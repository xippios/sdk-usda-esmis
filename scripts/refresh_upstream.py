# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.uv]
# exclude-newer = "2026-10-27T00:00:00Z"
# ///
"""Refresh the upstream documentation snapshot in ``docs/upstream/`` (``/refresh-upstream``).

ESMIS, the Economics, Statistics, and Market Information System of USDA's National
Agricultural Library (https://esmis.nal.usda.gov), documents its API in an OpenAPI
document that its ``/api-documentation`` page names. The script writes:

- ``openapi/esmis_public_api.yaml``: the OpenAPI document, byte for byte;
- ``pages/publication-wasde.md`` and ``pages/release-wasde.md``: the WASDE publication
  page and its newest release's view page, converted to Markdown;
- ``pages/release-calendar.md``: an excerpt of the release calendar;
- ``FETCHED.md``: regenerated entirely, one row per file and per page recorded without
  a file.

How each is captured is stated once, in the ``FETCHED.md`` this script writes
(``render_fetched``). Everything is fetched before anything is written. A page whose
structure the converter does not know, or one that starts to state a copyright, a
licence or terms of use, stops the run. Files under ``openapi/`` and ``pages/`` that the
run does not produce are removed; nothing else under ``docs/upstream/`` is touched. No
key is needed or read. Run from the repository root::

    uv run scripts/refresh_upstream.py
"""

import argparse
import hashlib
import http.client
import json
import re
import textwrap
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import IO, Any
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs/upstream"
COMMAND = "uv run scripts/refresh_upstream.py"

SITE = "https://esmis.nal.usda.gov"
HOST = "esmis.nal.usda.gov"
"""The host the OpenAPI document's URL, read from the documentation page, must have."""
DOCS_URL = f"{SITE}/api-documentation"
PUBLICATION_URL = f"{SITE}/publication/world-agricultural-supply-and-demand-estimates"
CALENDAR_URL = f"{SITE}/release-calendar"
CORNELL_URL = "https://usda.library.cornell.edu/api"
"""ESMIS's API address at Cornell's Mann Library, its home until 2025-10-01."""
CORNELL_TARGET = f"{SITE}/api"
POLICIES_URL = "https://www.usda.gov/policies-and-links"
QUALITY_URL = "https://www.ars.usda.gov/docs/quality-of-information/"
"""The two footer links that could carry terms of use; the script reads both."""
FOOTER_LABEL = "Government Links"
"""The ``aria-label`` of the footer's list of links."""
SWAGGER_KEY = ("swaggerUIFormatter", "swagger_file-0", "swaggerFile")
"""Where the documentation page's ``drupal-settings-json`` names the OpenAPI document."""

YAML_FILE = "openapi/esmis_public_api.yaml"
PUBLICATION_FILE = "pages/publication-wasde.md"
RELEASE_FILE = "pages/release-wasde.md"
CALENDAR_FILE = "pages/release-calendar.md"
SUBDIRS = ("openapi", "pages")
CALENDAR_EVENTS = 10
"""How many of the calendar's events the excerpt keeps, in upstream order."""

USER_AGENT = "xippios-usda-esmis refresh_upstream (+https://github.com/xippios)"
TIMEOUT = 60.0
PAUSE = 2.0
"""Seconds before every request; requests never run in parallel."""
RETRY_PAUSE = 10.0
"""Seconds before the one retry after a network error or a 5xx."""

_STATEMENT = re.compile(
    r"\N{COPYRIGHT SIGN}|copyright|public domain|licen[cs]e|terms of (?:use|service)",
    re.IGNORECASE,
)
_SETTINGS = "drupal-settings-json"
_RELEASES_BLOCK = "block-views-blockpublication-releases-indexed-all-releases-block"
_LATEST_BLOCK = "block-views-blockpublication-releases-latest-release-block"
_RELEASE_PATH = re.compile(r"/\d{4}-\d{2}-\d{2}(?:-\d+)?")
_MONTH = re.compile(r"\d{4}-\d{2}")
_PAGE = re.compile(r"\?page=(\d+)")
_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_NO_TEXT = frozenset({"script", "style", "svg", "template", "noscript"})
_INLINE = frozenset({"span", "div", "ul", "li"})
"""Elements whose content is kept inline as it stands; any other one stops the run."""


@dataclass
class _Tally:
    """HTTP requests sent by this run, redirects and retries included."""

    requests: int = 0


_TALLY = _Tally()


@dataclass(frozen=True)
class Response:
    """One GET as served: status, body and validators, and any redirects on the way."""

    url: str
    status: int
    body: bytes
    etag: str | None
    last_modified: str | None
    redirects: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class Row:
    """One row of the ``FETCHED.md`` table, with the snapshot file it produced, if any."""

    response: Response
    note: str
    path: str | None = None
    content: bytes | None = None
    body_kept: bool = True
    """False for a body recorded by status only: no size, sha256 or validators."""


class _RetryableError(Exception):
    """A network error or a 5xx: worth one more attempt."""


class _RecordRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects as urllib does, remembering each status and target."""

    def __init__(self) -> None:
        super().__init__()
        self.hops: list[tuple[int, str]] = []

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Record the hop, then let urllib build the follow-up request."""
        self.hops.append((code, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _log(message: str) -> None:
    print(message, flush=True)  # noqa: T201


def _get(url: str, expect: int) -> Response:
    redirects = _RecordRedirects()
    opener = urllib.request.build_opener(redirects)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            body: bytes = response.read()
            status: int = response.status
            headers = response.headers
    except urllib.error.HTTPError as error:
        if error.code >= 500:
            raise _RetryableError(f"HTTP {error.code} {error.reason}") from None
        if error.code != expect:
            raise SystemExit(f"GET {url}: HTTP {error.code} {error.reason}") from None
        body, status, headers = error.read(), error.code, error.headers
    except (http.client.HTTPException, OSError) as error:  # URLError is an OSError
        raise _RetryableError(str(error)) from None
    finally:
        _TALLY.requests += 1 + len(redirects.hops)
    if status != expect:
        raise SystemExit(f"GET {url}: expected HTTP {expect}, got {status}")
    encoding = headers.get("Content-Encoding", "identity").strip().lower()
    if encoding != "identity":
        raise SystemExit(f"GET {url}: unexpected Content-Encoding {encoding!r}")
    return Response(
        url,
        status,
        body,
        headers.get("ETag"),
        headers.get("Last-Modified"),
        tuple(redirects.hops),
    )


def fetch(url: str, expect: int = 200) -> Response:
    """GET ``url`` after a polite pause; retry once on a network error or a 5xx."""
    time.sleep(PAUSE)
    try:
        response = _get(url, expect)
    except _RetryableError as error:
        _log(f"  {url}: {error}; retrying once in {RETRY_PAUSE:.0f} s")
        time.sleep(RETRY_PAUSE)
        try:
            response = _get(url, expect)
        except _RetryableError as error:
            raise SystemExit(f"GET {url}: {error} (after one retry)") from None
    digest = hashlib.sha256(response.body).hexdigest()
    hops = "".join(f", {code} to {target}" for code, target in response.redirects)
    _log(
        f"  {url}: HTTP {response.status}{hops}, {len(response.body)} bytes, sha256 {digest}, "
        f"Last-Modified {response.last_modified or '-'}, ETag {response.etag or '-'}"
    )
    return response


def _page_changed(url: str, what: str) -> SystemExit:
    return SystemExit(
        f"{url} changed: {what}.\nLook at the page by hand and update "
        "scripts/refresh_upstream.py. Nothing was written."
    )


def _text(response: Response) -> str:
    try:
        return response.body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise _page_changed(response.url, f"body is not UTF-8 ({error})") from None


def _no_statement(response: Response, text: str) -> None:
    """Stop if ``text`` states a copyright, licence or terms, which Attribution denies."""
    match = _STATEMENT.search(text)
    if match:
        raise SystemExit(
            f"GET {response.url}: the page now states {match.group(0)!r}, a copyright, "
            "licence or terms of use, which FETCHED.md's Attribution says none of the pages "
            "does.\nRead the statement by hand, quote it in render_fetched and update "
            "scripts/refresh_upstream.py. Nothing was written."
        )


def _redirect_note(response: Response) -> str:
    return "".join(f"redirected ({code}) to {target}; " for code, target in response.redirects)


def _squash(text: str) -> str:
    return " ".join(text.split())


# --- HTML to a tree -------------------------------------------------------------------


@dataclass
class Element:
    """One HTML element as ``html.parser`` reads it: tag, attributes and children."""

    tag: str
    attrs: dict[str, str]
    children: list["Element | str"] = field(default_factory=list)

    def has_class(self, name: str) -> bool:
        """Whether ``name`` is one of the element's classes."""
        return name in self.attrs.get("class", "").split()

    def elements(self) -> Iterator["Element"]:
        """Every element below this one, depth first, in document order."""
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.elements()

    def find_all(self, tag: str, cls: str | None = None) -> list["Element"]:
        """The elements below this one with ``tag`` and, if given, the class ``cls``."""
        return [
            item
            for item in self.elements()
            if item.tag == tag and (cls is None or item.has_class(cls))
        ]

    def child_elements(self) -> list["Element"]:
        """The direct children that are elements."""
        return [child for child in self.children if isinstance(child, Element)]

    def raw_text(self) -> str:
        """The text below this element as parsed, scripts and styles left out."""
        if self.tag in _NO_TEXT:
            return ""
        return "".join(
            child if isinstance(child, str) else child.raw_text() for child in self.children
        )

    def text(self) -> str:
        """The visible text, whitespace collapsed (a no-break space counts as one)."""
        return _squash(self.raw_text())


class _TreeBuilder(HTMLParser):
    """Build an ``Element`` tree; an end tag closes the nearest open element it names."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {})
        self._open = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open an element, or add a void one."""
        element = Element(tag, {name: value or "" for name, value in attrs})
        self._open[-1].children.append(element)
        if tag not in _VOID:
            self._open.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Add a self-closed element."""
        self._open[-1].children.append(Element(tag, {name: value or "" for name, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        """Close the nearest open element named ``tag``; ignore a stray end tag."""
        for index in range(len(self._open) - 1, 0, -1):
            if self._open[index].tag == tag:
                del self._open[index:]
                return

    def handle_data(self, data: str) -> None:
        """Keep text where it stands."""
        self._open[-1].children.append(data)


def parse_html(text: str) -> Element:
    """The document's element tree."""
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()
    return builder.root


@dataclass(frozen=True)
class Page:
    """A fetched HTML page: its URL and its tree."""

    url: str
    root: Element

    def one(self, within: Element, tag: str, cls: str | None = None) -> Element:
        """The one element ``tag`` (with class ``cls``) below ``within``."""
        found = within.find_all(tag, cls)
        if len(found) != 1:
            what = f"<{tag}>" + (f" of class {cls!r}" if cls else "")
            raise _page_changed(self.url, f"expected one {what}, found {len(found)}")
        return found[0]

    def main(self) -> Element:
        """The page's ``<main>``, its breadcrumbs removed."""
        main = self.one(self.root, "main")
        for parent in [main, *main.elements()]:
            parent.children = [
                child
                for child in parent.children
                if not (
                    isinstance(child, Element) and child.has_class("block-system-breadcrumb-block")
                )
            ]
        return main

    def settings(self) -> dict[str, Any]:
        """The page's ``drupal-settings-json``."""
        scripts = [
            item
            for item in self.root.find_all("script")
            if item.attrs.get("data-drupal-selector") == _SETTINGS
        ]
        if len(scripts) != 1:
            raise _page_changed(self.url, f"expected one {_SETTINGS}, found {len(scripts)}")
        text = "".join(child for child in scripts[0].children if isinstance(child, str))
        try:
            settings = json.loads(text)
        except ValueError as error:
            raise _page_changed(self.url, f"{_SETTINGS} is not JSON ({error})") from None
        if not isinstance(settings, dict):
            raise _page_changed(self.url, f"{_SETTINGS} is not an object")
        return settings


def html_page(response: Response) -> Page:
    """Parse a fetched page; stop if its visible text states a copyright, licence or terms.

    The visible text leaves scripts out, so the publication titles in a page's
    ``drupal-settings-json`` cannot trip the check.
    """
    page = Page(response.url, parse_html(_text(response)))
    _no_statement(response, page.root.text())
    return page


# --- the tree to Markdown -------------------------------------------------------------


def _cell(value: str) -> str:
    return value.replace("|", r"\|")


def inline(page: Page, node: Element) -> str:
    """Markdown for the content of ``node``, whitespace not yet collapsed.

    A link becomes ``[text](absolute URL)``, a ``<time>`` its text with its ``datetime``
    in parentheses; screen-reader-only text is left out, two links side by side get a
    space between them. An element outside ``_INLINE`` stops the run.
    """
    parts: list[str] = []
    previous_link = False
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
            previous_link = previous_link and not child.strip()
            continue
        if child.tag in _NO_TEXT or child.has_class("usa-sr-only"):
            continue
        if child.tag == "a" and previous_link:
            parts.append(" ")
        inner = inline(page, child)
        if child.tag == "a" and "href" in child.attrs:
            parts.append(f"[{_squash(inner)}]({urljoin(page.url, child.attrs['href'])})")
        elif child.tag == "time" and "datetime" in child.attrs:
            parts.append(f"{inner} (`{child.attrs['datetime']}`)")
        elif child.tag in _INLINE:
            parts.append(inner)
        else:
            raise _page_changed(page.url, f"an inline <{child.tag}> the script does not convert")
        previous_link = child.tag == "a"
    return "".join(parts)


def paragraphs(page: Page, node: Element) -> list[str]:
    """Markdown for a field's text: its ``<p>`` elements, through any ``<div>``."""
    lines: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                raise _page_changed(page.url, "loose text beside a field's paragraphs")
        elif child.tag == "p":
            text = _squash(inline(page, child))
            lines += [text, ""] if text else []
        elif child.tag == "div":
            lines += paragraphs(page, child)
        else:
            raise _page_changed(page.url, f"a <{child.tag}> in a field's text")
    return lines


def table(page: Page, node: Element) -> list[str]:
    """A pipe table for an HTML table without merged cells or nested tables."""
    cells = [*node.find_all("th"), *node.find_all("td")]
    if node.find_all("table") or any("rowspan" in c.attrs or "colspan" in c.attrs for c in cells):
        raise _page_changed(
            page.url,
            "a table with merged cells or a nested table, which this script does not convert "
            "yet; extend it to keep such a table as HTML (conventions §3)",
        )
    rows = [
        [
            _cell(_squash(inline(page, cell)))
            for cell in row.child_elements()
            if cell.tag in {"th", "td"}
        ]
        for row in node.find_all("tr")
    ]
    if not rows or not node.find_all("thead"):
        raise _page_changed(page.url, "a table without a header row")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise _page_changed(page.url, "a table whose rows differ in length")
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return [*lines, ""]


def field_lines(page: Page, node: Element) -> list[str]:
    """A labelled Drupal field: one list item, or a label and a table for a file list."""
    label = page.one(node, "div", "field__label")
    files = node.find_all("div", "nal-file")
    if files:
        lines = [f"**{label.text()}**:", "", "| File | Type | Size |", "| --- | --- | --- |"]
        for item in files:
            link = page.one(item, "a")
            size = page.one(item, "span", "nal-file__size")
            href = urljoin(page.url, link.attrs.get("href", ""))
            lines.append(
                f"| [{_cell(link.text())}]({href}) | `{link.attrs.get('type', '')}` "
                f"| {_cell(size.text())} |"
            )
        return [*lines, ""]
    rest = Element("div", {}, [child for child in node.children if child is not label])
    return [f"- **{label.text()}**: {_squash(inline(page, rest))}"]


def _list_end(lines: list[str]) -> list[str]:
    """Close a run of list items with a blank line before the next block."""
    return [*lines, ""] if lines and lines[-1].startswith("- ") else lines


def date_filter(page: Page, form: Element) -> str:
    """One line for the release list's filter form: its select and the months offered."""
    selects = form.find_all("select")
    inputs = [item for item in form.find_all("input") if item.attrs.get("type") != "hidden"]
    if len(selects) != 1 or inputs:
        raise _page_changed(
            page.url, f"the filter has {len(selects)} selects, {len(inputs)} inputs"
        )
    values = [option.attrs.get("value", "") for option in selects[0].find_all("option")]
    months = values[1:]
    if values[:1] != ["All"] or not months or not all(_MONTH.fullmatch(v) for v in months):
        raise _page_changed(page.url, "the filter offers more than All and months as YYYY-MM")
    return (
        f"The list's filter form (`{form.attrs.get('method', '').upper()} "
        f"{form.attrs.get('action', '')}`) offers, in the select "
        f"`{selects[0].attrs.get('name', '')}`, `All` and months as `YYYY-MM`, from "
        f"`{min(months)}` to `{max(months)}`."
    )


def paging(page: Page, nav: Element) -> tuple[int, int]:
    """The ``?page=N`` of the paging links labelled "Page 1" and "Last page"."""
    found: dict[str, int] = {}
    for link in nav.find_all("a"):
        label = link.attrs.get("aria-label", "")
        match = _PAGE.fullmatch(link.attrs.get("href", ""))
        if label in {"Page 1", "Last page"} and match:
            found[label] = int(match.group(1))
    if set(found) != {"Page 1", "Last page"}:
        raise _page_changed(page.url, "no paging links labelled Page 1 and Last page")
    return found["Page 1"], found["Last page"]


def views_block(page: Page, node: Element) -> list[str]:
    """A Drupal views block: its heading, filter form, table and paging controls."""
    lines: list[str] = []
    for child in node.child_elements():
        if child.tag == "h2":
            lines += [f"## {child.text()}", ""]
        elif child.tag == "form":
            lines += [date_filter(page, child), ""]
        elif child.tag == "table":
            lines += table(page, child)
        elif child.tag == "nav" and child.has_class("usa-pagination"):
            first, last = paging(page, child)
            lines += [
                f'The list pages with `?page=N`: "Page 1" is `?page={first}`, the last page '
                f"`?page={last}`.",
                "",
            ]
        elif child.tag == "div":
            lines += views_block(page, child)
        else:
            raise _page_changed(page.url, f"a views block holds a <{child.tag}>")
    if any(isinstance(child, str) and child.strip() for child in node.children):
        raise _page_changed(page.url, "a views block holds loose text")
    return lines


def _converted(url: str) -> list[str]:
    return _paragraph(
        f"Converted from {url} by `scripts/refresh_upstream.py`; see `../FETCHED.md`."
    )


def _first_row(page: Page, block: Element) -> Element:
    rows = page.one(block, "tbody").find_all("tr")
    if not rows:
        raise _page_changed(page.url, "a release table without rows")
    return rows[0]


def _release_key(row: Element) -> tuple[str, ...]:
    """A release row's date and file links, to compare two tables' rows."""
    times = [item.attrs.get("datetime", "") for item in row.find_all("time")[:1]]
    files = sorted(
        link.attrs.get("href", "")
        for link in row.find_all("a")
        if "/release-files/" in link.attrs.get("href", "")
    )
    return (*times, *files)


def publication_markdown(page: Page) -> tuple[str, str, int]:
    """The publication page as Markdown, its newest release's URL and its last page."""
    main = page.main()
    article = page.one(main, "article", "node--type-publication")
    lines = [f"# {page.one(main, 'h1').text()}", "", *_converted(page.url)]
    regions = [item for item in article.elements() if item.has_class("layout__region")]
    if not regions:
        raise _page_changed(page.url, "no layout regions in the publication article")
    for region in regions:
        for block in region.child_elements():
            if not block.has_class("block"):
                raise _page_changed(page.url, f"a region holds a <{block.tag}>, not a block")
            if block.has_class("block-views"):
                lines = _list_end(lines) + views_block(page, block)
            elif block.find_all("div", "field__label"):
                for item in block.find_all("div", "field"):
                    lines += field_lines(page, item)
            elif block.find_all("div", "field__item"):
                lines = _list_end(lines) + paragraphs(page, block)
            else:
                raise _page_changed(page.url, f"a block of class {block.attrs.get('class')!r}")

    releases = page.one(article, "div", _RELEASES_BLOCK)
    first = _first_row(page, releases)
    latest = _release_key(_first_row(page, page.one(article, "div", _LATEST_BLOCK)))
    if _release_key(first) != latest:
        raise _page_changed(
            page.url,
            f"the release list's first row {_release_key(first)} is not the Latest Release "
            f"{latest}, so the newest release is unclear",
        )
    path = urlsplit(page.url).path
    views = [link for link in first.find_all("a") if link.text() == "View"]
    href = views[0].attrs.get("href", "") if len(views) == 1 else ""
    if not href.startswith(f"{path}/") or not _RELEASE_PATH.fullmatch(href[len(path) :]):
        raise _page_changed(page.url, f"the first release's View link is {href!r}")
    _, last = paging(page, page.one(releases, "nav", "usa-pagination"))
    return _join(_list_end(lines)), urljoin(page.url, href), last


def release_markdown(page: Page) -> str:
    """A release view page as Markdown: its fields in page order."""
    main = page.main()
    article = page.one(main, "article", "node--type-release")
    lines = [f"# {page.one(main, 'h1').text()}", "", *_converted(page.url)]
    fields = article.find_all("div", "field")
    if not fields:
        raise _page_changed(page.url, "no fields in the release article")
    for item in fields:
        if item.find_all("div", "nal-file"):
            lines = _list_end(lines)
        lines += field_lines(page, item)
    if article.text() != _squash(" ".join(item.text() for item in fields)):
        raise _page_changed(page.url, "the release article holds text outside its fields")
    return _join(_list_end(lines))


def calendar_markdown(page: Page) -> tuple[str, int]:
    """The calendar excerpt, and the number of events the page holds."""
    main = page.main()
    title = page.one(main, "h1").text()
    if not main.find_all("div", "fullcalendar--wrapper"):
        raise _page_changed(page.url, "no fullcalendar container in the main content")
    if main.text() != title or main.find_all("table"):
        raise _page_changed(page.url, "the main content holds more than a heading and a calendar")
    calendars = page.settings().get("fullcalendar")
    if not isinstance(calendars, dict) or len(calendars) != 1:
        raise _page_changed(page.url, "expected one calendar under fullcalendar")
    settings = next(iter(calendars.values()))
    options = settings.get("options") if isinstance(settings, dict) else None
    if not isinstance(settings, dict) or not isinstance(options, dict):
        raise _page_changed(page.url, "the calendar's settings have no options object")
    sources = options.get("eventSources")
    if not isinstance(sources, list) or not all(isinstance(s, list) for s in sources):
        raise _page_changed(page.url, "options.eventSources is not a list of event lists")
    events: list[Any] = [event for source in sources for event in source]
    if not events or not all(isinstance(event, dict) for event in events):
        raise _page_changed(page.url, "no events, or events that are not objects")
    names = list(events[0])
    if any(list(event) != names for event in events):
        raise _page_changed(page.url, "the events no longer all have the same fields")
    starts = []
    for event in events:
        try:
            starts.append(datetime.fromisoformat(str(event["start"])))
        except (KeyError, ValueError):
            raise _page_changed(page.url, f"an event's start is not ISO 8601: {event}") from None
    shown = {
        **settings,
        "options": {key: value for key, value in options.items() if key != "eventSources"},
    }
    ids = {json.dumps(event.get("id")) for event in events}
    kept = events[:CALENDAR_EVENTS]
    lines = [
        f"# {title}",
        "",
        *_paragraph(
            f"An excerpt of {page.url} by `scripts/refresh_upstream.py`; see `../FETCHED.md`.",
            "The page's main content is the heading above and an empty calendar container,",
            "which the browser fills from the events in the page's `drupal-settings-json`.",
        ),
        "## Calendar settings",
        "",
        *_paragraph(
            "The page's `drupal-settings-json` holds one calendar under `fullcalendar`, keyed",
            "by a view DOM id (left out here). Its settings, `options.eventSources` left out,",
            "re-serialised with `json.dumps`, values as fetched:",
        ),
        "```json",
        json.dumps(shown, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Events",
        "",
        *_paragraph(
            f"`options.eventSources` holds {len(sources)}",
            "event source" if len(sources) == 1 else "event sources",
            f"with {len(events)} events in all, for {len(ids)} distinct `id`s, their `start`",
            f"from `{min(starts).isoformat()}` to `{max(starts).isoformat()}`. Every event has",
            "the same fields, in this order:",
            ", ".join(f"`{name}`" for name in names) + f". The first {len(kept)} events, one",
            "JSON object per line, re-serialised with `json.dumps`, values as fetched:",
        ),
        "```json",
        *(json.dumps(event, ensure_ascii=False) for event in kept),
        "```",
        "",
        f"\N{HORIZONTAL ELLIPSIS} {len(events) - len(kept)} more events not kept",
    ]
    return _join(lines), len(events)


def _join(lines: list[str]) -> str:
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


# --- the pages ------------------------------------------------------------------------


def documentation_page() -> tuple[Row, str, int]:
    """Record the API documentation page; read the OpenAPI URL and the footer from it."""
    response = fetch(DOCS_URL)
    page = html_page(response)
    article = page.one(page.main(), "article", "node--type-api-documentation")
    if article.text() or not any(
        item.attrs.get("id", "").startswith("swagger-ui-") for item in article.elements()
    ):
        raise _page_changed(page.url, "the article is no longer an empty Swagger UI container")
    value: Any = page.settings()
    for key in SWAGGER_KEY:
        if not isinstance(value, dict) or key not in value:
            raise _page_changed(page.url, f"{_SETTINGS} has no {'.'.join(SWAGGER_KEY)}")
        value = value[key]
    formatters = page.settings().get(SWAGGER_KEY[0])
    if not isinstance(value, str) or not isinstance(formatters, dict) or len(formatters) != 1:
        raise _page_changed(page.url, f"expected one Swagger UI file under {SWAGGER_KEY[0]}")
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.netloc != HOST:
        raise _page_changed(page.url, f"the OpenAPI document's URL {value!r} left https://{HOST}")
    footer = [
        nav for nav in page.root.find_all("nav") if nav.attrs.get("aria-label") == FOOTER_LABEL
    ]
    links = [link.attrs.get("href", "") for nav in footer for link in nav.find_all("a")]
    missing = [url for url in (POLICIES_URL, QUALITY_URL) if url not in links]
    if len(footer) != 1 or missing:
        raise _page_changed(page.url, f"the footer's {FOOTER_LABEL!r} no longer links {missing}")
    note = (
        f"{_redirect_note(response)}Drupal page whose main content is an empty Swagger UI "
        f"container, no documentation text; its `drupal-settings-json` names the OpenAPI "
        f"document at `{'.'.join(SWAGGER_KEY)}`: `{value}`"
    )
    return Row(response, note), value, len(links)


def openapi_row(url: str) -> Row:
    """Fetch the OpenAPI document; it is kept byte for byte, so only read, never parsed."""
    response = fetch(url)
    text = _text(response)
    _no_statement(response, text)
    version = re.match(r"openapi:\s*(3\.\S*)", text)
    info = re.search(r"^info:[^\n]*\n((?:[ \t][^\n]*\n|\r?\n)*)", text, re.MULTILINE)
    if not version or not info:
        raise SystemExit(f"GET {url}: not an OpenAPI 3 document with an info object")
    stated = re.findall(r"^  (license|termsOfService|contact):", info.group(1), re.MULTILINE)
    if stated:
        raise SystemExit(
            f"GET {url}: info now names {stated}, which FETCHED.md's Attribution says it "
            "does not.\nLook at the document by hand and update scripts/refresh_upstream.py. "
            "Nothing was written."
        )
    count = len(re.findall(r"^[ \t]+operationId:", text, re.MULTILINE))
    if not count:
        raise SystemExit(f"GET {url}: no operationId in the document")
    secured = re.search(r"^(?:security:|[ \t]+securitySchemes:)", text, re.MULTILINE)
    crlf, lf = response.body.count(b"\r\n"), response.body.count(b"\n")
    endings = "CRLF" if crlf == lf else "LF" if not crlf else "mixed"
    note = (
        f"{_redirect_note(response)}verbatim, byte for byte ({endings} line endings, as "
        f"served); OpenAPI {version.group(1)}, {count} operations by `operationId`; "
        + ("declares security; " if secured else "no `securitySchemes` or `security`; ")
        + "`info` names no licence, terms of service or contact"
    )
    return Row(response, note, YAML_FILE, response.body)


def publication_row() -> tuple[Row, str]:
    """Fetch and convert the publication page; return its newest release's URL too."""
    response = fetch(PUBLICATION_URL)
    content, release_url, last = publication_markdown(html_page(response))
    note = (
        f"{_redirect_note(response)}converted to Markdown; Bytes and sha256 are the HTML "
        f"page's; the first of the release list's {last + 1} pages (`?page=0` to "
        f"`?page={last}`), which changes with every release"
    )
    return Row(response, note, PUBLICATION_FILE, content.encode("utf-8")), release_url


def release_row(url: str) -> Row:
    """Fetch and convert the newest release's view page."""
    response = fetch(url)
    content = release_markdown(html_page(response))
    note = (
        f"{_redirect_note(response)}converted to Markdown; Bytes and sha256 are the HTML "
        "page's; the view page of the newest release in the publication page's list, so "
        "the URL changes with every release"
    )
    return Row(response, note, RELEASE_FILE, content.encode("utf-8"))


def calendar_row() -> Row:
    """Fetch the release calendar and keep its excerpt."""
    response = fetch(CALENDAR_URL)
    content, events = calendar_markdown(html_page(response))
    note = (
        f"{_redirect_note(response)}excerpt, not the page: the heading, the calendar's "
        f"settings and the first {CALENDAR_EVENTS} of its {events} events from the page's "
        "`drupal-settings-json`; Bytes and sha256 are the full page's"
    )
    return Row(response, note, CALENDAR_FILE, content.encode("utf-8"))


def cornell_row() -> Row:
    """Record the former API address at Cornell: a redirect to a 404, status only."""
    response = fetch(CORNELL_URL, expect=404)
    if response.redirects != ((301, CORNELL_TARGET),):
        raise _page_changed(CORNELL_URL, f"redirects {response.redirects}, not 301 to the API")
    note = (
        f"{_redirect_note(response)}ESMIS's API address at Cornell's Mann Library before the "
        "move to the National Agricultural Library; status only, no body kept"
    )
    return Row(response, note, body_kept=False)


def policies_row() -> Row:
    """Record USDA's Policies and Links page, which the CDN refuses to this script."""
    response = fetch(POLICIES_URL, expect=403)
    if b"Access Denied" not in response.body:
        raise _page_changed(POLICIES_URL, "HTTP 403 without 'Access Denied' in the body")
    note = (
        f'{_redirect_note(response)}the footer\'s "Policies and Links"; 403 Access Denied at '
        "the CDN edge, so what it states is not read; the body carries a per-request "
        "reference, so no size or sha256 is recorded"
    )
    return Row(response, note, body_kept=False)


def quality_row() -> Row:
    """Record the Information Quality page the footer links to; it states no licence."""
    response = fetch(QUALITY_URL)
    _no_statement(response, parse_html(_text(response)).text())
    note = (
        f'{_redirect_note(response)}the footer\'s "Information Quality" (ARS); states no '
        "copyright, licence or terms of use"
    )
    return Row(response, note)


# --- FETCHED.md -----------------------------------------------------------------------


def _iso_http_date(value: str | None) -> str:
    if value is None:
        return "-"
    return parsedate_to_datetime(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _paragraph(*sentences: str) -> list[str]:
    text = " ".join(sentences)
    wrapped = textwrap.fill(text, width=88, break_long_words=False, break_on_hyphens=False)
    return [*wrapped.splitlines(), ""]


def render_fetched(rows: list[Row], yaml_url: str, footer_links: int, fetched: str) -> str:
    """The whole of ``FETCHED.md``: the one statement of how the snapshot is captured."""
    lines = [
        "# Upstream documentation snapshot \N{EM DASH} USDA ESMIS",
        "",
        *_paragraph(
            "Source of truth for every endpoint wrapper (ADR-0003). The files in this",
            "directory are written by `scripts/refresh_upstream.py` (`/refresh-upstream`)",
            "from the pages and the document in the table below and refreshed deliberately by",
            "PR, so that changes show up as diffs. This file is generated by the same script.",
            "Nothing here was edited by hand.",
        ),
        "## Attribution",
        "",
        *_paragraph(
            "None stated. The visible text of the ESMIS pages this script fetches (the API",
            "documentation page, a publication page, a release page and the release",
            "calendar) carries no copyright line, licence or terms of use, and the OpenAPI",
            "document's `info` names no licence, terms of service or contact. The site's",
            f'footer lists {footer_links} links under "{FOOTER_LABEL}"; two of them could',
            f'carry terms of use and are the ones read: "Policies and Links", {POLICIES_URL},',
            "which the CDN edge answers with 403 Access Denied to this script, so what it",
            f'states is not read here; and "Information Quality", {QUALITY_URL}, which',
            "states no copyright, licence or terms of use. The script stops if any page it",
            "reads starts to state one. The documentation's text is reproduced here as this",
            "package's reference (ADR-0003); an objection from the publisher is met by",
            "replacing it with a summary that keeps the names and semantics the wrappers rely",
            "on.",
        ),
        "## How this is captured",
        "",
        *_paragraph(
            f"ESMIS documents its API on {DOCS_URL}, a Drupal page whose main content is an",
            "empty Swagger UI container. The Swagger UI renders the OpenAPI document that the",
            f"page's `drupal-settings-json` names at `{'.'.join(SWAGGER_KEY)}`, as of this run",
            f"{yaml_url}. The script reads the URL from there, stops if the key is gone or the",
            f"URL leaves https://{HOST}, and saves the document verbatim, byte for byte, as",
            f"`{YAML_FILE}`, with the line endings it is served with; `.gitattributes` keeps",
            "`docs/upstream/**` as `-text`, so git does not convert them. The documentation",
            "page itself gets a row without a file.",
        ),
        *_paragraph(
            "The publication page of the World Agricultural Supply and Demand Estimates",
            "(WASDE) and the view page of its newest release, the first row of the",
            "publication's release list, are converted to Markdown with the standard",
            "library's `html.parser`. The page's main content is kept; its breadcrumbs, the",
            "site's header, navigation and footer and the screen-reader-only text inside",
            "links are dropped. Links become absolute URLs and a date its text with its",
            "`datetime` attribute in parentheses; the release list's date filter and its",
            "paging controls become one line each, the months offered and the last page. No",
            "table on these pages has merged cells or a nested table, so none is kept as",
            "HTML. The run stops on a page structure the converter does not know, and when",
            "the release list's first row is not the page's Latest Release. Both files change",
            "with every release; their rows' Bytes and sha256 are those of the HTML pages.",
        ),
        *_paragraph(
            "The release calendar has no HTML table: the browser draws it from the events in",
            f"the page's `drupal-settings-json`. `{CALENDAR_FILE}` is an excerpt: the page's",
            "heading, the calendar's settings without the events, the events' count and field",
            f"names, and the first {CALENDAR_EVENTS} events, one JSON object per line, all",
            "re-serialised with `json.dumps`, values as fetched (upstream writes `/` as `\\/`);",
            "then a line counting the events not kept. Its row's Bytes and sha256 are those",
            "of the full page, and its Last-Modified is the time Drupal last rendered it; on",
            "2026-10-27 two runs 1.5 minutes apart gave identical bytes.",
        ),
        *_paragraph(
            "Pages without documentation text get no file, only a row: the API documentation",
            "page, with its HTTP status and the size and sha256 of its body; ESMIS's former",
            f"API address at Cornell's Mann Library, {CORNELL_URL}, which redirects to",
            f"{CORNELL_TARGET}, which answers 404, recorded by status only; and the two",
            "footer pages under Attribution, USDA's by status only, since its 403 body",
            "carries a per-request reference.",
        ),
        *_paragraph(
            "Against the same upstream, two runs write byte-identical files under `openapi/`",
            "and `pages/`, and this file differs in its Fetched column and in the ETag and",
            "Last-Modified of any ESMIS page that Drupal rendered anew in between. Drupal",
            "renders these pages into a cache, and their ETag and Last-Modified are the time",
            "of that rendering, so a new rendering changes them even when the page is the",
            "same byte for byte. Ids that Drupal may generate per rendering",
            "(`js-view-dom-id-…`, form ids) are left out of the Markdown files; where a new",
            "rendering changes them, the page's Bytes and sha256 change here too.",
        ),
        *_paragraph(
            "Fetched is the UTC time the run started, in ISO 8601 with an explicit Z, the",
            "same for every row; Last-Modified is the HTTP header in UTC, ETag as sent.",
            f"Requests go one at a time, {PAUSE:.0f} s apart, each retried at most once,",
            f"identified as `{USER_AGENT}`; no API key is sent or read.",
        ),
        "## Files and pages",
        "",
        "| File | URL | Fetched | HTTP | Bytes | sha256 | ETag | Last-Modified | Note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        response = row.response
        kept = row.body_kept
        cells = [
            row.path or "(no file)",
            response.url,
            fetched,
            str(response.status),
            str(len(response.body)) if kept else "-",
            hashlib.sha256(response.body).hexdigest() if kept else "-",
            (response.etag or "-") if kept else "-",
            _iso_http_date(response.last_modified) if kept else "-",
            row.note,
        ]
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    lines += ["", f"Regenerate: `{COMMAND}`"]
    return "\n".join(lines) + "\n"


def write_snapshot(out: Path, rows: list[Row], fetched_md: str) -> None:
    """Write the files and ``FETCHED.md``; prune stale files under ``SUBDIRS``.

    Only files under ``openapi/`` and ``pages/`` that this run does not produce are removed.
    """
    if out.exists() and any(out.iterdir()) and not (out / "FETCHED.md").is_file():
        raise SystemExit(f"{out} is neither empty nor a snapshot (no FETCHED.md); not writing")
    files = {row.path: row.content for row in rows if row.path and row.content is not None}
    for subdir in SUBDIRS:
        directory = out / subdir
        directory.mkdir(parents=True, exist_ok=True)
        for path in sorted(directory.iterdir()):
            if path.is_file() and f"{subdir}/{path.name}" not in files:
                path.unlink()
                _log(f"  removed {subdir}/{path.name}: no longer produced")
    for name, content in files.items():
        (out / name).write_bytes(content)
    (out / "FETCHED.md").write_bytes(fetched_md.encode("utf-8"))


def main() -> None:
    """Fetch every document and page, then write the snapshot."""
    parser = argparse.ArgumentParser(description="Refresh docs/upstream/ from USDA ESMIS.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="snapshot directory")
    out: Path = parser.parse_args().out
    fetched = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    _log(f"API documentation: {DOCS_URL}")
    docs_page, yaml_url, footer_links = documentation_page()
    yaml_row = openapi_row(yaml_url)
    _log("Pages converted to Markdown")
    publication, release_url = publication_row()
    release = release_row(release_url)
    excerpt = calendar_row()
    _log("Pages recorded without a file")
    shells = [docs_page, cornell_row(), policies_row(), quality_row()]

    rows = [yaml_row, publication, release, excerpt, *shells]
    write_snapshot(out, rows, render_fetched(rows, yaml_url, footer_links, fetched))
    written = sum(1 for row in rows if row.path)
    _log(
        f"Wrote {written} files and FETCHED.md under {out} (Fetched {fetched}); "
        f"{_TALLY.requests} HTTP requests, redirects and retries included"
    )


if __name__ == "__main__":
    main()
