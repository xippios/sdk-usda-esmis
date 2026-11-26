"""The capture script's declaration and its hooks on core's frame, offline: nothing is fetched.

``scripts/refresh_upstream.py`` declares its snapshot, ``SNAPSHOT``, to ``xippios.core.refresh``,
whose fetch, attribution check, ``FETCHED.md``, write and ``--check`` core's tests hold
(sdk-core ADR-0062), as core's family check holds the notes of ``OBSERVED.md``. What stays here
is the script's own: its pages, the pages that one of them names, and its hooks, the checks and
the notes of the pages' rows, the check of the OpenAPI document's ``info`` and the section on
the documentation's public domain. A hook is handed an answer built from a file under
``docs/upstream/`` or from a literal of the page's shape, never one fetched.
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
from xippios.core.refresh import Page, Response, Row

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_upstream.py"
UPSTREAM = ROOT / "docs" / "upstream"
YAML_URL = "https://esmis.nal.usda.gov/sites/default/files/swagger/esmis_public_api.yaml"
"""The OpenAPI document's URL, as the documentation page named it on 2026-11-20."""


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_upstream", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def answer(
    url: str, body: bytes, *, status: int = 200, redirects: tuple[tuple[int, str], ...] = ()
) -> Response:
    """The answer at ``url``, as the frame hands it to a hook.

    The body is an input of the test, not an answer from ESMIS: a file under
    ``docs/upstream/`` as the snapshot keeps it, or a literal of the page's shape.
    """
    return Response(
        url=url,
        status=status,
        body=body,
        content_type=None,
        etag=None,
        last_modified=None,
        redirects=redirects,
    )


def documentation_page(document: str = YAML_URL, footer: tuple[str, ...] = ()) -> bytes:
    """The documentation page in the shape it was served on 2026-11-20, cut to what is read.

    An input of the test, not an answer from ESMIS: an empty Swagger UI container, the
    ``drupal-settings-json`` naming ``document`` and a footer that links both pages that
    could carry terms of use, beside ``footer``'s other links.
    """
    links = (script.POLICIES_URL, script.QUALITY_URL, *footer)
    anchors = "".join(f'<li><a href="{link}">{link}</a></li>' for link in links)
    return (
        "<html><body><main><article class='node--type-api-documentation'>"
        "<div id='swagger-ui-0'></div></article></main>"
        f"<nav aria-label='{script.FOOTER_LABEL}'><ul>{anchors}</ul></nav>"
        "<script type='application/json' data-drupal-selector='drupal-settings-json'>"
        '{"swaggerUIFormatter": {"swagger_file-0": {"swaggerFile": "'
        f'{document}"'
        "}}}</script></body></html>"
    ).encode()


def declared(url: str) -> Page:
    """The page that ``SNAPSHOT`` declares at ``url``."""
    (found,) = [page for page in script.SNAPSHOT.pages if page.url == url]
    page: Page = found
    return page


def noted(page: Page, response: Response) -> str:
    """The row's note that the script's ``note`` writes, its checks passed."""
    text: str = script.note(Row(page, response, response.body if page.file else None, page.note))
    return text


def committed_note(url: str) -> str:
    """The note of ``url``'s row in the committed ``FETCHED.md``, its last cell."""
    rows = (UPSTREAM / "FETCHED.md").read_text(encoding="utf-8").splitlines()
    (row,) = [line for line in rows if line.startswith("| ") and f" | {url} | " in line]
    return row.removesuffix(" |").rsplit(" | ", 1)[-1]


# --- the declaration -------------------------------------------------------------------


def test_the_snapshot_declares_its_pages_and_hooks() -> None:
    """The documentation page first, whose OpenAPI document ``linked`` adds, the publication
    page, whose newest release it adds, the calendar, then the pages without a file; the
    frame builds the client from the slug, since the snapshot sends no credential."""
    snapshot = script.SNAPSHOT
    assert [(page.url, page.file, page.status) for page in snapshot.pages] == [
        (script.DOCS_URL, None, 200),
        (script.PUBLICATION_URL, script.PUBLICATION_FILE, 200),
        (script.CALENDAR_URL, script.CALENDAR_FILE, 200),
        (script.CORNELL_URL, None, 301),
        (script.POLICIES_URL, None, 403),
        (script.QUALITY_URL, None, 200),
    ]
    assert (snapshot.name, snapshot.slug, snapshot.out) == ("USDA ESMIS", "usda-esmis", UPSTREAM)
    hooks = (snapshot.reduce, snapshot.linked, snapshot.note, snapshot.sections)
    assert hooks == (script.reduce, script.linked, script.note, script.sections)
    assert snapshot.client is None
    assert (snapshot.attribution, snapshot.variables) == ((), ())


# --- the documentation page and the OpenAPI document ------------------------------------


def test_the_documentation_page_names_the_openapi_document() -> None:
    page = declared(script.DOCS_URL)
    response = answer(page.url, documentation_page())
    linked = script.linked(Row(page, response, None))
    assert linked == (Page(YAML_URL, script.YAML_FILE),)
    assert noted(page, response) == committed_note(page.url)


def test_a_document_on_another_host_stops_the_run() -> None:
    page = declared(script.DOCS_URL)
    elsewhere = documentation_page("https://example.org/esmis_public_api.yaml")
    with pytest.raises(SystemExit, match=re.escape("left https://esmis.nal.usda.gov")):
        script.documentation(answer(page.url, elsewhere))


def test_a_footer_without_the_policies_page_stops_the_run() -> None:
    page = declared(script.DOCS_URL)
    body = documentation_page().replace(script.POLICIES_URL.encode(), b"https://www.usda.gov/")
    with pytest.raises(SystemExit, match="no longer links"):
        script.documentation(answer(page.url, body))


def test_the_document_note_reads_the_kept_yaml() -> None:
    """The note on the document as kept is the one the committed ``FETCHED.md`` holds."""
    page = Page(YAML_URL, script.YAML_FILE)
    response = answer(page.url, (UPSTREAM / script.YAML_FILE).read_bytes())
    assert noted(page, response) == committed_note(YAML_URL)
    assert script.reduce(page, response) == response.body, "kept byte for byte"


def test_an_info_that_names_a_licence_stops_the_run() -> None:
    page = Page(YAML_URL, script.YAML_FILE)
    licensed = b"openapi: 3.0.0\ninfo:\n  title: ESMIS\n  license:\n    name: x\npaths: {}\n"
    with pytest.raises(SystemExit, match=r"info now names \['license'\]"):
        noted(page, answer(page.url, licensed))


# --- the pages without a file -----------------------------------------------------------


def test_the_former_address_redirects_to_the_api_on_another_host() -> None:
    page = declared(script.CORNELL_URL)
    moved = ((301, script.CORNELL_TARGET),)
    assert noted(page, answer(page.url, b"", status=301, redirects=moved)) == page.note
    with pytest.raises(SystemExit, match="changed: it redirects"):
        noted(page, answer(page.url, b"", status=301, redirects=((301, script.SITE),)))


def test_the_policies_page_answers_access_denied() -> None:
    page = declared(script.POLICIES_URL)
    denied = b"<html><body><h1>Access Denied</h1></body></html>"
    assert noted(page, answer(page.url, denied, status=403)) == page.note
    with pytest.raises(SystemExit, match="without 'Access Denied'"):
        noted(page, answer(page.url, b"<html></html>", status=403))


# --- the section -----------------------------------------------------------------------


def test_the_public_domain_section_counts_the_footers_links() -> None:
    page = declared(script.DOCS_URL)
    response = answer(page.url, documentation_page(footer=("a", "b", "c")))
    (section,) = script.sections([Row(page, response, None)])
    assert section.heading == "Public domain"
    text = " ".join(section.text.split())
    assert '5 links under "Government Links"' in text
    assert "17 U.S.C. § 105" in text
    with pytest.raises(SystemExit, match="read no row of it"):
        script.sections([])
