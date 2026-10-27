# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.uv]
# exclude-newer = "2026-10-27T00:00:00Z"
# ///
"""Refresh the upstream documentation snapshot in ``docs/upstream/`` (``/refresh-upstream``).

ESMIS, the Economics, Statistics, and Market Information System of USDA's National
Agricultural Library (https://esmis.nal.usda.gov), documents its API on a Drupal page,
``/api-documentation``, whose main content is an empty Swagger UI container: the Swagger
UI renders the OpenAPI document that the page's ``drupal-settings-json`` names at
``swaggerUIFormatter.swagger_file-0.swaggerFile``. The script reads that URL from the
page, stops if the key is gone or names another host, and writes:

- ``openapi/esmis_public_api.yaml``: the OpenAPI document verbatim, byte for byte;
- ``pages/publication-wasde.md``: the WASDE publication page converted to Markdown;
- ``pages/release-wasde.md``: the view page of that publication's newest release, the
  first row of the publication page's release list, converted the same way;
- ``pages/release-calendar.md``: an excerpt of the release calendar, a page that changes
  daily and draws its calendar in the browser from the events in its
  ``drupal-settings-json``: its heading, the calendar's settings, the events' field
  names and the first ``CALENDAR_EVENTS`` events as fetched, the rest counted;
- ``FETCHED.md``: regenerated entirely, one row per file and per page recorded without
  a file (the API documentation page; ESMIS's former API address at Cornell's Mann
  Library, status only; the two policy pages the site's footer links to).

Pages are converted with the standard library's ``html.parser``: the page's ``<main>``
content, breadcrumbs dropped, as are the header, navigation and footer outside it and the
screen-reader-only text inside links; links become absolute URLs, a ``<time>`` element
its text with its ``datetime`` in parentheses. A page whose structure the converter does
not know stops the run, so nothing is dropped unnoticed.

Everything is fetched before anything is written, one request at a time with a pause,
each URL retried at most once. Files under ``openapi/`` and ``pages/`` that the run does
not produce are removed; ``FETCHED.md`` is rewritten; nothing else under
``docs/upstream/`` is touched. Against the same upstream, two runs write byte-identical
files, but for the calendar excerpt, and ``FETCHED.md`` differs in its ``Fetched``
column, the UTC time the run started, and in the validators of any page Drupal rendered
anew in between (``FETCHED.md`` says how). The script stops if a page it reads starts to state
a copyright, a licence or terms of use, which ``FETCHED.md``'s Attribution says none
does. The API needs no key, and none is sent or read. Run from the repository root::

    uv run scripts/refresh_upstream.py
"""

import argparse
import calendar
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
    r"\N{COPYRIGHT SIGN}|&copy;|copyright|public domain|licen[cs]e|terms of (?:use|service)",
    re.IGNORECASE,
)
_SETTINGS = "drupal-settings-json"
_RELEASE_PATH = re.compile(r"/\d{4}-\d{2}-\d{2}(?:-\d+)?")
_MONTH = re.compile(r"(\d{4})-(\d{2})")
_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_NO_TEXT = frozenset({"script", "style", "svg", "template", "noscript"})
_BLOCKS = frozenset({"p", "div", "section", "ul", "ol", "table", "h2", "h3", "h4", "h5", "h6"})
_INLINE_MARKS = {"strong": "**", "b": "**", "em": "*", "i": "*", "code": "`"}


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
    _TALLY.requests += 1
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            body: bytes = response.read()
            status: int = response.status
            headers = response.headers
    except urllib.error.HTTPError as error:
        _TALLY.requests += len(redirects.hops)
        if error.code >= 500:
            raise _RetryableError(f"HTTP {error.code} {error.reason}") from None
        if error.code != expect:
            raise SystemExit(f"GET {url}: HTTP {error.code} {error.reason}") from None
        body, status, headers = error.read(), error.code, error.headers
    except (http.client.HTTPException, OSError) as error:  # URLError is an OSError
        _TALLY.requests += len(redirects.hops)
        raise _RetryableError(str(error)) from None
    else:
        _TALLY.requests += len(redirects.hops)
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
    """Stop if the page states a copyright, licence or terms, which Attribution denies."""
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
        """The text below this element as parsed, script and style left out."""
        if self.tag in _NO_TEXT:
            return ""
        return "".join(
            child if isinstance(child, str) else child.raw_text() for child in self.children
        )

    def text(self) -> str:
        """The visible text, whitespace collapsed (a no-break space counts as one)."""
        return " ".join(self.raw_text().split())


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
    """A fetched HTML page: its URL, its tree and the checks that stop a changed page."""

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

    def title(self, main: Element) -> str:
        """The text of the page's one ``<h1>``."""
        return self.one(main, "h1").text()

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

    def changed(self, what: str) -> SystemExit:
        """The error that stops the run on a page the converter does not know."""
        return _page_changed(self.url, what)


def html_page(response: Response) -> Page:
    """Parse a fetched page after checking it states no copyright, licence or terms."""
    text = _text(response)
    _no_statement(response, text)
    return Page(response.url, parse_html(text))


# --- the tree to Markdown -------------------------------------------------------------


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _cell(value: str) -> str:
    return value.replace("|", r"\|")


def inline(node: "Element | str", base: str) -> str:
    """Markdown for inline content, whitespace not yet collapsed.

    Links become ``[text](absolute URL)``, a ``<time>`` its text and its ``datetime`` in
    parentheses, ``<br>`` stays ``<br>``; screen-reader-only text and scripts are left out.
    Two links side by side get a space between them.
    """
    if isinstance(node, str):
        return node
    if node.tag in _NO_TEXT or node.has_class("usa-sr-only"):
        return ""
    if node.tag == "br":
        return "<br>"
    parts: list[str] = []
    previous_link = False
    for child in node.children:
        is_link = isinstance(child, Element) and child.tag == "a"
        if is_link and previous_link:
            parts.append(" ")
        parts.append(inline(child, base))
        if isinstance(child, Element) or child.strip():
            previous_link = is_link
    inner = "".join(parts)
    if node.tag == "a" and "href" in node.attrs:
        return f"[{_collapse(inner)}]({urljoin(base, node.attrs['href'])})"
    if node.tag == "time" and "datetime" in node.attrs:
        return f"{inner} (`{node.attrs['datetime']}`)"
    mark = _INLINE_MARKS.get(node.tag)
    if mark and _collapse(inner):
        return f"{mark}{_collapse(inner)}{mark}"
    return inner


def blocks(page: Page, node: Element) -> list[str]:
    """Markdown lines for block content: paragraphs, headings, lists and tables."""
    lines: list[str] = []
    run: list[Element | str] = []

    def flush() -> None:
        text = _collapse("".join(inline(item, page.url) for item in run))
        if text:
            lines.extend([text, ""])
        run.clear()

    for child in node.children:
        if isinstance(child, str) or child.tag not in _BLOCKS:
            run.append(child)
            continue
        flush()
        if child.tag == "p":
            run.append(child)
            flush()
        elif child.tag in {"ul", "ol"}:
            for number, item in enumerate(child.find_all("li"), start=1):
                bullet = f"{number}." if child.tag == "ol" else "-"
                lines.append(f"{bullet} {_collapse(inline(item, page.url))}")
            lines.append("")
        elif child.tag == "table":
            lines.extend(table(page, child))
        elif child.tag.startswith("h"):
            lines.extend([f"{'#' * int(child.tag[1])} {child.text()}", ""])
        else:
            lines.extend(blocks(page, child))
    flush()
    return lines


def table(page: Page, node: Element) -> list[str]:
    """A pipe table for an HTML table without merged cells or nested tables."""
    cells = [*node.find_all("th"), *node.find_all("td")]
    if node.find_all("table") or any("rowspan" in c.attrs or "colspan" in c.attrs for c in cells):
        raise page.changed(
            "a table with merged cells or a nested table, which this script does not convert "
            "yet; extend it to keep such a table as HTML (conventions §3)"
        )
    rows: list[list[str]] = []
    for row in node.find_all("tr"):
        rows.append(
            [
                _cell(_collapse(inline(cell, page.url)))
                for cell in row.child_elements()
                if cell.tag in {"th", "td"}
            ]
        )
    if not rows or not node.find_all("thead"):
        raise page.changed("a table without a header row")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise page.changed("a table whose rows differ in length")
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
    return [f"- **{label.text()}**: {_collapse(inline(rest, page.url))}"]


def _list_end(lines: list[str]) -> list[str]:
    """Close a run of list items with a blank line before the next block."""
    return [*lines, ""] if lines and lines[-1].startswith("- ") else lines


def date_filter(page: Page, form: Element) -> list[str]:
    """The release list's filter form: its target, its one select and the months offered."""
    selects = form.find_all("select")
    inputs = [item for item in form.find_all("input") if item.attrs.get("type") != "hidden"]
    if len(selects) != 1 or inputs:
        raise page.changed(f"the filter form has {len(selects)} selects and {len(inputs)} inputs")
    select = selects[0]
    label = page.one(form, "label")
    button = page.one(form, "button")
    options = select.find_all("option")
    first, months = options[0], options[1:]
    lines = [
        f"Filter form: `{form.attrs.get('method', '').upper()} "
        f'{form.attrs.get("action", "")}`, button "{button.text()}"; the select '
        f'`{select.attrs.get("name", "")}`, labelled "{label.text()}", offers '
        f'`{first.attrs.get("value", "")}` ("{first.text()}"'
        + (", selected" if "selected" in first.attrs else "")
        + f") and {len(months)} months, each as `YYYY-MM` labelled with the month's name "
        'and year (`2026-10` is "October 2026"), newest first:',
        "",
        "| Year | Months offered |",
        "| --- | --- |",
    ]
    by_year: dict[str, list[str]] = {}
    previous = "9999-99"
    for option in months:
        value = option.attrs.get("value", "")
        match = _MONTH.fullmatch(value)
        if not match or not 1 <= int(match.group(2)) <= 12:
            raise page.changed(f"the filter offers {value!r}, not a month as YYYY-MM")
        year, month = match.group(1), match.group(2)
        if option.text() != f"{calendar.month_name[int(month)]} {year}":
            raise page.changed(f"the filter labels {value!r} as {option.text()!r}")
        if value >= previous or "selected" in option.attrs:
            raise page.changed(f"the filter's month {value!r} is out of order or selected")
        previous = value
        by_year.setdefault(year, []).append(month)
    lines += [f"| {year} | {', '.join(values)} |" for year, values in by_year.items()]
    return [*lines, ""]


def pager(page: Page, nav: Element) -> list[str]:
    """The paging controls as a table: each item's text, link, label and state."""
    lines = [
        "Paging controls, in page order:",
        "",
        "| Text | Link | aria-label | Current |",
        "| --- | --- | --- | --- |",
    ]
    for item in nav.find_all("li"):
        links = item.find_all("a")
        if len(links) > 1:
            raise page.changed("a paging item with more than one link")
        source = links[0] if links else item
        href = f"`{links[0].attrs.get('href', '')}`" if links else ""
        current = "yes" if links and links[0].has_class("usa-current") else ""
        lines.append(
            f"| {_cell(source.text())} | {href} | {_cell(source.attrs.get('aria-label', ''))} "
            f"| {current} |"
        )
    return [*lines, ""]


def views_block(page: Page, node: Element) -> list[str]:
    """A Drupal views block: its heading, filter form, tables and paging controls."""
    lines: list[str] = []
    for child in node.child_elements():
        if child.tag == "h2":
            lines += [f"## {child.text()}", ""]
        elif child.tag == "form":
            lines += date_filter(page, child)
        elif child.tag == "table":
            lines += table(page, child)
        elif child.tag == "nav" and child.has_class("usa-pagination"):
            lines += pager(page, child)
        elif child.tag == "div":
            lines += views_block(page, child)
        else:
            raise page.changed(f"a views block holds a <{child.tag}> the script does not convert")
    if any(isinstance(child, str) and child.strip() for child in node.children):
        raise page.changed("a views block holds loose text the script does not convert")
    return lines


def _header(url: str, *sentences: str) -> list[str]:
    return _paragraph(
        f"Converted from {url} by `scripts/refresh_upstream.py`; `../FETCHED.md` records",
        "the fetch. Kept: the page's main content; dropped: breadcrumbs, the site's header,",
        "navigation and footer, and screen-reader-only text. Links are absolute URLs; a",
        "date is its text with its `datetime` attribute in parentheses.",
        *sentences,
    )


def publication_markdown(page: Page) -> tuple[str, str]:
    """The publication page as Markdown, and the URL of its newest release's view page."""
    main = page.main()
    article = page.one(main, "article", "node--type-publication")
    lines = [
        f"# {page.title(main)}",
        "",
        *_header(
            page.url,
            "The paging controls' links are kept as given. The release list changes with",
            "every release (monthly for this publication), and so does this file; only the",
            "list's first page is kept.",
        ),
    ]
    regions = [item for item in article.elements() if item.has_class("layout__region")]
    if not regions:
        raise page.changed("no layout regions in the publication article")
    for region in regions:
        for block in region.child_elements():
            if not block.has_class("block"):
                raise page.changed(f"a region holds a <{block.tag}> that is not a block")
            if block.has_class("block-views"):
                lines = _list_end(lines) + views_block(page, block)
            elif block.find_all("div", "field__label"):
                for item in block.find_all("div", "field"):
                    lines += field_lines(page, item)
            elif block.find_all("div", "field__item"):
                lines = _list_end(lines) + blocks(page, block)
            else:
                raise page.changed(f"a block of class {block.attrs.get('class')!r}")
    lines = _list_end(lines)

    path = urlsplit(page.url).path
    views = [
        link
        for link in article.find_all("a")
        if link.text() == "View"
        and link.attrs.get("href", "").startswith(f"{path}/")
        and _RELEASE_PATH.fullmatch(link.attrs["href"][len(path) :])
    ]
    if not views:
        raise page.changed("no release view link in the release list")
    release_url = urljoin(page.url, views[0].attrs["href"])
    return _join(lines), release_url


def release_markdown(page: Page) -> str:
    """A release view page as Markdown: its fields in page order."""
    main = page.main()
    article = page.one(main, "article", "node--type-release")
    lines = [
        f"# {page.title(main)}",
        "",
        *_header(
            page.url,
            "This is the view page of the publication's newest release, the first row of",
            "its release list, so this file changes with every release.",
        ),
    ]
    fields = article.find_all("div", "field")
    if not fields:
        raise page.changed("no fields in the release article")
    for item in fields:
        lines = (_list_end(lines) if item.find_all("div", "nal-file") else lines) + field_lines(
            page, item
        )
    if _collapse(article.text()) != _collapse(" ".join(item.text() for item in fields)):
        raise page.changed("the release article holds text outside its fields")
    return _join(_list_end(lines))


def calendar_markdown(page: Page) -> tuple[str, int]:
    """The calendar excerpt, and the number of events the page holds."""
    main = page.main()
    title = page.title(main)
    if not main.find_all("div", "fullcalendar--wrapper"):
        raise page.changed("no fullcalendar container in the main content")
    if main.text() != title or main.find_all("table"):
        raise page.changed("the main content holds more than the heading and the calendar")
    calendars = page.settings().get("fullcalendar")
    if not isinstance(calendars, dict) or len(calendars) != 1:
        raise page.changed("expected one calendar under fullcalendar in the settings")
    settings = next(iter(calendars.values()))
    options = settings.get("options") if isinstance(settings, dict) else None
    if not isinstance(settings, dict) or not isinstance(options, dict):
        raise page.changed("the calendar's settings have no options object")
    sources = options.get("eventSources")
    if not isinstance(sources, list) or not all(isinstance(s, list) for s in sources):
        raise page.changed("options.eventSources is not a list of event lists")
    events: list[Any] = [event for source in sources for event in source]
    if not events or not all(isinstance(event, dict) for event in events):
        raise page.changed("the calendar holds no events, or events that are not objects")
    shown = {
        **settings,
        "options": {key: value for key, value in options.items() if key != "eventSources"},
    }
    names = list(events[0])
    uniform = all(list(event) == names for event in events)
    ids = {json.dumps(event.get("id")) for event in events}
    starts = []
    for event in events:
        try:
            starts.append(datetime.fromisoformat(str(event.get("start"))))
        except ValueError:
            raise page.changed(f"an event's start {event.get('start')!r} is not ISO 8601") from None
    first, last = min(starts), max(starts)
    kept = events[:CALENDAR_EVENTS]
    lines = [
        f"# {title}",
        "",
        *_paragraph(
            f"An excerpt of {page.url}, written by `scripts/refresh_upstream.py`;",
            "`../FETCHED.md` records the fetch, with the full page's size and sha256. The",
            "page changes daily, so this file keeps its structure only. Its main content is",
            "the heading above and an empty calendar container, which the browser fills",
            "from the events in the page's `drupal-settings-json`; the page has no HTML",
            "table. Breadcrumbs, the site's header, navigation and footer are dropped.",
        ),
        "## Calendar settings",
        "",
        *_paragraph(
            "The page's `drupal-settings-json` holds one calendar under `fullcalendar`, keyed",
            "by a view DOM id (`js-view-dom-id-…`, left out here). Its settings as fetched,",
            "`options.eventSources` left out:",
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
            "from",
            f"`{first.isoformat()}` to `{last.isoformat()}`.",
            (
                "Every event has the same fields, in this order:"
                if uniform
                else "Not every event has the same fields; the first event's, in order:"
            ),
            ", ".join(f"`{name}`" for name in names) + ".",
            f"The first {len(kept)} events as fetched, one JSON object per line:",
        ),
        "```json",
        *(json.dumps(event, ensure_ascii=False) for event in kept),
        "```",
        "",
        f"\N{HORIZONTAL ELLIPSIS} {len(events) - len(kept)} more rows not kept "
        "(the page changes daily)",
    ]
    return _join(lines), len(events)


def _join(lines: list[str]) -> str:
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


# --- the pages ------------------------------------------------------------------------


def documentation_page() -> tuple[Row, str]:
    """Record the API documentation page and read the OpenAPI document's URL from it."""
    response = fetch(DOCS_URL)
    page = html_page(response)
    main = page.main()
    article = page.one(main, "article", "node--type-api-documentation")
    if article.text() or not any(
        item.attrs.get("id", "").startswith("swagger-ui-") for item in article.elements()
    ):
        raise page.changed("the article is no longer an empty Swagger UI container")
    value: Any = page.settings()
    for key in SWAGGER_KEY:
        if not isinstance(value, dict) or key not in value:
            raise page.changed(f"{_SETTINGS} has no {'.'.join(SWAGGER_KEY)}")
        value = value[key]
    formatters = page.settings().get(SWAGGER_KEY[0])
    if not isinstance(value, str) or not isinstance(formatters, dict) or len(formatters) != 1:
        raise page.changed(f"expected one Swagger UI file under {SWAGGER_KEY[0]}")
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.netloc != HOST:
        raise page.changed(f"the OpenAPI document's URL {value!r} left https://{HOST}")
    note = (
        f"{_redirect_note(response)}Drupal page whose main content is an empty Swagger UI "
        f"container, no documentation text; its `drupal-settings-json` names the OpenAPI "
        f"document at `{'.'.join(SWAGGER_KEY)}`: `{value}`"
    )
    return Row(response, note), value


def _top_level(lines: list[str]) -> dict[str, list[str]]:
    """The document's top-level keys, each with the indented lines below it."""
    blocks: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        if line and not line[0].isspace() and not line.startswith("#"):
            key, _, rest = line.partition(":")
            current = blocks.setdefault(key, [rest.strip()] if rest.strip() else [])
        elif current is not None:
            current.append(line)
    return blocks


def _scalar(block: list[str], key: str, indent: int, url: str) -> str:
    prefix = f"{' ' * indent}{key}:"
    for line in block:
        if line.startswith(prefix) and not line[len(prefix) :].startswith(" |"):
            return line[len(prefix) :].strip().strip("'\"")
    raise SystemExit(f"GET {url}: no {key} where the script reads it")


def openapi_row(url: str) -> Row:
    """Fetch the OpenAPI document; it is kept byte for byte, so only read, never parsed."""
    response = fetch(url)
    text = _text(response)
    _no_statement(response, text)
    top = _top_level(text.splitlines())
    if not top.get("openapi", [""])[0].startswith("3."):
        raise SystemExit(f"GET {url}: not an OpenAPI 3 document")
    for name in ("info", "servers", "paths"):
        if name not in top:
            raise SystemExit(f"GET {url}: no top-level {name}")
    version = top["openapi"][0]
    title = _scalar(top["info"], "title", 2, url)
    api = _scalar(top["info"], "version", 2, url)
    server = _scalar([line.replace("- ", "  ", 1) for line in top["servers"]], "url", 4, url)
    stated = [
        name
        for name in ("license", "termsOfService", "contact")
        if any(line.startswith(f"  {name}:") for line in top["info"])
    ]
    if stated:
        raise SystemExit(
            f"GET {url}: info now names {stated}, which FETCHED.md's Attribution says it "
            "does not.\nLook at the document by hand and update scripts/refresh_upstream.py. "
            "Nothing was written."
        )
    methods: dict[str, int] = {}
    groups: list[str] = []
    path = ""
    for line in top["paths"]:
        if line.startswith("  /") and line.rstrip().endswith(":"):
            path = line.strip().removesuffix(":")
            group = "/".join(path.split("/")[:4]) + "/"
            if group not in groups:
                groups.append(group)
        elif re.fullmatch(r"    (get|put|post|delete|patch|head|options|trace):\s*", line):
            if not path:
                raise SystemExit(f"GET {url}: an operation outside a path")
            method = line.strip().removesuffix(":").upper()
            methods[method] = methods.get(method, 0) + 1
    count = sum(methods.values())
    if not count or count != len(re.findall(r"^\s+operationId:", text, re.MULTILINE)):
        raise SystemExit(f"GET {url}: operations and operationIds do not match in number")
    secured = "security" in top or re.search(r"^\s+securitySchemes:", text, re.MULTILINE)
    crlf, lf = response.body.count(b"\r\n"), response.body.count(b"\n")
    endings = "CRLF" if crlf == lf else "LF" if not crlf else "mixed"
    by_method = ", ".join(f"{n} {m}" for m, n in methods.items())
    note = (
        f"{_redirect_note(response)}verbatim, byte for byte ({endings} line endings, as "
        f"served); OpenAPI {version}, `{title}` {api}, server `{server}`; {count} operations "
        f"({by_method}) under {', '.join(f'`{group}`' for group in groups)}; "
        + ("declares security; " if secured else "no `securitySchemes` or `security`; ")
        + "`info` names no licence, terms of service or contact"
    )
    return Row(response, note, YAML_FILE, response.body)


def publication_row() -> tuple[Row, str]:
    """Fetch and convert the publication page; return its newest release's URL too."""
    response = fetch(PUBLICATION_URL)
    content, release_url = publication_markdown(html_page(response))
    last = re.findall(r"\| Last \| `\?page=(\d+)`", content)
    pages = f"{int(last[0]) + 1} pages (`?page=0` to `?page={last[0]}`)" if last else ""
    note = (
        f"{_redirect_note(response)}converted to Markdown; Bytes and sha256 are the HTML "
        f"page's; the first of the release list's {pages or 'one page'}, which changes "
        "with every release"
    )
    return Row(response, note, PUBLICATION_FILE, content.encode("utf-8")), release_url


def release_row(url: str) -> Row:
    """Fetch and convert the newest release's view page."""
    if not url.startswith(PUBLICATION_URL + "/"):
        raise _page_changed(PUBLICATION_URL, f"the newest release's link {url!r} left the page")
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
        "`drupal-settings-json`; Bytes and sha256 are the full page's; changes daily"
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
    text = _text(response)
    _no_statement(response, text)
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


def render_fetched(rows: list[Row], yaml_url: str, fetched: str) -> str:
    """The whole of ``FETCHED.md``."""
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
            "None stated. The ESMIS pages this script fetches (the API documentation page, a",
            "publication page, a release page and the release calendar) carry no copyright",
            "line, licence or terms of use, and the OpenAPI document's `info` names no",
            "licence, terms of service or contact. The site's footer links to two policy",
            f'pages: "Policies and Links", {POLICIES_URL}, which the CDN edge answers with',
            "403 Access Denied to this script, so what it states is not read here; and",
            f'"Information Quality", {QUALITY_URL}, which states no copyright, licence or',
            "terms of use. The script stops if any page it reads starts to state one. The",
            "documentation's text is reproduced here as this package's reference (ADR-0003);",
            "an objection from the publisher is met by replacing it with a summary that keeps",
            "the names and semantics the wrappers rely on.",
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
            "library's `html.parser`: the page's main content is kept, its breadcrumbs, the",
            "site's header, navigation and footer and the screen-reader-only text inside",
            "links are dropped; links become absolute URLs and a date its text with its",
            "`datetime` attribute in parentheses; the release list's date filter is kept as",
            "its parameter and the months it offers, the paging controls as a table. No table",
            "on these pages has merged cells or a nested table, so none is kept as HTML. A",
            "page structure the converter does not know stops the run. Both files change with",
            "every release; their rows' Bytes and sha256 are those of the HTML pages.",
        ),
        *_paragraph(
            "The release calendar has no HTML table: the browser draws it from the events in",
            f"the page's `drupal-settings-json`. `{CALENDAR_FILE}` is an excerpt: the page's",
            "heading, the calendar's settings without the events, the events' count and field",
            f"names, and the first {CALENDAR_EVENTS} events as fetched, one JSON object per",
            "line, then a line counting the events not kept. Its row's Bytes and sha256 are",
            "those of the full page.",
        ),
        *_paragraph(
            "Pages without documentation text get no file, only a row: the API documentation",
            "page, with its HTTP status and the size and sha256 of its body; ESMIS's former",
            f"API address at Cornell's Mann Library, {CORNELL_URL}, which redirects to",
            f"{CORNELL_TARGET}, which answers 404, recorded by status only; and the two",
            "policy pages under Attribution, USDA's by status only, since its 403 body",
            "carries a per-request reference.",
        ),
        *_paragraph(
            "Against the same upstream, two runs write byte-identical files, but for the",
            "calendar excerpt, a page that changes daily, and this file differs in its",
            "Fetched column and in the ETag and Last-Modified of any ESMIS page that Drupal",
            "rendered anew in between. Drupal renders these pages into a cache, and their",
            "ETag and Last-Modified are the time of that rendering, so a new rendering changes",
            "them even when the page is the same byte for byte. Ids that Drupal may generate",
            "per rendering (`js-view-dom-id-…`, form ids) are left out of the Markdown files;",
            "where a new rendering changes them, the page's Bytes and sha256 change here too.",
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
    docs_page, yaml_url = documentation_page()
    yaml_row = openapi_row(yaml_url)
    _log("Pages converted to Markdown")
    publication, release_url = publication_row()
    release = release_row(release_url)
    excerpt = calendar_row()
    _log("Pages recorded without a file")
    shells = [docs_page, cornell_row(), policies_row(), quality_row()]

    rows = [yaml_row, publication, release, excerpt, *shells]
    write_snapshot(out, rows, render_fetched(rows, yaml_url, fetched))
    written = sum(1 for row in rows if row.path)
    _log(
        f"Wrote {written} files and FETCHED.md under {out} (Fetched {fetched}); "
        f"{_TALLY.requests} HTTP requests, redirects and retries included"
    )


if __name__ == "__main__":
    main()
