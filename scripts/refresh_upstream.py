"""Refresh the upstream documentation snapshot in ``docs/upstream/`` (``/refresh-upstream``).

ESMIS, the Economics, Statistics, and Market Information System of USDA's National
Agricultural Library (https://esmis.nal.usda.gov), documents its API in an OpenAPI
document that its ``/api-documentation`` page names. The script declares its snapshot,
``SNAPSHOT``, to core's frame, ``xippios.core.refresh``, which fetches every page, checks
the attribution, writes the files and ``FETCHED.md`` and compares with ``--check``
(sdk-core ADR-0062; conventions §3). The snapshot keeps:

- ``openapi/esmis_public_api.yaml``: the OpenAPI document, byte for byte;
- ``pages/publication-wasde.md`` and ``pages/release-wasde.md``: the WASDE publication
  page and its newest release's view page, converted to Markdown;
- ``pages/release-calendar.md``: an excerpt of the release calendar;

and records the documentation page and the footer's Information Quality page as rows
without a file, and under ``Not fetched`` ESMIS's former API address at Cornell, which
redirects to another host, and USDA's policy page, which the CDN refuses to a script.

The frame builds its client from the slug, named ``xippios-usda-esmis/<version>`` as the
package's client is: the snapshot sends no credential, so the script needs nothing of the
package. The script's own code is its hooks. ``reduce`` converts the three HTML pages
with the standard library's ``html.parser``, ``linked`` reads the OpenAPI document's URL
from the documentation page and the newest release's from the publication page, ``note``
checks every page it recognises, the OpenAPI document's YAML ``info`` among them, which
the frame does not read, and writes each row's note, and ``sections`` writes the section
on the documentation's public domain from the footer the documentation page links. A page
that changed in a way the script does not know stops the run before anything is written.
No key is needed or read. Run from the repository root::

    uv run scripts/refresh_upstream.py              # fetch, then write the snapshot
    uv run scripts/refresh_upstream.py --check      # fetch and compare; write nothing

Eight requests, one a page, each retried once at most by the frame.
"""

import json
import re
import textwrap
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from xippios.core.refresh import Page, Response, Row, Section, Snapshot, changed, decode, run

ROOT = Path(__file__).resolve().parents[1]

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
CALENDAR_EVENTS = 10
"""How many of the calendar's events the excerpt keeps, in upstream order."""
INFO_TERMS = ("license", "termsOfService", "contact")
"""The fields of the document's ``info`` that would state a licence, terms or whom to ask."""

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


def _squash(text: str) -> str:
    return " ".join(text.split())


def _paragraph(*sentences: str) -> list[str]:
    text = " ".join(sentences)
    wrapped = textwrap.fill(text, width=88, break_long_words=False, break_on_hyphens=False)
    return [*wrapped.splitlines(), ""]


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
class Html:
    """A fetched HTML page: its URL and its tree."""

    url: str
    root: Element

    def one(self, within: Element, tag: str, cls: str | None = None) -> Element:
        """The one element ``tag`` (with class ``cls``) below ``within``."""
        found = within.find_all(tag, cls)
        if len(found) != 1:
            what = f"<{tag}>" + (f" of class {cls!r}" if cls else "")
            raise changed(self.url, f"expected one {what}, found {len(found)}")
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
            raise changed(self.url, f"expected one {_SETTINGS}, found {len(scripts)}")
        text = "".join(child for child in scripts[0].children if isinstance(child, str))
        try:
            settings = json.loads(text)
        except ValueError as error:
            raise changed(self.url, f"{_SETTINGS} is not JSON ({error})") from None
        if not isinstance(settings, dict):
            raise changed(self.url, f"{_SETTINGS} is not an object")
        return settings


def html_page(response: Response) -> Html:
    """A fetched page's tree; a body that is not UTF-8 stops the run."""
    return Html(response.url, parse_html(decode(response)))


# --- the tree to Markdown -------------------------------------------------------------


def _cell(value: str) -> str:
    return value.replace("|", r"\|")


def inline(page: Html, node: Element) -> str:
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
            raise changed(page.url, f"an inline <{child.tag}> the script does not convert")
        previous_link = child.tag == "a"
    return "".join(parts)


def paragraphs(page: Html, node: Element) -> list[str]:
    """Markdown for a field's text: its ``<p>`` elements, through any ``<div>``."""
    lines: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                raise changed(page.url, "loose text beside a field's paragraphs")
        elif child.tag == "p":
            text = _squash(inline(page, child))
            lines += [text, ""] if text else []
        elif child.tag == "div":
            lines += paragraphs(page, child)
        else:
            raise changed(page.url, f"a <{child.tag}> in a field's text")
    return lines


def table(page: Html, node: Element) -> list[str]:
    """A pipe table for an HTML table without merged cells or nested tables."""
    cells = [*node.find_all("th"), *node.find_all("td")]
    if node.find_all("table") or any("rowspan" in c.attrs or "colspan" in c.attrs for c in cells):
        raise changed(
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
        raise changed(page.url, "a table without a header row")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise changed(page.url, "a table whose rows differ in length")
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return [*lines, ""]


def field_lines(page: Html, node: Element) -> list[str]:
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


def date_filter(page: Html, form: Element) -> str:
    """One line for the release list's filter form: its select and the months offered."""
    selects = form.find_all("select")
    inputs = [item for item in form.find_all("input") if item.attrs.get("type") != "hidden"]
    if len(selects) != 1 or inputs:
        raise changed(page.url, f"the filter has {len(selects)} selects, {len(inputs)} inputs")
    values = [option.attrs.get("value", "") for option in selects[0].find_all("option")]
    months = values[1:]
    if values[:1] != ["All"] or not months or not all(_MONTH.fullmatch(v) for v in months):
        raise changed(page.url, "the filter offers more than All and months as YYYY-MM")
    return (
        f"The list's filter form (`{form.attrs.get('method', '').upper()} "
        f"{form.attrs.get('action', '')}`) offers, in the select "
        f"`{selects[0].attrs.get('name', '')}`, `All` and months as `YYYY-MM`, from "
        f"`{min(months)}` to `{max(months)}`."
    )


def paging(page: Html, nav: Element) -> tuple[int, int]:
    """The ``?page=N`` of the paging links labelled "Page 1" and "Last page"."""
    found: dict[str, int] = {}
    for link in nav.find_all("a"):
        label = link.attrs.get("aria-label", "")
        match = _PAGE.fullmatch(link.attrs.get("href", ""))
        if label in {"Page 1", "Last page"} and match:
            found[label] = int(match.group(1))
    if set(found) != {"Page 1", "Last page"}:
        raise changed(page.url, "no paging links labelled Page 1 and Last page")
    return found["Page 1"], found["Last page"]


def views_block(page: Html, node: Element) -> list[str]:
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
            raise changed(page.url, f"a views block holds a <{child.tag}>")
    if any(isinstance(child, str) and child.strip() for child in node.children):
        raise changed(page.url, "a views block holds loose text")
    return lines


def _converted(url: str) -> list[str]:
    return _paragraph(
        f"Converted from {url} by `scripts/refresh_upstream.py`; see `../FETCHED.md`."
    )


def _first_row(page: Html, block: Element) -> Element:
    rows = page.one(block, "tbody").find_all("tr")
    if not rows:
        raise changed(page.url, "a release table without rows")
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


def _join(lines: list[str]) -> str:
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def publication_markdown(page: Html) -> tuple[str, str, int]:
    """The publication page as Markdown, its newest release's URL and its last page."""
    main = page.main()
    article = page.one(main, "article", "node--type-publication")
    lines = [f"# {page.one(main, 'h1').text()}", "", *_converted(page.url)]
    regions = [item for item in article.elements() if item.has_class("layout__region")]
    if not regions:
        raise changed(page.url, "no layout regions in the publication article")
    for region in regions:
        for block in region.child_elements():
            if not block.has_class("block"):
                raise changed(page.url, f"a region holds a <{block.tag}>, not a block")
            if block.has_class("block-views"):
                lines = _list_end(lines) + views_block(page, block)
            elif block.find_all("div", "field__label"):
                for item in block.find_all("div", "field"):
                    lines += field_lines(page, item)
            elif block.find_all("div", "field__item"):
                lines = _list_end(lines) + paragraphs(page, block)
            else:
                raise changed(page.url, f"a block of class {block.attrs.get('class')!r}")

    releases = page.one(article, "div", _RELEASES_BLOCK)
    first = _first_row(page, releases)
    latest = _release_key(_first_row(page, page.one(article, "div", _LATEST_BLOCK)))
    if _release_key(first) != latest:
        raise changed(
            page.url,
            f"the release list's first row {_release_key(first)} is not the Latest Release "
            f"{latest}, so the newest release is unclear",
        )
    path = urlsplit(page.url).path
    views = [link for link in first.find_all("a") if link.text() == "View"]
    href = views[0].attrs.get("href", "") if len(views) == 1 else ""
    if not href.startswith(f"{path}/") or not _RELEASE_PATH.fullmatch(href[len(path) :]):
        raise changed(page.url, f"the first release's View link is {href!r}")
    _, last = paging(page, page.one(releases, "nav", "usa-pagination"))
    return _join(_list_end(lines)), urljoin(page.url, href), last


def release_markdown(page: Html) -> str:
    """A release view page as Markdown: its fields in page order."""
    main = page.main()
    article = page.one(main, "article", "node--type-release")
    lines = [f"# {page.one(main, 'h1').text()}", "", *_converted(page.url)]
    fields = article.find_all("div", "field")
    if not fields:
        raise changed(page.url, "no fields in the release article")
    for item in fields:
        if item.find_all("div", "nal-file"):
            lines = _list_end(lines)
        lines += field_lines(page, item)
    if article.text() != _squash(" ".join(item.text() for item in fields)):
        raise changed(page.url, "the release article holds text outside its fields")
    return _join(_list_end(lines))


def calendar_markdown(page: Html) -> tuple[str, int]:
    """The calendar excerpt, and the number of events the page holds."""
    main = page.main()
    title = page.one(main, "h1").text()
    if not main.find_all("div", "fullcalendar--wrapper"):
        raise changed(page.url, "no fullcalendar container in the main content")
    if main.text() != title or main.find_all("table"):
        raise changed(page.url, "the main content holds more than a heading and a calendar")
    calendars = page.settings().get("fullcalendar")
    if not isinstance(calendars, dict) or len(calendars) != 1:
        raise changed(page.url, "expected one calendar under fullcalendar")
    settings = next(iter(calendars.values()))
    options = settings.get("options") if isinstance(settings, dict) else None
    if not isinstance(settings, dict) or not isinstance(options, dict):
        raise changed(page.url, "the calendar's settings have no options object")
    sources = options.get("eventSources")
    if not isinstance(sources, list) or not all(isinstance(s, list) for s in sources):
        raise changed(page.url, "options.eventSources is not a list of event lists")
    events: list[Any] = [event for source in sources for event in source]
    if not events or not all(isinstance(event, dict) for event in events):
        raise changed(page.url, "no events, or events that are not objects")
    names = list(events[0])
    if any(list(event) != names for event in events):
        raise changed(page.url, "the events no longer all have the same fields")
    starts = []
    for event in events:
        try:
            starts.append(datetime.fromisoformat(str(event["start"])))
        except (KeyError, ValueError):
            raise changed(page.url, f"an event's start is not ISO 8601: {event}") from None
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


# --- what the pages say ---------------------------------------------------------------


def documentation(response: Response) -> tuple[str, int]:
    """The OpenAPI document's URL that the documentation page names, and its footer's links.

    The page's main content is an empty Swagger UI container, its ``drupal-settings-json``
    names the document at ``SWAGGER_KEY`` on ESMIS's host, and its footer's list
    ``FOOTER_LABEL`` links the two pages that could carry terms of use; anything else stops
    the run.
    """
    page = html_page(response)
    article = page.one(page.main(), "article", "node--type-api-documentation")
    if article.text() or not any(
        item.attrs.get("id", "").startswith("swagger-ui-") for item in article.elements()
    ):
        raise changed(page.url, "the article is no longer an empty Swagger UI container")
    value: Any = page.settings()
    for key in SWAGGER_KEY:
        if not isinstance(value, dict) or key not in value:
            raise changed(page.url, f"{_SETTINGS} has no {'.'.join(SWAGGER_KEY)}")
        value = value[key]
    formatters = page.settings().get(SWAGGER_KEY[0])
    if not isinstance(value, str) or not isinstance(formatters, dict) or len(formatters) != 1:
        raise changed(page.url, f"expected one Swagger UI file under {SWAGGER_KEY[0]}")
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.netloc != HOST:
        raise changed(page.url, f"the OpenAPI document's URL {value!r} left https://{HOST}")
    footer = [
        nav for nav in page.root.find_all("nav") if nav.attrs.get("aria-label") == FOOTER_LABEL
    ]
    links = [link.attrs.get("href", "") for nav in footer for link in nav.find_all("a")]
    missing = [url for url in (POLICIES_URL, QUALITY_URL) if url not in links]
    if len(footer) != 1 or missing:
        raise changed(page.url, f"the footer's {FOOTER_LABEL!r} no longer links {missing}")
    return value, len(links)


def document_note(response: Response) -> str:
    """Check the OpenAPI document, which is kept byte for byte, and write its row's note.

    The document is YAML, so its ``info`` is read here: the frame reads an API document's
    ``info`` in JSON alone. A field of ``INFO_TERMS`` in it stops the run, since the
    attribution records none.
    """
    text = decode(response)
    version = re.match(r"openapi:\s*(3\.\S*)", text)
    info = re.search(r"^info:[^\n]*\n((?:[ \t][^\n]*\n|\r?\n)*)", text, re.MULTILINE)
    if not version or not info:
        raise changed(response.url, "it is not an OpenAPI 3 document with an info object")
    terms = "|".join(INFO_TERMS)
    stated = re.findall(rf"^  ({terms}):", info.group(1), re.MULTILINE)
    if stated:
        raise SystemExit(
            f"GET {response.url}: info now names {stated}, which the attribution does not "
            "record.\nRead it by hand, record it in the snapshot's attribution and update "
            "scripts/refresh_upstream.py. Nothing was written."
        )
    count = len(re.findall(r"^[ \t]+operationId:", text, re.MULTILINE))
    if not count:
        raise changed(response.url, "it holds no operationId")
    secured = re.search(r"^(?:security:|[ \t]+securitySchemes:)", text, re.MULTILINE)
    crlf, lf = response.body.count(b"\r\n"), response.body.count(b"\n")
    endings = "CRLF" if crlf == lf else "LF" if not crlf else "mixed"
    return (
        f"verbatim, byte for byte ({endings} line endings, as served); OpenAPI "
        f"{version.group(1)}, {count} operations by `operationId`; "
        + ("declares security; " if secured else "no `securitySchemes` or `security`; ")
        + "`info` names no licence, terms of service or contact"
    )


# --- the hooks -------------------------------------------------------------------------


def reduce(page: Page, response: Response) -> bytes:
    """The content of a page's file: the three HTML pages as Markdown, the document as fetched."""
    if page.file == PUBLICATION_FILE:
        return publication_markdown(html_page(response))[0].encode("utf-8")
    if page.file == RELEASE_FILE:
        return release_markdown(html_page(response)).encode("utf-8")
    if page.file == CALENDAR_FILE:
        return calendar_markdown(html_page(response))[0].encode("utf-8")
    return response.body


def linked(row: Row) -> Sequence[Page]:
    """The pages a row's page names, each captured right after it.

    The documentation page names the OpenAPI document, and the publication page's release
    list its newest release, whose URL changes with every release.
    """
    if row.page.url == DOCS_URL:
        url, _ = documentation(row.response)
        return (Page(url, YAML_FILE),)
    if row.page.url == PUBLICATION_URL:
        _, release, _ = publication_markdown(html_page(row.response))
        return (Page(release, RELEASE_FILE),)
    return ()


def note(row: Row) -> str:
    """Check the page a row was read from and write the row's note.

    A page that changed in a way the script does not know stops the run with ``changed``,
    before anything is written.
    """
    url, response, file = row.page.url, row.response, row.page.file
    if url == DOCS_URL:
        document, _ = documentation(response)
        return (
            "Drupal page whose main content is an empty Swagger UI container, no documentation "
            f"text; its `{_SETTINGS}` names the OpenAPI document at "
            f"`{'.'.join(SWAGGER_KEY)}`: `{document}`"
        )
    if file == YAML_FILE:
        return document_note(response)
    if file == PUBLICATION_FILE:
        _, _, last = publication_markdown(html_page(response))
        return (
            "converted to Markdown; the first of the release list's "
            f"{last + 1} pages (`?page=0` to `?page={last}`), which changes with every release"
        )
    if file == RELEASE_FILE:
        return (
            "converted to Markdown; the view page of the newest release in the publication "
            "page's list, so the URL changes with every release"
        )
    if file == CALENDAR_FILE:
        _, events = calendar_markdown(html_page(response))
        return (
            "excerpt, not the page: the heading, the calendar's settings and the first "
            f"{CALENDAR_EVENTS} of its {events} events from the page's `{_SETTINGS}`"
        )
    if url == CORNELL_URL:
        if response.redirects != ((301, CORNELL_TARGET),):
            raise changed(url, f"it redirects {response.redirects}, not 301 to {CORNELL_TARGET}")
        return row.note
    if url == POLICIES_URL:
        if b"Access Denied" not in response.body:
            raise changed(url, "it answers HTTP 403 without 'Access Denied' in the body")
        return row.note
    return row.note


def sections(rows: Sequence[Row]) -> Sequence[Section]:
    """The section on the documentation's public domain, from the documentation page's footer.

    A run without the documentation page's row stops, since the section counts its footer's
    links.
    """
    pages = [row for row in rows if row.page.url == DOCS_URL]
    if not pages:
        raise SystemExit(
            f"The section on the public domain counts the footer of {DOCS_URL}, and this run "
            "read no row of it: declare it. Nothing was written."
        )
    _, links = documentation(pages[0].response)
    text = "\n".join(
        _paragraph(
            "The documentation and the release files are works of the United States",
            f"Government (USDA, National Agricultural Library, ESMIS, {SITE}), in the public",
            "domain in the United States under 17 U.S.C. \N{SECTION SIGN} 105. The site's",
            f'footer lists {links} links under "{FOOTER_LABEL}"; two of them could carry',
            f"terms of use and are the ones read. USDA states its policy at {POLICIES_URL},",
            "which the CDN edge answers with 403 Access Denied to this script, so what it",
            "states is not read here (Not fetched); the Information Quality page,",
            f"{QUALITY_URL}, states no copyright, licence or terms of use.",
        )
    )
    return (Section("Public domain", text),)


# --- the declaration -------------------------------------------------------------------

CAPTURE = "\n\n".join(
    (
        f"ESMIS documents its API on {DOCS_URL}, a Drupal page whose main content is an empty "
        "Swagger UI container. The Swagger UI renders the OpenAPI document that the page's "
        f"`{_SETTINGS}` names at `{'.'.join(SWAGGER_KEY)}`. The script reads the URL from "
        f"there, stops if the key is gone or the URL leaves https://{HOST}, and saves the "
        f"document verbatim, byte for byte, as `{YAML_FILE}`, with the line endings it is "
        "served with; `.gitattributes` keeps `docs/upstream/**` as `-text`, so git does not "
        "convert them. The document is YAML, so the script reads its `info` itself: it names "
        "no licence, terms of service or contact. The documentation page itself gets a row "
        "without a file.",
        "The publication page of the World Agricultural Supply and Demand Estimates (WASDE) "
        "and the view page of its newest release, the first row of the publication's release "
        "list, are converted to Markdown with the standard library's `html.parser`. The "
        "page's main content is kept; its breadcrumbs, the site's header, navigation and "
        "footer and the screen-reader-only text inside links are dropped. Links become "
        "absolute URLs and a date its text with its `datetime` attribute in parentheses; the "
        "release list's date filter and its paging controls become one line each, the months "
        "offered and the last page. No table on these pages has merged cells or a nested "
        "table, so none is kept as HTML. The run stops on a page structure the converter does "
        "not know, and when the release list's first row is not the page's Latest Release. "
        "Both files change with every release.",
        "The release calendar has no HTML table: the browser draws it from the events in the "
        f"page's `{_SETTINGS}`. `{CALENDAR_FILE}` is an excerpt: the page's heading, the "
        "calendar's settings without the events, the events' count and field names, and the "
        f"first {CALENDAR_EVENTS} events, one JSON object per line, all re-serialised with "
        "`json.dumps`, values as fetched (upstream writes `/` as `\\/`); then a line counting "
        "the events not kept. Its row's Last-Modified is the time Drupal last rendered it.",
        "Pages without documentation text get no file, only a row: the API documentation page "
        "and the footer's Information Quality page. ESMIS's former API address at Cornell's "
        f"Mann Library, {CORNELL_URL}, redirects to {CORNELL_TARGET} on another host, which "
        "is not followed, and USDA's policy page answers 403 at the CDN edge: both stand "
        "under Not fetched.",
        "Against the same upstream, two runs write byte-identical files under `openapi/` and "
        "`pages/`, and this file differs in its Fetched column and in the ETag and "
        "Last-Modified of any ESMIS page that Drupal rendered anew in between. Drupal renders "
        "these pages into a cache, and their ETag and Last-Modified are the time of that "
        "rendering, so a new rendering changes them even when the page is the same byte for "
        "byte. Ids that Drupal may generate per rendering "
        "(`js-view-dom-id-\N{HORIZONTAL ELLIPSIS}`, form ids) are left out of the Markdown "
        "files; where a new rendering "
        "changes them, the page's Bytes and sha256 change here too.",
    )
)
"""``FETCHED.md``'s "How this is captured": what is converted, cut or left out, and why."""

SNAPSHOT = Snapshot(
    name="USDA ESMIS",
    slug="usda-esmis",
    pages=(
        Page(DOCS_URL),
        Page(PUBLICATION_URL, PUBLICATION_FILE),
        Page(CALENDAR_URL, CALENDAR_FILE),
        Page(
            CORNELL_URL,
            status=301,
            note="ESMIS's API address at Cornell's Mann Library before the move to the "
            "National Agricultural Library: a redirect to another host, not followed",
        ),
        Page(
            POLICIES_URL,
            status=403,
            note='the footer\'s "Policies and Links", which the CDN edge answers with 403 '
            "Access Denied to a script, so what it states is not read",
        ),
        Page(
            QUALITY_URL,
            note='the footer\'s "Information Quality" (ARS); states no copyright, licence or '
            "terms of use",
        ),
    ),
    capture=CAPTURE,
    out=ROOT / "docs" / "upstream",
    reduce=reduce,
    linked=linked,
    note=note,
    sections=sections,
)
"""The snapshot: the documentation page first, the OpenAPI document it names right after
it, then the WASDE pages, the calendar and the pages without documentation text."""

if __name__ == "__main__":
    raise SystemExit(run(SNAPSHOT))
