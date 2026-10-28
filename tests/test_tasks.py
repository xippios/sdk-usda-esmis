"""Replay tests on recorded fixtures, at least one per task (conventions §10).

``/add-endpoint`` and ``/record-fixture`` add them.

Every task is replayed against the answers recorded for the wrappers on 2026-10-27, and
every tool but the bulk task is called end to end through the MCP server.
``list_publications`` answers from the packaged tables in ``reference/`` and sends
nothing: its tests mount no fixture and check that no request left. Three answers
were recorded for the tasks: WASDE's release page 1 (``release_find_by_identifier/
wasde_page1.json``), which the walk of ``list_releases`` crosses into, the October
2026 WASDE ``.txt`` (``download_release_file/wasde1026_txt.json``), the exchange the
download replays, and, on 2026-10-28, the WASDE of 2013-08-12
(``release_find_by_id/95621.json``), whose original and revised files of one format the
download's choice by ``format`` and ``name`` is tested on, without a download. The
download is checked by path, size and content type, never by what the file says
(ADR-0020).
"""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.routing import APIRoute
from pydantic import TypeAdapter
from xippios.core import (
    Downloaded,
    InvalidRequestError,
    NotFoundError,
    PackagedList,
    Result,
    ResultCap,
    UnknownCode,
    UpstreamModel,
)
from xippios.core.mcp import cap_result, tool_name
from xippios.core.testing import (
    ReplayFixture,
    assert_projection,
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
    PublicationRow,
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
PACKAGE = "xippios.usda.esmis"
PUBLICATIONS = 2522
"""Publications in ``reference/publication.json``, as ``list_publications``'s docstring
counts them; a refresh of the table updates both."""
PACKAGED_FETCHED = "2026-10-27T17:24:48Z"
"""The publication table's ``fetched``, as written."""
FILE_KEYS = {"param", "endpoint", "fetched", "note", "records"}
"""The keys a packaged file may hold (ADR-0022, amendment point 8)."""


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


def packaged_file(name: str) -> dict[str, Any]:
    """``reference/<name>.json`` as written, read as JSON, not through ``PackagedList``."""
    text = resources.files(PACKAGE).joinpath("reference", f"{name}.json").read_text("utf-8")
    payload: dict[str, Any] = json.loads(text)
    return payload


def test_list_publications_answers_the_whole_table_without_a_request(
    respx_mock: respx.MockRouter,
) -> None:
    table = PackagedList.load(PACKAGE, "publication")
    result = tasks.list_publications()
    assert len(result.data) == len(table.records) == PUBLICATIONS
    assert result.data == table.parse(PublicationRow, source=SOURCE), "upstream order"
    assert result.meta.source == SOURCE
    assert result.meta.endpoint == "esmis_api_publication_findAll"
    assert result.meta.retrieved_at == table.fetched, "the table's fetch time (ADR-0022)"
    assert result.meta.retrieved_at == datetime.fromisoformat(PACKAGED_FETCHED)
    assert result.meta.request == {}, "filters left None are omitted"
    assert (result.meta.vintage, result.meta.published_at, result.meta.total) == (None,) * 3
    assert not result.meta.published_at_naive
    assert respx_mock.calls.call_count == 0


@pytest.mark.parametrize(
    ("search", "ids"),
    [
        ("wasde", ["1659"]),
        ("WASDE", ["1659"]),
        ("1659", ["1659"]),
        ("CropProg", ["2179"]),
    ],
)
def test_list_publications_search_matches_id_identifier_and_title(
    search: str, ids: list[str]
) -> None:
    result = tasks.list_publications(search=search)
    assert [row.id for row in result.data] == ids
    assert result.meta.request == {"search": search}


def test_list_publications_search_keeps_every_field_on_its_own() -> None:
    result = tasks.list_publications(search="wheat")
    assert len(result.data) == 30, "the docstring's count"
    for row in result.data:
        fields = [row.id, *row.identifier, row.title]
        assert any("wheat" in field.casefold() for field in fields), row.id
    assert tasks.list_publications(search="xippios-matches-nothing").data == []


@pytest.mark.parametrize(("acronym", "count"), [("ERS", 121), ("WAOB", 2), ("AMS-LPS", 1424)])
def test_list_publications_by_agency_acronym(acronym: str, count: int) -> None:
    result = tasks.list_publications(agency_acronym=acronym)
    assert len(result.data) == count
    assert all(acronym in (row.agency_acronym or []) for row in result.data)
    assert result.meta.request == {"agency_acronym": acronym}


def test_list_publications_with_both_filters() -> None:
    result = tasks.list_publications(search="wheat", agency_acronym="ERS")
    assert len(result.data) == 6
    assert result.meta.request == {"search": "wheat", "agency_acronym": "ERS"}
    by_search = tasks.list_publications(search="wheat").data
    by_agency = tasks.list_publications(agency_acronym="ERS").data
    assert result.data == [row for row in by_agency if row in by_search], "both, upstream order"


@pytest.mark.parametrize(
    ("acronym", "closest"),
    [
        ("ers", [("ERS", "Economic Research Service")]),
        (
            "AMS-LP",
            [
                ("AMS-LPS", "Livestock, Poultry and Seed Program"),
                ("AMS-SC", "Specialty Crops Program"),
                ("AMS-DA", "Dairy Program"),
            ],
        ),
        ("XYZ", []),
    ],
)
def test_list_publications_refuses_an_acronym_the_agency_table_lacks(
    respx_mock: respx.MockRouter, acronym: str, closest: list[tuple[str, str]]
) -> None:
    agencies = PackagedList.load(PACKAGE, "agency")
    with pytest.raises(UnknownCode) as caught:
        tasks.list_publications(search="wheat", agency_acronym=acronym)
    refusal = caught.value
    assert isinstance(refusal, InvalidRequestError)
    assert (refusal.param, refusal.value) == ("agency_acronym", acronym)
    assert refusal.list_name == "agency"
    assert refusal.fetched == agencies.fetched
    assert list(refusal.closest) == closest
    message = str(refusal)
    assert f"{acronym!r} is not an agency_acronym in the packaged agency list" in message
    assert f"(fetched {agencies.fetched:%Y-%m-%d})" in message
    for code, name in closest:
        assert f"{code} ({name})" in message
    assert respx_mock.calls.call_count == 0


def test_the_packaged_files_hold_the_four_keys_and_a_note() -> None:
    files: list[tuple[str, str, type[UpstreamModel]]] = [
        ("publication", "esmis_api_publication_findAll", PublicationRow),
        ("agency", "esmis_api_agency_findAll", Agency),
    ]
    for name, endpoint, model in files:
        raw = packaged_file(name)
        assert set(raw) == FILE_KEYS, name
        table = PackagedList.load(PACKAGE, name)
        assert (table.param, table.endpoint) == (name, endpoint)
        assert table.note
        assert table.fetched.tzinfo is UTC
        rows = table.parse(model, source=SOURCE)
        for row, record in zip(rows, raw["records"], strict=True):
            assert set(record) == set(model.model_fields), "every field, null included"
            assert row.dump_upstream() == record, "records under upstream's names"
    assert packaged_file("publication")["fetched"] == PACKAGED_FETCHED


def test_the_packaged_tables_agree() -> None:
    publications = PackagedList.load(PACKAGE, "publication").parse(PublicationRow, source=SOURCE)
    agencies = PackagedList.load(PACKAGE, "agency").parse(Agency, source=SOURCE)
    ids = [row.id for row in publications]
    assert len(set(ids)) == len(ids) == PUBLICATIONS
    acronyms = {agency.acronym for agency in agencies}
    assert len(agencies) == len(acronyms) == 9
    # Every acronym a publication lists is in the agency table, so the refusal of an
    # acronym the table lacks never hides a publication.
    listed = {acronym for row in publications for acronym in row.agency_acronym or []}
    assert listed == acronyms


def test_publication_row_is_a_projection_of_publication() -> None:
    page = recorded(PublicationResults, "publication_find_all", "page0").results
    for publication in page:
        assert_projection(PublicationRow.project(publication), publication)


CAP_NOTE = (
    "showing 200 of 2522 rows (cap: 200 rows or 65536 bytes); filter with search (text of an "
    "id, an identifier or a title) or agency_acronym (as list_agencies spells it) to see the "
    "rest; Python and HTTP callers get the whole table"
)
"""The note of the MCP tool called without a filter: the default cap, the cap's own note."""


def test_the_python_task_returns_the_whole_table_the_tool_caps() -> None:
    cap = tasks.MCP_CAPS["list_publications"]
    assert (cap.max_rows, cap.max_bytes) == (ResultCap().max_rows, ResultCap().max_bytes)
    result = tasks.list_publications()
    whole = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    assert len(whole.encode()) == 599_402, "the size MCP_CAPS's comment names"
    assert len(result.data) == PUBLICATIONS, "Python callers get the whole table"
    cut = json.loads(cap_result(result, cap))
    assert cut["data"] == json.loads(whole)["data"][:200]
    assert cut["note"] == CAP_NOTE


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


AUGUST_2013 = [
    ("3t945q76s/bk128b299/g732d935k/ORIGwasde-08-12-2013.xls", "xls"),
    ("3t945q76s/bk128b299/rb68xc267/ORIGwasde-08-12-2013.pdf", "pdf"),
    ("3t945q76s/bk128b299/4t64gn45n/wasde-08-12-2013.pdf", "pdf"),
    ("3t945q76s/bk128b299/tx31qj070/ORIGwasde-08-12-2013.xml", "xml"),
    ("3t945q76s/bk128b299/41687h848/wasde-08-12-2013.xls", "xls"),
    ("3t945q76s/bk128b299/wm117p338/wasde-08-12-2013.xml", "xml"),
]
"""The files of release 95621, the WASDE of 2013-08-12, as recorded: paths under
``/sites/default/release-files/`` and formats, in upstream order, an original and a
revised file of each format."""
AUGUST_2013_LISTING = (
    "ORIGwasde-08-12-2013.xls (xls), ORIGwasde-08-12-2013.pdf (pdf), "
    "wasde-08-12-2013.pdf (pdf), ORIGwasde-08-12-2013.xml (xml), "
    "wasde-08-12-2013.xls (xls), wasde-08-12-2013.xml (xml)"
)
"""Release 95621's files as a refusal names them."""


def august_2013() -> Release:
    (release,) = recorded(ReleaseResults, "release_find_by_id", "95621").results
    return release


def august_2013_file(name: str) -> ReleaseFile:
    (path,) = [path for path, _ in AUGUST_2013 if path.endswith(f"/{name}")]
    return ReleaseFile.from_url(f"{BASE_URL}/sites/default/release-files/{path}")


def test_list_release_files_keeps_an_original_and_a_revised_file_in_upstream_order(
    replay_fixture: ReplayFixture,
) -> None:
    route = replay_fixture("release_find_by_id", "95621")
    result = tasks.list_release_files(95621)
    assert result.data == [
        ReleaseFile(
            url=f"{BASE_URL}/sites/default/release-files/{path}",
            name=path.rsplit("/", 1)[-1],
            format=kind,
        )
        for path, kind in AUGUST_2013
    ]
    xml = [file.name for file in result.data if file.format == "xml"]
    assert xml == ["ORIGwasde-08-12-2013.xml", "wasde-08-12-2013.xml"]
    assert result.meta.vintage == "95621"
    assert result.meta.published_at == datetime(2013, 8, 12, 12, 0)
    assert result.meta.published_at_naive
    assert result.meta.request == {"release_id": 95621}
    assert sent_urls(route) == [f"{API}/release/findById/95621"]


@pytest.mark.parametrize(
    ("format", "name", "chosen"),
    [
        ("xml", None, "ORIGwasde-08-12-2013.xml"),
        ("pdf", None, "ORIGwasde-08-12-2013.pdf"),
        (None, "wasde-08-12-2013.xml", "wasde-08-12-2013.xml"),
        (None, "ORIGwasde-08-12-2013.xls", "ORIGwasde-08-12-2013.xls"),
        ("xml", "wasde-08-12-2013.xml", "wasde-08-12-2013.xml"),
        ("xml", "ORIGwasde-08-12-2013.xml", "ORIGwasde-08-12-2013.xml"),
    ],
    ids=["format-first-xml", "format-first-pdf", "name", "name-orig", "both", "both-orig"],
)
def test_the_file_is_chosen_by_format_name_or_both(
    format: str | None, name: str | None, chosen: str
) -> None:
    assert tasks._select(august_2013(), format, name) == august_2013_file(chosen)


@pytest.mark.parametrize(
    ("format", "name", "message"),
    [
        (
            "pdf",
            "wasde-08-12-2013.xml",
            "release 95621's file 'wasde-08-12-2013.xml' has the format 'xml', not 'pdf'; "
            "pass format='xml' or leave format out",
        ),
        (
            None,
            "wasde-08-12-2013.txt",
            f"release 95621 has no file named 'wasde-08-12-2013.txt'; its files: "
            f"{AUGUST_2013_LISTING}",
        ),
        (
            "xml",
            "WASDE-08-12-2013.xml",
            f"release 95621 has no file named 'WASDE-08-12-2013.xml'; its files: "
            f"{AUGUST_2013_LISTING}",
        ),
        (
            None,
            None,
            "name the file of release 95621 to download: pass format, name or both; its "
            f"files: {AUGUST_2013_LISTING}",
        ),
        ("txt", None, "release 95621 has no 'txt' file; its formats: xls, pdf, xml"),
    ],
    ids=["name-of-another-format", "unknown-name", "name-as-spelt", "neither", "no-such-format"],
)
def test_a_choice_the_release_cannot_serve_is_refused(
    format: str | None, name: str | None, message: str
) -> None:
    with pytest.raises(InvalidRequestError) as caught:
        tasks._select(august_2013(), format, name)
    assert str(caught.value) == message
    assert caught.value.source == SOURCE


@pytest.mark.parametrize(
    ("endpoint", "case"),
    [
        ("release_find_all", "page0"),
        ("release_find_by_id", "796099"),
        ("release_find_by_id", "95621"),
        ("release_find_by_identifier", "wasde_page0"),
        ("release_find_by_identifier", "wasde_page1"),
        ("release_find_by_pub_id", "1659_page0"),
    ],
)
def test_every_recorded_file_has_a_name_and_a_known_format(endpoint: str, case: str) -> None:
    for release in recorded(ReleaseResults, endpoint, case).results:
        files = release.release_files()
        assert files == [ReleaseFile.from_url(url) for url in release.files]
        assert [file.url for file in files] == release.files, "verbatim, in upstream order"
        for file in files:
            assert file.url.endswith(f"/{file.name}")
            assert "/" not in file.name
            assert file.name.endswith(f".{file.format}")
            assert file.format in FORMATS, file.url


@pytest.mark.parametrize(
    ("url", "name", "format"),
    [
        (WASDE_TXT, "wasde1026.txt", "txt"),
        (
            f"{BASE_URL}/sites/default/release-files/3t945q76s/bk128b299/wm117p338/"
            "wasde-08-12-2013.xml",
            "wasde-08-12-2013.xml",
            "xml",
        ),
        (f"{BASE_URL}/sites/default/release-files/1/REPORT.PDF", "REPORT.PDF", "pdf"),
        (f"{BASE_URL}/sites/default/release-files/1/latest", "latest", ""),
    ],
    ids=["recent-path", "hashed-path", "upper-case-extension", "no-extension"],
)
def test_release_file_from_url_reads_the_name_and_format(url: str, name: str, format: str) -> None:
    """The last path segment as printed; its extension lowercased, ``""`` without one."""
    assert ReleaseFile.from_url(url) == ReleaseFile(url=url, name=name, format=format)


type Download = Callable[[Path], Result[Downloaded]]
"""A call of the download, ``dest`` given."""

DOWNLOADS: list[tuple[Download, dict[str, Any]]] = [
    (lambda dest: tasks.download_release_file(796099, "txt", dest), {"format": "txt"}),
    (
        lambda dest: tasks.download_release_file(796099, dest=dest, name="wasde1026.txt"),
        {"name": "wasde1026.txt"},
    ),
    (
        lambda dest: tasks.download_release_file(796099, "txt", dest, name="wasde1026.txt"),
        {"format": "txt", "name": "wasde1026.txt"},
    ),
]
"""The positional call ``(release_id, format, dest)``, ``name`` alone and both, each with
what ``meta.request`` holds beside the release id and the URL."""


@pytest.mark.parametrize(("download", "chosen_by"), DOWNLOADS, ids=["format", "name", "both"])
def test_download_release_file(
    replay_fixture: ReplayFixture,
    tmp_path: Path,
    download: Download,
    chosen_by: dict[str, Any],
) -> None:
    release = replay_fixture("release_find_by_id", "796099")
    file = replay_fixture("download_release_file", "wasde1026_txt")
    recorded_file = load_fixture(FIXTURES / "download_release_file" / "wasde1026_txt.json").response
    dest = tmp_path / "wasde1026.txt"
    before = datetime.now(UTC)
    result = download(dest)
    after = datetime.now(UTC)
    assert isinstance(result.data, Downloaded)
    assert result.data.path == dest
    assert result.data.bytes == dest.stat().st_size == len(recorded_file.content) == 122378
    assert result.data.content_type == "text/plain"
    assert result.data.last_modified == "Fri, 09 Oct 2026 16:01:00 GMT"
    assert result.meta.endpoint == "wasde1026.txt", "the file's name as upstream prints it"
    assert result.meta.vintage == "796099"
    assert (result.meta.published_at, result.meta.published_at_naive) == (OCTOBER_PRINTED, True)
    assert result.meta.request == {"release_id": 796099, **chosen_by, "url": WASDE_TXT}
    assert result.meta.retrieved_at == result.data.retrieved_at
    assert_time_between(result.meta.retrieved_at, before, after)
    assert sent_urls(release) == [f"{API}/release/findById/796099"]
    assert sent_urls(file) == [WASDE_TXT]
    assert [path.name for path in tmp_path.iterdir()] == ["wasde1026.txt"], "no part file"


def test_download_release_file_refuses_a_format_the_release_lacks(
    replay_fixture: ReplayFixture, tmp_path: Path
) -> None:
    replay_fixture("release_find_by_id", "796099")
    download = replay_fixture("download_release_file", "wasde1026_txt")
    with pytest.raises(InvalidRequestError) as caught:
        tasks.download_release_file(796099, "zip", tmp_path / "wasde1026.zip")
    assert str(caught.value) == "release 796099 has no 'zip' file; its formats: pdf, txt, xls, xml"
    assert sent_urls(download) == []
    assert list(tmp_path.iterdir()) == []


def test_download_release_file_refuses_neither_format_nor_name(
    replay_fixture: ReplayFixture, tmp_path: Path
) -> None:
    release = replay_fixture("release_find_by_id", "796099")
    download = replay_fixture("download_release_file", "wasde1026_txt")
    with pytest.raises(InvalidRequestError) as caught:
        tasks.download_release_file(796099, dest=tmp_path / "wasde1026.txt")
    assert str(caught.value) == (
        "name the file of release 796099 to download: pass format, name or both; its files: "
        "wasde1026.pdf (pdf), wasde1026.txt (txt), wasde1026.xls (xls), wasde1026.xml (xml)"
    )
    assert sent_urls(release) == [f"{API}/release/findById/796099"], "the file list"
    assert sent_urls(download) == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("dest", "message"),
    [
        (None, "dest is required: name the file to write, e.g. 'wasde1026.txt'"),
        (".", "dest is a directory; name the file to write"),
        ("missing/wasde1026.txt", "dest's directory does not exist; create it first"),
    ],
    ids=["none", "a-directory", "a-missing-directory"],
)
def test_a_bad_dest_is_refused_before_any_request(
    replay_fixture: ReplayFixture,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
    dest: str | None,
    message: str,
) -> None:
    replay_fixture("release_find_by_id", "796099")
    replay_fixture("download_release_file", "wasde1026_txt")
    target = None if dest is None else tmp_path / dest
    with pytest.raises(InvalidRequestError) as caught:
        tasks.download_release_file(796099, "txt", target)
    assert str(caught.value) == message
    assert caught.value.source == SOURCE
    assert respx_mock.calls.call_count == 0, "refused before the release is looked up"
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
    assert len(tools) == len(routes) == 8


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
        "list_publications",
        {"agency_acronym": "WAOB"},
        [],
        [],
        lambda payload: (
            [row["id"] for row in payload["data"]] == ["1659", "1699"]
            and payload["meta"]["retrieved_at"] == PACKAGED_FETCHED
            and payload["meta"]["endpoint"] == "esmis_api_publication_findAll"
        ),
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
        lambda payload: (
            payload["data"]["id"] == payload["meta"]["vintage"] == "796099"
            and payload["meta"]["published_at"] == "2026-10-09T12:00:00"
            and payload["meta"]["published_at_naive"] is True
        ),
    ),
    (
        "list_release_files",
        {"release_id": 796099},
        [("release_find_by_id", "796099")],
        [f"{API}/release/findById/796099"],
        lambda payload: (
            [file["format"] for file in payload["data"]] == ["pdf", "txt", "xls", "xml"]
            and payload["meta"]["published_at"] == "2026-10-09T12:00:00"
            and payload["meta"]["published_at_naive"] is True
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
async def test_the_list_publications_tool_returns_200_rows_with_the_caps_note(
    respx_mock: respx.MockRouter,
) -> None:
    payload = await mcp_call(server, "usda_esmis_list_publications", {})
    whole = tasks.list_publications()
    assert len(whole.data) == PUBLICATIONS
    assert payload["data"] == [row.model_dump(mode="json") for row in whole.data[:200]]
    assert payload["note"] == CAP_NOTE
    assert payload["meta"]["retrieved_at"] == PACKAGED_FETCHED
    assert respx_mock.calls.call_count == 0


@pytest.mark.anyio
async def test_the_list_publications_tool_refuses_an_unknown_acronym_as_text() -> None:
    text = await mcp_call_text(server, "usda_esmis_list_publications", {"agency_acronym": "ers"})
    assert text.startswith("error: UnknownCode: 'ers' is not an agency_acronym")
    assert "Did you mean ERS (Economic Research Service)?" in text


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
