"""Per-task tests with recorded fixtures: at least one replay test for every task.

What every task shares (a sync function returning ``Result[T]`` with an agent docstring,
registered by the adapters and listed in the README status table) is core's family check,
which ``tests/test_family.py`` collects. A replay test that checks what was sent compares
``xippios.core.testing.sent_query(route)``, the scrubbed query of the last request, or
``sent_urls(route)``, the URLs the route received with credentials redacted, rather than
keep a request from ``route.calls`` in its frame, where a failure or ``pytest -l`` would
print it.

Every task is replayed against the answers recorded for the wrappers on 2026-10-27, and
every tool but the bulk task is called end to end through the MCP server. Two answers
were recorded for the tasks: WASDE's release page 1 (``release_find_by_identifier/
wasde_page1.json``), which the walk of ``list_releases`` crosses into, and the October
2026 WASDE ``.txt`` (``release_files/wasde1026_txt.json``), the exchange the download
replays. The download is checked by path, size and content type, never by what the file
says (ADR-0020).
"""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from pydantic import TypeAdapter
from xippios.core import Downloaded, InvalidRequestError, NotFoundError
from xippios.core.mcp import tool_name
from xippios.core.testing import (
    ReplayFixture,
    assert_time_between,
    load_fixture,
    mcp_call,
    mcp_call_text,
    sent_urls,
)

from xippios.usda.esmis import tasks
from xippios.usda.esmis._client import BASE_URL, SOURCE
from xippios.usda.esmis.http import router
from xippios.usda.esmis.mcp import server
from xippios.usda.esmis.models import (
    Agency,
    Pager,
    PublicationResults,
    Release,
    ReleaseFile,
    ReleaseResults,
)

FIXTURES = Path(__file__).parent / "fixtures"
API = f"{BASE_URL}/api/v1"
WASDE_RELEASES = f"{API}/release/findByIdentifier/wasde"
WASDE_TXT = f"{BASE_URL}/sites/default/release-files/796099/wasde1026.txt"
FORMATS = {"pdf", "txt", "xls", "xml", "zip"}
OCTOBER_PRINTED = datetime(2026, 10, 9, 12, 0)
"""The October 2026 WASDE's ``release_datetime`` as printed, its ``+0000`` dropped."""


def recorded[T](type_: type[T], endpoint: str, case: str) -> T:
    """A recorded answer, parsed as the wrapper parses it."""
    body = json.loads(load_fixture(FIXTURES / endpoint / f"{case}.json").response.content)
    return TypeAdapter(type_).validate_python(body)


def releases_of(case: str) -> list[Release]:
    return recorded(ReleaseResults, "release_find_by_identifier", case).results


def printed_date(release: Release) -> date:
    return release.release_datetime.date()


def test_list_agencies(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("agency_find_all", "all")
    before = datetime.now(UTC)
    result = tasks.list_agencies()
    after = datetime.now(UTC)
    assert result.data == recorded(list[Agency], "agency_find_all", "all")
    assert [agency.acronym for agency in result.data][:4] == ["FAS", "ERS", "WAOB", "NASS"]
    assert result.meta.source == SOURCE
    assert result.meta.endpoint == "esmis_api_agency_findAll"
    assert result.meta.request == {}
    assert (result.meta.total, result.meta.vintage, result.meta.published_at) == (None,) * 3
    assert_time_between(result.meta.retrieved_at, before, after)
    assert sent_urls(route) == [f"{API}/agency/findAll"]


def test_search_publications_collects_every_page(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_search", "wasde_page0", match_params=["query", "page"])
    result = tasks.search_publications("wasde")
    assert result.data == recorded(PublicationResults, "publication_search", "wasde_page0").results
    assert [publication.id for publication in result.data][-1] == "1659"
    assert result.meta.endpoint == "esmis_api_publication_search"
    assert result.meta.request == {"query": "wasde"}, "page left None is omitted"
    assert result.meta.total == 7
    # A short first page is the last: one request, never page 1.
    assert sent_urls(route) == [f"{API}/publication/search?query=wasde&page=0"]


def test_search_publications_one_page(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_search", "wasde_page0", match_params=["query", "page"])
    result = tasks.search_publications("wasde", page=0)
    assert len(result.data) == 7
    assert result.meta.request == {"query": "wasde", "page": 0}
    assert result.meta.total == 7
    assert sent_urls(route) == [f"{API}/publication/search?query=wasde&page=0"]


@pytest.mark.parametrize("query", ["", "   "])
def test_search_publications_refuses_an_empty_query(
    replay_fixture: ReplayFixture, query: str
) -> None:
    route = replay_fixture("publication_search", "empty_query")
    with pytest.raises(InvalidRequestError, match="query must not be empty"):
        tasks.search_publications(query)
    assert sent_urls(route) == [], "refused before anything is sent"


def test_get_publication(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_find_by_identifier", "wasde")
    result = tasks.get_publication("wasde")
    (expected,) = recorded(PublicationResults, "publication_find_by_identifier", "wasde").results
    assert result.data == expected
    assert (result.data.id, result.data.identifier) == ("1659", ["wasde"])
    assert result.meta.endpoint == "esmis_api_publication_findByIdentifier"
    assert result.meta.request == {"publication_identifier": "wasde"}
    assert (result.meta.total, result.meta.vintage, result.meta.published_at) == (None,) * 3
    assert sent_urls(route) == [f"{API}/publication/findByIdentifier/wasde"]


def test_get_publication_unknown_is_not_found(replay_fixture: ReplayFixture) -> None:
    replay_fixture("publication_find_by_identifier", "unknown")
    with pytest.raises(NotFoundError) as caught:
        tasks.get_publication("xippios-no-such-identifier")
    message = str(caught.value)
    assert "'xippios-no-such-identifier'" in message
    assert "GET /api/v1/publication/findByIdentifier/xippios-no-such-identifier" in message
    assert BASE_URL not in message, "a message names the path, never the host"


def test_get_publication_with_a_slash_is_refused(replay_fixture: ReplayFixture) -> None:
    replay_fixture("publication_find_by_identifier", "with_slash")
    with pytest.raises(InvalidRequestError, match="encoded slash"):
        tasks.get_publication("Market and Trade Economics Division/FDS")


def test_list_releases_one_page(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_identifier", "wasde_page0", match_params=["page"])
    result = tasks.list_releases("wasde", page=0)
    assert result.data == releases_of("wasde_page0")
    assert result.meta.endpoint == "esmis_api_release_findByIdentifier"
    assert result.meta.request == {"publication_identifier": "wasde", "page": 0}
    assert result.meta.total == 703, "upstream's count for the whole publication"
    assert (result.meta.vintage, result.meta.published_at) == (None, None)
    assert sent_urls(route) == [f"{WASDE_RELEASES}?page=0"]


def test_list_releases_walks_until_a_page_is_older_than_since(
    replay_fixture: ReplayFixture,
) -> None:
    first = replay_fixture("release_find_by_identifier", "wasde_page0", match_params=["page"])
    second = replay_fixture("release_find_by_identifier", "wasde_page1", match_params=["page"])
    since = date(2024, 1, 1)
    result = tasks.list_releases("wasde", since=since)
    walked = releases_of("wasde_page0") + releases_of("wasde_page1")
    assert result.data == [release for release in walked if printed_date(release) >= since]
    assert len(result.data) == 33
    assert (result.data[0].id, result.data[-1].id) == ("796099", "95494")
    assert printed_date(result.data[-1]) == date(2024, 1, 12)
    assert result.meta.request == {"publication_identifier": "wasde", "since": since}
    assert result.meta.total == 703, "may exceed len(data) after the date filter"
    # Page 1's oldest release (2022-08-12) is before since: the walk ends there.
    assert sent_urls(first) == [f"{WASDE_RELEASES}?page=0"]
    assert sent_urls(second) == [f"{WASDE_RELEASES}?page=1"]


def test_list_releases_keeps_the_printed_dates_between_since_and_until(
    replay_fixture: ReplayFixture,
) -> None:
    route = replay_fixture("release_find_by_identifier", "wasde_page0", match_params=["page"])
    since, until = date(2025, 1, 1), date(2025, 12, 31)
    result = tasks.list_releases("wasde", since=since, until=until)
    assert [release.id for release in result.data] == [
        release.id
        for release in releases_of("wasde_page0")
        if since <= printed_date(release) <= until
    ]
    assert len(result.data) == 11
    assert {printed_date(release).year for release in result.data} == {2025}
    assert result.meta.request == {
        "publication_identifier": "wasde",
        "since": since,
        "until": until,
    }
    # Page 0's oldest release (2024-09-12) is before since: one request.
    assert sent_urls(route) == [f"{WASDE_RELEASES}?page=0"]


def test_list_releases_unknown_identifier_is_empty(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_identifier", "unknown")
    result = tasks.list_releases("nope-nope")
    assert result.data == []
    assert result.meta.total == 0, "as the pager says"
    assert sent_urls(route) == [f"{API}/release/findByIdentifier/nope-nope?page=0"]


def test_list_releases_refuses_since_after_until(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_identifier", "wasde_page0")
    with pytest.raises(InvalidRequestError, match="since"):
        tasks.list_releases("wasde", since=date(2026, 1, 1), until=date(2025, 1, 1))
    assert sent_urls(route) == []


@pytest.mark.anyio
async def test_the_walk_stops_at_total_pages_without_a_request_past_it() -> None:
    """A full last page ends the walk by ``total_pages``: no request for the page after."""
    full = releases_of("wasde_page0")
    pager = Pager(current_page=0, items_per_page=25, total_pages=1, total_results=25)
    asked: list[int] = []

    async def fetch_page(page: int) -> tuple[Pager | tuple[()], list[Release]]:
        asked.append(page)
        return pager, full

    items, total = await tasks._Pages(fetch_page).walk()
    assert (items, total, asked) == (full, 25, [0])


def test_get_release(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_id", "796099")
    result = tasks.get_release(796099)
    (expected,) = recorded(ReleaseResults, "release_find_by_id", "796099").results
    assert result.data == expected
    assert result.data.release_datetime == datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    assert result.meta.endpoint == "esmis_api_release_findById"
    assert result.meta.vintage == "796099"
    assert (result.meta.published_at, result.meta.published_at_naive) == (OCTOBER_PRINTED, True)
    assert result.meta.request == {"release_id": 796099}
    assert result.meta.total is None
    assert sent_urls(route) == [f"{API}/release/findById/796099"]


def test_get_release_unknown_is_not_found(replay_fixture: ReplayFixture) -> None:
    replay_fixture("release_find_by_id", "unknown")
    with pytest.raises(NotFoundError, match="HTTP 404"):
        tasks.get_release(999999999)


def test_get_latest_release(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_identifier", "wasde_page0", match_params=["page"])
    result = tasks.get_latest_release("wasde")
    page = releases_of("wasde_page0")
    assert result.data == max(page, key=lambda release: release.release_datetime)
    assert result.data.id == "796099"
    assert result.meta.endpoint == "esmis_api_release_findByIdentifier"
    assert result.meta.vintage == "796099"
    assert (result.meta.published_at, result.meta.published_at_naive) == (OCTOBER_PRINTED, True)
    assert result.meta.request == {"publication_identifier": "wasde"}
    assert sent_urls(route) == [f"{WASDE_RELEASES}?page=0"]


def test_get_latest_release_unknown_is_not_found(replay_fixture: ReplayFixture) -> None:
    replay_fixture("release_find_by_identifier", "unknown")
    with pytest.raises(NotFoundError, match="'nope-nope'"):
        tasks.get_latest_release("nope-nope")


def test_list_release_files(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_id", "796099")
    result = tasks.list_release_files(796099)
    assert result.data == [
        ReleaseFile(
            url=f"{BASE_URL}/sites/default/release-files/796099/wasde1026.{kind}",
            name=f"wasde1026.{kind}",
            format=kind,
        )
        for kind in ("pdf", "txt", "xls", "xml")
    ]
    assert result.meta.endpoint == "esmis_api_release_findById"
    assert result.meta.vintage == "796099"
    assert (result.meta.published_at, result.meta.published_at_naive) == (OCTOBER_PRINTED, True)
    assert result.meta.request == {"release_id": 796099}
    assert sent_urls(route) == [f"{API}/release/findById/796099"]


@pytest.mark.parametrize(
    ("endpoint", "case"),
    [
        ("release_find_all", "page0"),
        ("release_find_by_identifier", "wasde_page0"),
        ("release_find_by_identifier", "wasde_page1"),
        ("release_find_by_pub_id", "1659_page0"),
    ],
)
def test_every_recorded_file_has_a_name_and_a_known_format(endpoint: str, case: str) -> None:
    for release in recorded(ReleaseResults, endpoint, case).results:
        files = tasks._files(release)
        assert [file.url for file in files] == release.files, "verbatim, in upstream order"
        for file in files:
            assert file.url.endswith(f"/{file.name}")
            assert file.name.endswith(f".{file.format}")
            assert file.format in FORMATS, file.url


def test_download_release_file(replay_fixture: ReplayFixture, tmp_path: Path) -> None:
    release = replay_fixture("release_find_by_id", "796099")
    download = replay_fixture("release_files", "wasde1026_txt")
    recorded_file = load_fixture(FIXTURES / "release_files" / "wasde1026_txt.json").response
    dest = tmp_path / "wasde1026.txt"
    before = datetime.now(UTC)
    result = tasks.download_release_file(796099, "txt", dest)
    after = datetime.now(UTC)
    assert isinstance(result.data, Downloaded)
    assert result.data.path == dest
    assert result.data.bytes == dest.stat().st_size == len(recorded_file.content) == 122378
    assert result.data.content_type == "text/plain"
    assert result.data.last_modified == "Fri, 09 Oct 2026 16:01:00 GMT"
    assert result.meta.endpoint == "wasde1026.txt", "the file's name as upstream prints it"
    assert result.meta.vintage == "796099"
    assert (result.meta.published_at, result.meta.published_at_naive) == (OCTOBER_PRINTED, True)
    assert result.meta.request == {"release_id": 796099, "format": "txt", "url": WASDE_TXT}
    assert result.meta.retrieved_at == result.data.retrieved_at
    assert_time_between(result.meta.retrieved_at, before, after)
    assert sent_urls(release) == [f"{API}/release/findById/796099"]
    assert sent_urls(download) == [WASDE_TXT]
    assert [path.name for path in tmp_path.iterdir()] == ["wasde1026.txt"], "no part file"


def test_download_release_file_refuses_a_format_the_release_lacks(
    replay_fixture: ReplayFixture, tmp_path: Path
) -> None:
    replay_fixture("release_find_by_id", "796099")
    download = replay_fixture("release_files", "wasde1026_txt")
    with pytest.raises(InvalidRequestError) as caught:
        tasks.download_release_file(796099, "zip", tmp_path / "wasde1026.zip")
    assert str(caught.value) == "release 796099 has no 'zip' file; its formats: pdf, txt, xls, xml"
    assert sent_urls(download) == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
async def test_the_bulk_task_is_no_tool_and_no_route() -> None:
    bulk = tasks.BULK_TASKS
    assert bulk == {"download_release_file"}
    assert bulk <= set(tasks.__all__)
    tools = {tool.name for tool in await server.list_tools()}
    routes = {route.path for route in router.routes if isinstance(route, APIRoute)}
    for name in tasks.__all__:
        fn = getattr(tasks, name)
        served = name not in bulk
        assert (tool_name(SOURCE, fn) in tools) is served, name
        assert (f"/{SOURCE}/{name}" in routes) is served, name
    assert len(tools) == len(routes) == 7


type McpCase = tuple[str, dict[str, Any], list[tuple[str, str]], list[str], Callable[..., bool]]
"""A tool's task name, its arguments, the fixtures it needs, the URLs it sends, a check."""

MCP_CASES: list[McpCase] = [
    (
        "list_agencies",
        {},
        [("agency_find_all", "all")],
        [f"{API}/agency/findAll"],
        lambda payload: len(payload["data"]) == 9,
    ),
    (
        "search_publications",
        {"query": "wasde"},
        [("publication_search", "wasde_page0")],
        [f"{API}/publication/search?query=wasde&page=0"],
        lambda payload: payload["meta"]["total"] == 7 and len(payload["data"]) == 7,
    ),
    (
        "get_publication",
        {"publication_identifier": "wasde"},
        [("publication_find_by_identifier", "wasde")],
        [f"{API}/publication/findByIdentifier/wasde"],
        lambda payload: payload["data"]["id"] == "1659",
    ),
    (
        "list_releases",
        {"publication_identifier": "wasde", "since": "2025-01-01"},
        [("release_find_by_identifier", "wasde_page0")],
        [f"{WASDE_RELEASES}?page=0"],
        lambda payload: (
            len(payload["data"]) == 21
            and payload["meta"]["request"]
            == {"publication_identifier": "wasde", "since": "2025-01-01"}
        ),
    ),
    (
        "get_release",
        {"release_id": 796099},
        [("release_find_by_id", "796099")],
        [f"{API}/release/findById/796099"],
        lambda payload: (
            payload["meta"]["vintage"] == "796099"
            and payload["meta"]["published_at"] == "2026-10-09T12:00:00"
            and payload["meta"]["published_at_naive"] is True
        ),
    ),
    (
        "get_latest_release",
        {"publication_identifier": "wasde"},
        [("release_find_by_identifier", "wasde_page0")],
        [f"{WASDE_RELEASES}?page=0"],
        lambda payload: payload["data"]["id"] == payload["meta"]["vintage"] == "796099",
    ),
    (
        "list_release_files",
        {"release_id": 796099},
        [("release_find_by_id", "796099")],
        [f"{API}/release/findById/796099"],
        lambda payload: (
            [file["format"] for file in payload["data"]] == ["pdf", "txt", "xls", "xml"]
        ),
    ),
]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("task", "arguments", "fixtures", "urls", "check"),
    MCP_CASES,
    ids=[case[0] for case in MCP_CASES],
)
async def test_every_tool_end_to_end(
    replay_fixture: ReplayFixture,
    task: str,
    arguments: dict[str, Any],
    fixtures: list[tuple[str, str]],
    urls: list[str],
    check: Callable[[Any], bool],
) -> None:
    routes = [replay_fixture(endpoint, case) for endpoint, case in fixtures]
    payload = await mcp_call(server, f"usda_esmis_{task}", arguments)
    assert payload["meta"]["source"] == SOURCE
    assert check(payload), payload["meta"]
    assert [url for route in routes for url in sent_urls(route)] == urls


@pytest.mark.anyio
async def test_a_tool_reports_not_found_as_text(replay_fixture: ReplayFixture) -> None:
    replay_fixture("publication_find_by_identifier", "unknown")
    text = await mcp_call_text(
        server,
        "usda_esmis_get_publication",
        {"publication_identifier": "xippios-no-such-identifier"},
    )
    assert text.startswith("error: NotFoundError: ESMIS has no publication")


def test_every_task_is_tested_through_the_mcp_server_or_is_bulk() -> None:
    tools = {case[0] for case in MCP_CASES}
    assert tools | tasks.BULK_TASKS == set(tasks.__all__)


def test_the_package_re_exports_the_tasks() -> None:
    import xippios.usda.esmis as package

    for name in tasks.__all__:
        assert getattr(package, name) is getattr(tasks, name)
