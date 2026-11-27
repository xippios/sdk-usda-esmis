"""Replay tests on recorded fixtures, at least one per task (conventions §10).

``/add-endpoint`` and ``/record-fixture`` add them.

Every task is replayed against the answers recorded for the wrappers on 2026-10-27, and
every tool but the bulk task is called end to end through the MCP server. Each answer a
test builds, or changes in memory, says where it comes from and names its kind where it is
built (conventions §10).
``list_publications`` answers from the packaged tables in ``reference/`` and sends
nothing: its tests mount no fixture and check that no request left. Four answers
were recorded for the tasks: WASDE's release page 1 (``release_find_by_identifier/
wasde_page1.json``), whose ids from before ESMIS's migration do not follow the dates, the October
2026 WASDE ``.txt`` (``download_release_file/wasde1026_txt.json``), the exchange the
download replays, and, on 2026-10-28, the WASDE of 2013-08-12
(``release_find_by_id/95621.json``), whose original and revised files of one format the
download's choice by ``format`` and ``name`` is tested on, without a download, and page 1
of every release (``release_find_all/page1.json``), which the walk of
``list_recent_releases`` crosses into. WASDE's release pages 0 to 7 of 2026-11-27
(``release_find_by_identifier/wasde_2026_11_27_page0.json`` to ``_page7.json``), read once
each by a probe of the whole list and written as served by core's writer, are the pages the
walks of ``list_releases`` from ``since`` cross, the two that hold older releases out of
place among them. The download is checked by path, size and content type, never by what
the file says (sdk-core ADR-0020).
"""

import importlib
import inspect
import json
import re
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from importlib import resources
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.routing import APIRoute
from pydantic import TypeAdapter
from xippios.core import (
    Downloaded,
    InvalidRequestError,
    MemoryCache,
    NotFoundError,
    PackagedList,
    Result,
    ResultCap,
    UnknownCode,
    UpstreamModel,
    ValidationError,
    check_dest,
    fetch_pages,
)
from xippios.core.mcp import cap_result, tool_name
from xippios.core.testing import (
    ReplayFixture,
    assert_projection,
    assert_time_between,
    load_fixture,
    mcp_call,
    mcp_call_text,
    recorded_query,
    sent_urls,
)

from xippios.usda.esmis import _client, tasks
from xippios.usda.esmis._client import BASE_URL, SOURCE, client
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
ROOT = Path(__file__).resolve().parents[1]
API = f"{BASE_URL}/api/v1"
WASDE_RELEASES = f"{API}/release/findByIdentifier/wasde"
ALL_RELEASES = f"{API}/release/findAll"
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
"""The keys a packaged file may hold (sdk-core ADR-0041, decision 5)."""
NOTHING_SENT = "Nothing was sent."
"""The sentence after the first of each refusal before a request (conventions §5)."""
WAOB = {"WAOB": "World Agricultural Outlook Board"}
"""The agency of every WASDE release, as ``meta.names`` names it by the packaged list."""
SEARCH_BY_KEYWORD = (
    "search_publications (over MCP, the tool usda_esmis_search_publications) finds "
    "identifiers by keyword"
)
"""How a refusal of an unknown identifier names the task to call instead (conventions §8)."""


def recorded_body(endpoint: str, case: str) -> Any:
    """A recorded answer's body, decoded as upstream sent it."""
    return json.loads(load_fixture(FIXTURES / endpoint / f"{case}.json").response.content)


def recorded[T](type_: type[T], endpoint: str, case: str) -> T:
    """A recorded answer, parsed as the wrapper parses it.

    The parsed recording is an input of the test, not an answer from ESMIS: no route serves
    it and no ``classify`` reads it, and a test compares it or hands it straight to the code
    under test, ``Release.release_files()`` and the walks' stop rules among them (conventions
    §10; sdk-core ADR-0064, decision 3).
    """
    return TypeAdapter(type_).validate_python(recorded_body(endpoint, case))


def releases_of(case: str) -> list[Release]:
    return recorded(ReleaseResults, "release_find_by_identifier", case).results


NOVEMBER = [f"wasde_2026_11_27_page{page}" for page in range(8)]
"""WASDE's release pages 0 to 7 as ESMIS served them on 2026-11-27, of 704 releases on 29."""


def recent_of(case: str) -> list[Release]:
    """A recorded page of every release (``esmis_api_release_findAll``)."""
    return recorded(ReleaseResults, "release_find_all", case).results


def printed_date(release: Release) -> date:
    return release.release_datetime.date()


def call_form(task: Callable[..., object]) -> str:
    """A task's signature as a caller writes the call: its parameters' kinds and defaults."""
    signature = inspect.signature(task)
    parameters = [
        parameter.replace(annotation=parameter.empty) for parameter in signature.parameters.values()
    ]
    return str(signature.replace(parameters=parameters, return_annotation=signature.empty))


CALL_FORMS = {
    "list_agencies": "()",
    "list_publications": "(*, search=None, agency_acronym=None)",
    "search_publications": "(query, *, page=None)",
    "get_publication": "(publication_identifier)",
    "list_releases": "(publication_identifier, *, since=None, until=None, page=None)",
    "list_recent_releases": "(*, since=None, until=None, page=None)",
    "get_release": "(release_id)",
    "download_release_file": "(release_id, *, dest, format=None, name=None)",
}
"""Each task's call form: what identifies a record by position, in the order of upstream's
path, and every filter and every argument of the package's own by name (sdk-core ADR-0061,
decision 5; https://github.com/xippios/sdk-usda-esr/issues/60, part 1)."""


@pytest.mark.parametrize(("name", "form"), CALL_FORMS.items(), ids=CALL_FORMS)
def test_the_arguments_that_name_a_record_come_first_and_the_rest_by_name(
    name: str, form: str
) -> None:
    assert sorted(CALL_FORMS) == sorted(tasks.__all__)
    assert call_form(getattr(tasks, name)) == form
    assert call_form(getattr(tasks, f"{name}_async")) == form


UNTYPED: Any = tasks
"""The tasks without their types, for the calls that their signatures refuse."""

BY_POSITION: dict[str, Callable[[Path], object]] = {
    "list_publications": lambda _: UNTYPED.list_publications("wheat"),
    "search_publications": lambda _: UNTYPED.search_publications("wasde", 0),
    "list_releases": lambda _: UNTYPED.list_releases("wasde", date(2026, 1, 1)),
    "list_recent_releases": lambda _: UNTYPED.list_recent_releases(date(2026, 10, 20)),
    "download_release_file": lambda dest: UNTYPED.download_release_file(796099, "txt", dest),
    "download_release_file-without-dest": lambda _: UNTYPED.download_release_file(
        796099, format="txt"
    ),
}
"""Calls that pass a filter, or an argument of the package's own, by position, and the
download without its ``dest``."""


@pytest.mark.parametrize("call", BY_POSITION.values(), ids=BY_POSITION)
def test_a_filter_by_position_is_refused_before_any_request(
    respx_mock: respx.MockRouter, tmp_path: Path, call: Callable[[Path], object]
) -> None:
    with pytest.raises(TypeError):
        call(tmp_path / "wasde1026.txt")
    assert respx_mock.calls.call_count == 0
    assert list(tmp_path.iterdir()) == []


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
    assert result.meta.retrieved_at == table.fetched, "the table's fetch time (sdk-core ADR-0041)"
    assert result.meta.retrieved_at == datetime.fromisoformat(PACKAGED_FETCHED)
    assert result.meta.request == {}, "filters left None are omitted"
    assert (result.meta.vintage, result.meta.published_at, result.meta.total) == (None,) * 3
    assert not result.meta.published_at_naive
    agencies = PackagedList.load(PACKAGE, "agency").parse(Agency, source=SOURCE)
    assert result.meta.names == {
        "agency_acronym": {agency.acronym: agency.title for agency in agencies}
    }, "every agency of the table, by the packaged agency list"
    assert result.meta.notes == []
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


@pytest.mark.parametrize("search", [None, "xippios-matches-nothing"])
def test_list_publications_names_the_acronym_asked_for(search: str | None) -> None:
    """``meta.names`` names the agency asked for, by its title, also where no row matches."""
    result = tasks.list_publications(search=search, agency_acronym="ERS")
    assert bool(result.data) is (search is None)
    assert result.meta.names["agency_acronym"]["ERS"] == "Economic Research Service"
    if not result.data:
        assert result.meta.names == {"agency_acronym": {"ERS": "Economic Research Service"}}


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
    assert message.startswith(
        f"{acronym!r} is not an agency_acronym in the packaged agency list "
        f"(fetched {agencies.fetched:%Y-%m-%d}). {NOTHING_SENT}"
    )
    assert "list_publications keeps the publications that list the acronym exactly" in message
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


def test_every_publication_but_654_has_an_identifier_without_a_slash() -> None:
    """What the texts on an identifier with ``/`` say, counted in the packaged table."""
    publications = PackagedList.load(PACKAGE, "publication").parse(PublicationRow, source=SOURCE)
    slashed = [row for row in publications if any("/" in name for name in row.identifier)]
    alone = [row for row in slashed if all("/" in name for name in row.identifier)]
    assert (len(slashed), len(alone)) == (71, 1)
    assert [(row.id, row.identifier) for row in alone] == [
        ("654", ["Market Trade Economic Division/SSS-yearbook"])
    ]


CAP_NOTE = (
    "showing 200 of 2522 rows (cap: 200 rows or 65536 bytes); filter with search (text of an "
    "id, an identifier or a title) or agency_acronym (as list_agencies spells it) to narrow "
    "the list; continue with offset=200"
)
"""The note of the MCP tool called without a filter: the default cap, paged, with its note."""


def test_the_python_task_returns_the_whole_table_the_tool_caps() -> None:
    cap = tasks.MCP_CAPS["list_publications"]
    assert (cap.max_rows, cap.max_bytes) == (ResultCap().max_rows, ResultCap().max_bytes)
    assert cap.paged, "a packaged answer: a continuation costs upstream nothing"
    result = tasks.list_publications()
    whole = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    assert len(result.data) == PUBLICATIONS, "Python callers get the whole table"
    cut = json.loads(cap_result(result, cap))
    assert cut["data"] == json.loads(whole)["data"][:200]
    assert cut["note"] == CAP_NOTE


CAPPED_PARAMETERS = {
    "list_publications": ["search", "agency_acronym"],
    "list_releases": ["since", "until", "page"],
    "search_publications": ["page"],
    "list_recent_releases": ["since", "until", "page"],
}
"""The tools with a cap of their own, and the parameters each cap's note names."""


def test_four_tools_keep_the_default_cap_with_a_note_naming_their_parameters() -> None:
    assert set(tasks.MCP_CAPS) == set(CAPPED_PARAMETERS)
    paged = [name for name, cap in tasks.MCP_CAPS.items() if cap.paged]
    assert paged == ["list_publications"], "the one tool whose second run sends no request"
    default = ResultCap()
    for name, named in CAPPED_PARAMETERS.items():
        cap = tasks.MCP_CAPS[name]
        assert (cap.max_rows, cap.max_bytes) == (default.max_rows, default.max_bytes), name
        assert cap.note is not None
        parameters = inspect.signature(getattr(tasks, name)).parameters
        for parameter in named:
            assert re.search(rf"\b{parameter}\b", cap.note), (name, parameter)
            assert parameter in parameters, "a note never promises a filter the tool lacks"


@pytest.mark.parametrize(
    ("task", "call", "fixture", "note"),
    [
        (
            "list_releases",
            lambda: tasks.list_releases("wasde", page=0),
            ("release_find_by_identifier", "wasde_page0"),
            "showing 10 of 25 rows (cap: 10 rows or 65536 bytes); bound the release dates "
            "with since and until (e.g. 2026-01-01), or pass page (0 for the newest 25 "
            "releases, then 1, 2, ...) to see the rest",
        ),
        (
            "search_publications",
            lambda: tasks.search_publications("wasde"),
            ("publication_search", "wasde_page0"),
            "showing 5 of 7 rows (cap: 5 rows or 65536 bytes); pass page (0, 1, 2, ...; 25 "
            "publications a page) to see the rest",
        ),
        (
            "list_recent_releases",
            lambda: tasks.list_recent_releases(page=0),
            ("release_find_all", "page0"),
            "showing 10 of 25 rows (cap: 10 rows or 65536 bytes); narrow the window with "
            "since and until (e.g. 2026-10-20), or pass page (0 for the 25 newest catalogued "
            "releases, then 1, 2, ...) to see the rest",
        ),
    ],
    ids=["list_releases", "search_publications", "list_recent_releases"],
)
def test_a_cut_list_carries_its_tools_note(
    replay_fixture: ReplayFixture,
    task: str,
    call: Callable[[], Result[Any]],
    fixture: tuple[str, str],
    note: str,
) -> None:
    replay_fixture(*fixture)
    result = call()
    rows = int(note.split()[1])
    cap = ResultCap(max_rows=rows, note=tasks.MCP_CAPS[task].note)
    cut = json.loads(cap_result(result, cap))
    assert len(cut["data"]) == rows
    assert cut["note"] == note


@pytest.mark.anyio
async def test_no_tool_description_states_the_cap() -> None:
    """The cap's advice is in the notes of ``MCP_CAPS``, never in a tool's description."""
    tools = {tool.name: tool for tool in await server.list_tools()}
    for name in tasks.__all__:
        if name in tasks.BULK_TASKS:
            continue
        description = tools[tool_name(SOURCE, getattr(tasks, name))].description or ""
        for text in ("200 rows", "64 KB", "65536"):
            assert text not in description, (name, text)


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
    with pytest.raises(InvalidRequestError) as caught:
        tasks.search_publications(query)
    assert str(caught.value).startswith(f"query must not be empty or blank. {NOTHING_SENT}")
    assert sent_urls(route) == [], "refused before anything is sent"


@pytest.mark.anyio
async def test_a_page_of_another_size_stops_the_walk(respx_mock: respx.MockRouter) -> None:
    """NOT RECORDED: page 0 of ``publication_search`` for ``wasde`` as recorded on 2026-10-27,
    its pager's ``items_per_page`` changed in memory from 25 to 50, a form upstream was not
    seen to send (conventions §10, kind 4): the walk counts its offsets in pages of 25, so it
    refuses rather than skip or repeat items, naming what it sent."""
    body = recorded_body("publication_search", "wasde_page0")
    body["pager"]["items_per_page"] = 50
    route = respx_mock.get(f"{API}/publication/search").respond(json=body)
    with pytest.raises(ValidationError) as caught:
        await tasks.search_publications_async("wasde")
    assert str(caught.value).startswith(
        "ESMIS answered page 0 of GET /api/v1/publication/search in pages of 50 items, where "
        "the walk counts 25"
    )
    assert caught.value.source == SOURCE
    assert sent_urls(route) == [f"{API}/publication/search?query=wasde&page=0"]


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


def test_get_publication_refuses_an_identifier_that_two_publications_share(
    respx_mock: respx.MockRouter,
) -> None:
    """NOT RECORDED: the recorded answer of ``publication_find_by_identifier/wasde.json`` with
    a second recorded publication, 1762 of ``publication_search/wasde_page0.json``, appended to
    its results and its pager counting 2, the form that the probe of ``AMS_1045`` saw and no
    fixture holds (conventions §10, kind 4)."""
    body = recorded_body("publication_find_by_identifier", "wasde")
    second = recorded_body("publication_search", "wasde_page0")["results"][0]
    assert second["id"] == "1762"
    body["results"].append(second)
    body["pager"]["total_results"] = 2
    route = respx_mock.get(f"{API}/publication/findByIdentifier/wasde").respond(json=body)
    with pytest.raises(InvalidRequestError) as caught:
        tasks.get_publication("wasde")
    assert str(caught.value) == (
        "ESMIS answered GET /api/v1/publication/findByIdentifier/wasde with 2 publications, "
        "1659 and 1762, so the identifier names no one publication and none is returned; "
        f"{SEARCH_BY_KEYWORD}, and its answer holds each publication whole."
    )
    assert caught.value.source == SOURCE
    assert sent_urls(route) == [f"{API}/publication/findByIdentifier/wasde"]


def test_get_publication_unknown_is_not_found(replay_fixture: ReplayFixture) -> None:
    replay_fixture("publication_find_by_identifier", "unknown")
    with pytest.raises(NotFoundError) as caught:
        tasks.get_publication("xippios-no-such-identifier")
    message = str(caught.value)
    assert "'xippios-no-such-identifier'" in message
    assert "GET /api/v1/publication/findByIdentifier/xippios-no-such-identifier" in message
    assert message.endswith(SEARCH_BY_KEYWORD), "names the task and its tool (conventions §8)"
    assert BASE_URL not in message, "a message names the path, never the host"


def test_get_publication_with_a_slash_is_refused(replay_fixture: ReplayFixture) -> None:
    replay_fixture("publication_find_by_identifier", "with_slash")
    with pytest.raises(InvalidRequestError, match="encoded slash") as caught:
        tasks.get_publication("Market and Trade Economics Division/FDS")
    message = str(caught.value)
    assert message.endswith("every publication but 654 has one without '/'.")
    named = re.findall(r"\b(?:list|get|search|download)_[a-z_]+", message)
    assert named == ["list_publications"], "a lookup that a task has, and no other"


def test_the_texts_on_a_slash_say_that_publication_654_has_no_other() -> None:
    """The tool's description and the arguments' texts that ask for an identifier without
    ``/`` say that publication 654 has none, as the packaged table counts it."""
    for task in (tasks.get_publication, tasks.list_releases):
        assert "publication 654" in (task.__doc__ or ""), task.__name__
    assert "but publication 654" in (tasks.get_publication.__doc__ or "").split("Args:")[0]


def test_list_releases_one_page(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_identifier", "wasde_page0", match_params=["page"])
    result = tasks.list_releases("wasde", page=0)
    assert result.data == releases_of("wasde_page0")
    assert result.meta.endpoint == "esmis_api_release_findByIdentifier"
    assert result.meta.request == {"publication_identifier": "wasde", "page": 0}
    assert result.meta.total == 703, "upstream's count for the whole publication"
    assert (result.meta.vintage, result.meta.published_at) == (None, None)
    assert sent_urls(route) == [f"{WASDE_RELEASES}?page=0"]


def test_list_releases_walks_to_the_first_page_whose_newest_release_is_before_since(
    replay_fixture: ReplayFixture,
) -> None:
    routes = [
        replay_fixture("release_find_by_identifier", case, match_params=["page"])
        for case in NOVEMBER[:3]
    ]
    since = date(2024, 1, 1)
    result = tasks.list_releases("wasde", since=since)
    walked = [release for case in NOVEMBER[:3] for release in releases_of(case)]
    assert result.data == [release for release in walked if printed_date(release) >= since]
    assert len(result.data) == 34
    assert (result.data[0].id, result.data[-1].id) == ("796142", "95494")
    assert printed_date(result.data[-1]) == date(2024, 1, 12)
    assert result.meta.request == {"publication_identifier": "wasde", "since": since}
    assert result.meta.total == 704, "may exceed len(data) after the date filter"
    # Page 1's oldest release (2022-09-12) is before since, its newest (2024-09-12) is not:
    # the walk goes on. Page 2's newest (2022-08-12) is before since: the walk ends there,
    # one page past the last release it keeps, with no request for page 3.
    assert [sent_urls(route) for route in routes] == [
        [f"{WASDE_RELEASES}?page={page}"] for page in range(3)
    ]


def test_a_walk_from_since_reaches_the_releases_past_the_pages_out_of_place(
    replay_fixture: ReplayFixture,
) -> None:
    """WASDE's pages 3 and 4 hold older releases out of place, so their oldest are dated
    before 2015-10-01 while pages 4 to 6 still list releases from then on, the October 2015
    WASDE on page 6 (https://github.com/xippios/sdk-usda-esmis/issues/67). The walk ends at
    page 7, the first whose newest release (2014-02-10) is dated before ``since``."""
    routes = [
        replay_fixture("release_find_by_identifier", case, match_params=["page"])
        for case in NOVEMBER
    ]
    since = date(2015, 10, 1)
    result = tasks.list_releases("wasde", since=since)
    walked = [release for case in NOVEMBER for release in releases_of(case)]
    assert result.data == [release for release in walked if printed_date(release) >= since]
    assert len(result.data) == 135
    october = [release for release in result.data if printed_date(release) < date(2015, 11, 1)]
    assert [(release.id, printed_date(release)) for release in october] == [
        ("95595", date(2015, 10, 9))
    ]
    assert result.meta.total == 704
    assert [sent_urls(route) for route in routes] == [
        [f"{WASDE_RELEASES}?page={page}"] for page in range(8)
    ]


def test_a_walk_from_since_is_refused_where_24_pages_do_not_end_it(
    replay_fixture: ReplayFixture,
) -> None:
    """A walk from ``since`` runs its stop rule, so core refuses it at the bound, not before.

    NOT RECORDED at pages 8 to 23: page 7 of 2026-11-27 replayed at its own path for the
    other pages, where its newest release, dated 2014-02-10, never ends a walk from
    1982-02-11, a test that asserts what was sent and the refusal (conventions §10, kind 3).
    On the list as ESMIS served it that day, page 23's newest release is dated 1982-02-11,
    so such a walk needs a 25th page.
    """
    routes = [
        replay_fixture("release_find_by_identifier", case, match_params=["page"])
        for case in NOVEMBER[:7]
    ]
    rest = replay_fixture("release_find_by_identifier", NOVEMBER[7])
    with pytest.raises(InvalidRequestError) as caught:
        tasks.list_releases("wasde", since=date(1982, 2, 11))
    assert str(caught.value) == (
        "the walk needs more than the 24 pages that one call fetches: upstream counts 704 "
        "records on 29 pages of 25, and the walk reached page 24 of 29 after 24 requests. It "
        "returns nothing; pass page to fetch one page at a time."
    )
    assert caught.value.source == SOURCE
    assert [url for route in routes for url in sent_urls(route)] + sent_urls(rest) == [
        f"{WASDE_RELEASES}?page={page}" for page in range(24)
    ]


def test_no_recorded_page_lists_a_release_after_the_newest_of_a_page_before_it() -> None:
    """The order the walk of ``list_releases`` from ``since`` relies on, on the pages recorded.

    Each page's newest release is dated before the newest of the page before it, while pages
    3 and 4 are out of date order: 95866 of 1995-01-31 stands on page 3 among releases of
    2019, and page 4 opens with eighteen of 2002 to 2006 (``docs/upstream/OBSERVED.md``, "A
    publication's releases come newest first page by page").
    """
    pages = [[printed_date(release) for release in releases_of(case)] for case in NOVEMBER]
    newest = [max(dates) for dates in pages]
    assert all(later < earlier for earlier, later in pairwise(newest))
    in_order = [dates == sorted(dates, reverse=True) for dates in pages]
    assert in_order == [True, True, True, False, False, True, True, True]
    assert date(1995, 1, 31) in pages[3]
    assert {day.year for day in pages[4][:18]} <= set(range(2002, 2007))
    assert {day.year for day in pages[4][18:]} == {2018}


def test_the_description_of_list_releases_names_its_rule_and_the_dates_it_cannot_walk() -> None:
    """The tool's description says where a walk from ``since`` ends, and the text of ``since``
    which WASDE dates the bound leaves to ``page``, as the probe of 2026-11-27 counted them."""
    description, arguments = (tasks.list_releases.__doc__ or "").split("Args:")
    flat = " ".join(description.split())
    assert "the first page whose newest release is dated before it" in flat
    assert "newest first" not in flat.split(".")[0], "the summary claims no order of the list"
    since = " ".join(arguments.split("since:")[1].split("until:")[0].split())
    assert "one page past the last release it keeps" in since
    assert "for a ``since`` before 1982-02-12" in since


def test_list_releases_keeps_the_printed_dates_between_since_and_until(
    replay_fixture: ReplayFixture,
) -> None:
    route = replay_fixture("release_find_by_identifier", "wasde_page0", match_params=["page"])
    second = replay_fixture("release_find_by_identifier", "wasde_page1", match_params=["page"])
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
    # Page 0's newest release (2026-10-09) is not before since, page 1's (2024-08-12) is:
    # two requests, and until ends nothing of the walk.
    assert sent_urls(route) == [f"{WASDE_RELEASES}?page=0"]
    assert sent_urls(second) == [f"{WASDE_RELEASES}?page=1"]


def test_list_releases_without_since_or_page_is_refused_past_the_bound(
    replay_fixture: ReplayFixture,
) -> None:
    """WASDE's 703 releases fill 29 pages, more than the 24 that one call fetches."""
    route = replay_fixture("release_find_by_identifier", "wasde_page0", match_params=["page"])
    with pytest.raises(InvalidRequestError) as caught:
        tasks.list_releases("wasde")
    assert str(caught.value) == (
        "the walk needs more than the 24 pages that one call fetches: upstream counts 703 "
        "records on 29 pages of 25, and the walk reached page 1 of 29 after 1 request. It "
        "returns nothing; pass page to fetch one page at a time."
    )
    assert caught.value.source == SOURCE
    assert tasks.WALK_PAGES == 24
    assert sent_urls(route) == [f"{WASDE_RELEASES}?page=0"], "one request, then the refusal"


def test_the_latest_release_is_the_first_row_of_page_zero(replay_fixture: ReplayFixture) -> None:
    """Page 0 of a publication's releases runs latest ``release_datetime`` first, and no later
    page lists a release dated after its newest, as observed."""
    replay_fixture("release_find_by_identifier", "wasde_page0", match_params=["page"])
    result = tasks.list_releases("wasde", page=0)
    assert result.data[0] == max(result.data, key=lambda release: release.release_datetime)
    assert result.data[0].id == "796099"
    assert result.meta.names == {"agency_acronym": WAOB}


def test_list_releases_unknown_identifier_is_empty(replay_fixture: ReplayFixture) -> None:
    """The empty list and a note that says what upstream counted, where upstream answers so."""
    route = replay_fixture("release_find_by_identifier", "unknown")
    result = tasks.list_releases("nope-nope")
    assert result.data == []
    assert result.meta.total == 0, "as the pager says"
    assert result.meta.notes == [
        "ESMIS counts no release for the identifier 'nope-nope', as it answers an identifier "
        f"it does not know; {SEARCH_BY_KEYWORD}."
    ]
    assert sent_urls(route) == [f"{API}/release/findByIdentifier/nope-nope?page=0"]


def test_list_releases_writes_no_note_where_upstream_counts_releases(
    replay_fixture: ReplayFixture,
) -> None:
    """A date filter that keeps no release is the package's own: upstream counted 703."""
    replay_fixture("release_find_by_identifier", "wasde_page0", match_params=["page"])
    result = tasks.list_releases("wasde", since=date(2026, 10, 10), until=date(2026, 10, 11))
    assert (result.data, result.meta.total, result.meta.notes) == ([], 703, [])


def test_list_releases_refuses_since_after_until(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_identifier", "wasde_page0")
    with pytest.raises(InvalidRequestError) as caught:
        tasks.list_releases("wasde", since=date(2026, 1, 1), until=date(2025, 1, 1))
    assert str(caught.value) == (
        f"since (2026-01-01) is after until (2025-01-01): no release can lie between them. "
        f"{NOTHING_SENT}"
    )
    assert sent_urls(route) == []


def test_list_recent_releases_one_page(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_all", "page0", match_params=["page"])
    result = tasks.list_recent_releases(page=0)
    assert result.data == recent_of("page0")
    assert len(result.data) == 25
    ids = [int(release.id) for release in result.data]
    assert ids == sorted(ids, reverse=True), "the latest catalogued first"
    assert result.meta.endpoint == "esmis_api_release_findAll"
    assert result.meta.request == {"page": 0}
    assert result.meta.total == 1542025, "upstream's count of every release"
    assert (result.meta.vintage, result.meta.published_at) == (None, None)
    assert sent_urls(route) == [f"{ALL_RELEASES}?page=0"]


def test_list_recent_releases_one_page_keeps_the_printed_dates_between_since_and_until(
    replay_fixture: ReplayFixture,
) -> None:
    route = replay_fixture("release_find_all", "page0", match_params=["page"])
    since, until = date(2026, 10, 20), date(2026, 10, 22)
    result = tasks.list_recent_releases(since=since, until=until, page=0)
    assert [release.id for release in result.data] == [
        release.id for release in recent_of("page0") if since <= printed_date(release) <= until
    ]
    assert len(result.data) == 8
    assert {printed_date(release) for release in result.data} == {
        date(2026, 10, 20),
        date(2026, 10, 21),
        date(2026, 10, 22),
    }
    assert result.meta.request == {"since": since, "until": until, "page": 0}
    assert result.meta.total == 1542025, "before the date filter"
    # page given: that page alone, whatever its dates.
    assert sent_urls(route) == [f"{ALL_RELEASES}?page=0"]


def test_list_recent_releases_walks_until_a_page_is_newest_more_than_14_days_before_since(
    replay_fixture: ReplayFixture,
) -> None:
    """The walk goes on past a page whose oldest release is before ``since``.

    The two pages were recorded a day apart, page 0 on 2026-10-27 and page 1 on
    2026-10-28: three releases catalogued in between moved 796100, 796099 and 796098 from
    the end of page 0 to the head of page 1, so both pages list them. ``since`` lies after
    their dates (2026-10-09 and 2026-09-28), so the filter drops them, as it drops every
    release of page 1.
    """
    first = replay_fixture("release_find_all", "page0", match_params=["page"])
    second = replay_fixture("release_find_all", "page1", match_params=["page"])
    since = date(2026, 10, 24)
    result = tasks.list_recent_releases(since=since)
    walked = recent_of("page0") + recent_of("page1")
    assert result.data == [release for release in walked if printed_date(release) >= since]
    assert [release.id for release in result.data] == ["796124"]
    assert all(printed_date(release) >= since for release in result.data)
    assert result.meta.endpoint == "esmis_api_release_findAll"
    assert result.meta.request == {"since": since}
    assert result.meta.total == 1542028, "page 1's count, the last page fetched"
    assert result.meta.notes == [
        "The walk ended at page 1, the first page whose newest release is dated more than 14 "
        "days before since (2026-10-24); a release catalogued on a later page is not listed, "
        "and page reads it."
    ]
    # Page 0's oldest release (2026-09-28) is before since, where a rule on a page's oldest
    # would stop; its newest (2026-10-26) is not 14 days before since, so the walk goes on.
    # Page 1's newest (2026-10-09) is 15 days before since: the walk ends there, with no
    # request for page 2, which no route answers and the plugin refuses.
    assert sent_urls(first) == [f"{ALL_RELEASES}?page=0"]
    assert sent_urls(second) == [f"{ALL_RELEASES}?page=1"]


def test_a_walk_keeps_a_release_that_two_pages_list_once(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    """NOT RECORDED: page 1 of ``release_find_all`` as recorded on 2026-10-28, its pager's
    ``total_results`` changed in memory to 50 so that the walk ends there by upstream's
    count, a form upstream was not seen to send (conventions §10, kind 4); page 0 is
    replayed as recorded. Both pages list 796100, 796099 and 796098: three releases
    catalogued between the two recordings moved them from the end of page 0 to the head of
    page 1, and the walk keeps each once."""
    first = replay_fixture("release_find_all", "page0", match_params=["page"])
    body = recorded_body("release_find_all", "page1")
    body["pager"]["total_results"] = 50
    second = respx_mock.get(ALL_RELEASES, params={"page": "1"}).respond(json=body)
    result = tasks.list_recent_releases(since=date(2026, 9, 28))
    ids = [release.id for release in result.data]
    for repeated in ("796100", "796099", "796098"):
        assert ids.count(repeated) == 1, repeated
    assert len(ids) == len(set(ids))
    assert result.meta.notes == ["The walk ended at the last page of esmis_api_release_findAll."]
    assert sent_urls(first) == [f"{ALL_RELEASES}?page=0"]
    assert sent_urls(second) == [f"{ALL_RELEASES}?page=1"]


@pytest.mark.parametrize(
    ("case", "since", "last"),
    [
        ("page0", date(2026, 11, 9), False),
        ("page0", date(2026, 11, 10), True),
        ("page0", date(2026, 10, 10), False),
        ("page1", date(2026, 10, 23), False),
        ("page1", date(2026, 10, 24), True),
    ],
)
def test_the_stop_rule_needs_a_page_newest_more_than_14_days_before_since(
    case: str, since: date, last: bool
) -> None:
    """Page 0's newest release is dated 2026-10-26, page 1's 2026-10-09.

    ``list_recent_releases`` ends its walk 14 days before ``since``: 14 days walks on, 15
    ends the walk; page 0's release of 2026-09-28, before 2026-10-10, ends nothing.
    """
    rule = tasks._newest_before(since - tasks.ORDER_TOLERANCE)
    assert rule(recent_of(case)) is last
    assert rule([]) is False, "an empty page ends the walk anyway"


@pytest.mark.parametrize(
    ("since", "last"),
    [(date(2020, 7, 11), True), (date(2020, 7, 10), False), (date(1995, 2, 1), False)],
)
def test_the_stop_rule_of_list_releases_reads_a_page_s_newest_release(
    since: date, last: bool
) -> None:
    """WASDE's page 3 of 2026-11-27 runs 2020-07-10 back to 2018-12-11 with three older
    releases out of place, 95866 of 1995-01-31 among them: its newest ends a walk from a
    later ``since``, and its oldest ends none."""
    assert tasks._newest_before(since)(releases_of(NOVEMBER[3])) is last
    assert tasks._newest_before(since)([]) is False, "an empty page ends the walk anyway"


def test_the_tolerance_covers_the_order_recorded() -> None:
    """On findAll's two recorded pages, no release is dated more than 14 days before one
    catalogued earlier; the order beyond them is read from WASDE's recordings (next test).
    """
    dated = {
        int(release.id): printed_date(release)
        for case in ("page0", "page1")
        for release in recent_of(case)
    }
    gaps = {
        later: max(
            (dated[earlier] - dated[later] for earlier in dated if earlier < later),
            default=timedelta(0),
        )
        for later in dated
    }
    largest = max(gaps.values())
    assert largest == timedelta(days=14) == tasks.ORDER_TOLERANCE, "796123 against 796122"
    assert {later for later, gap in gaps.items() if gap > timedelta(0)} == {796123, 796098}
    assert gaps[796098] == timedelta(days=9)


def test_the_bound_is_the_first_wasde_release_of_the_new_ids() -> None:
    """Below ESMIS's migration the ids do not follow the dates; above it they do.

    WASDE as recorded: the ids jump from 96171 (2025-06-12) to 791996 (2025-09-12); every
    old id is dated before the bound, and among them a higher id can carry an older date.
    """
    wasde = releases_of("wasde_page0") + releases_of("wasde_page1")
    wasde += recorded(ReleaseResults, "release_find_by_id", "95621").results
    dated = {int(release.id): printed_date(release) for release in wasde}
    new = {id_: day for id_, day in dated.items() if id_ >= 791996}
    old = {id_: day for id_, day in dated.items() if id_ < 791996}
    assert max(old) == 96171
    assert min(new) == 791996
    assert min(new.values()) == new[791996] == tasks.CATALOG_ORDER_SINCE
    assert max(old.values()) == dated[96169] == date(2025, 8, 12)
    by_id = [day for _, day in sorted(new.items(), reverse=True)]
    assert by_id == sorted(by_id, reverse=True), "the new ids follow the dates"
    assert [dated[id_].month for id_ in range(96165, 96172)] == [5, 4, 3, 2, 8, 7, 6]
    assert dated[95511] == date(2022, 8, 12)
    assert dated[95621] == date(2013, 8, 12)
    assert dated[95482] == date(2025, 1, 10), "a lower id with a later date than both"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {"since": date(2026, 10, 24), "until": date(2026, 10, 20)},
            "since (2026-10-24) is after until (2026-10-20)",
        ),
        (
            {"since": date(2026, 10, 24), "until": date(2026, 10, 20), "page": 0},
            "since (2026-10-24) is after until (2026-10-20)",
        ),
        ({"since": date(2025, 9, 11)}, "since (2025-09-11) is before 2025-09-12"),
        (
            {"since": date(2025, 9, 11), "until": date(2025, 9, 30)},
            "since (2025-09-11) is before 2025-09-12",
        ),
        (
            {"since": date(2025, 9, 11), "until": date(2025, 9, 1)},
            "since (2025-09-11) is after until (2025-09-01)",
        ),
    ],
    ids=[
        "since-after-until",
        "since-after-until-with-page",
        "since-before-the-bound",
        "since-before-the-bound-with-until",
        "since-after-until-before-the-bound",
    ],
)
def test_list_recent_releases_refuses_before_any_request(
    respx_mock: respx.MockRouter, arguments: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidRequestError) as caught:
        tasks.list_recent_releases(**arguments)
    text = str(caught.value)
    assert text.startswith(message)
    assert f". {NOTHING_SENT} " in text or text.endswith(f". {NOTHING_SENT}")
    assert caught.value.source == SOURCE
    if message.endswith("is before 2025-09-12"):
        assert (
            "Use list_releases (over MCP, the tool usda_esmis_list_releases) for one "
            "publication's older releases, pass page"
        ) in text, "names the task and its tool (conventions §8)"
        assert "pass page to read older pages" in text
    assert respx_mock.calls.call_count == 0, "refused before any request"


def test_a_walk_from_since_is_refused_after_24_requests(replay_fixture: ReplayFixture) -> None:
    """A walk from ``since`` runs its stop rule, so core refuses it at the bound, not before.

    NOT RECORDED at pages 1 to 23: page 0 of ``release_find_all`` as recorded on 2026-10-27,
    replayed at its own path for the other pages, where its newest release, dated
    2026-10-26, never ends a walk from 2026-10-24, a test that asserts what was sent and the
    refusal (conventions §10, kind 3).
    """
    route = replay_fixture("release_find_all", "page0")
    with pytest.raises(InvalidRequestError) as caught:
        tasks.list_recent_releases(since=date(2026, 10, 24))
    assert str(caught.value) == (
        "the walk needs more than the 24 pages that one call fetches: upstream counts "
        "1,542,025 records on 61,681 pages of 25, and the walk reached page 24 of 61,681 after "
        "24 requests. It returns nothing; pass page to fetch one page at a time."
    )
    assert sent_urls(route) == [f"{ALL_RELEASES}?page={page}" for page in range(24)]


@pytest.mark.parametrize(
    "arguments", [{}, {"until": date(2026, 10, 23)}], ids=["neither", "until-alone"]
)
def test_list_recent_releases_without_since_is_refused_after_its_first_request(
    replay_fixture: ReplayFixture, arguments: dict[str, Any]
) -> None:
    """Without ``since`` the walk has no stop, and the catalog's 61,681 pages pass the bound.

    ``until`` bounds nothing of the walk, which starts at the newest catalogued release.
    """
    route = replay_fixture("release_find_all", "page0", match_params=["page"])
    with pytest.raises(InvalidRequestError) as caught:
        tasks.list_recent_releases(**arguments)
    assert str(caught.value) == (
        "the walk needs more than the 24 pages that one call fetches: upstream counts "
        "1,542,025 records on 61,681 pages of 25, and the walk reached page 1 of 61,681 after "
        "1 request. It returns nothing; pass page to fetch one page at a time."
    )
    assert sent_urls(route) == [f"{ALL_RELEASES}?page=0"]


@pytest.mark.parametrize("since", [date(2025, 9, 12), date(2025, 9, 11)])
def test_with_page_any_since_only_filters_the_page(
    replay_fixture: ReplayFixture, since: date
) -> None:
    """The bound is the walk's: with ``page`` given, ``since`` filters that page alone."""
    route = replay_fixture("release_find_all", "page0", match_params=["page"])
    result = tasks.list_recent_releases(since=since, page=0)
    assert result.data == recent_of("page0"), "every release of page 0 is dated after since"
    assert result.meta.request == {"since": since, "page": 0}
    assert sent_urls(route) == [f"{ALL_RELEASES}?page=0"]


def test_list_recent_releases_returns_esmis_s_test_releases(replay_fixture: ReplayFixture) -> None:
    """ESMIS's catalog lists test releases among the others, and the task returns them as listed.

    Page 0 of 2026-10-27 holds three, the identifier ``test`` and the title ``Test DDO``
    (``docs/upstream/OBSERVED.md``, "``/release/findAll`` lists test releases"), and the
    tool's description names them (https://github.com/xippios/sdk-usda-esmis/issues/32).
    """
    replay_fixture("release_find_all", "page0")
    result = tasks.list_recent_releases(page=0)
    test = [(item.id, item.title) for item in result.data if item.identifier == ["test"]]
    assert test == [("796113", "Test DDO"), ("796105", "Test DDO"), ("796098", "Test DDO")]
    description = (tasks.list_recent_releases.__doc__ or "").split("Args:")[0]
    assert '``"test"``' in description
    assert '``"Test DDO"``' in description


@pytest.mark.anyio
async def test_the_walk_stops_at_total_pages_without_a_request_past_it() -> None:
    """A full last page ends the walk by upstream's count: no request for the page after.

    The pager of one full page is an input of the test, not an answer from ESMIS.
    """
    full = releases_of("wasde_page0")
    pager = Pager(current_page=0, items_per_page=25, total_pages=1, total_results=25)
    asked: list[int] = []

    async def fetch(offset: int) -> tuple[Sequence[Release], int | None]:
        asked.append(offset // tasks.PAGE_SIZE)
        return tasks._page(pager, full, 0, "GET /api/v1/release/findByIdentifier/wasde")

    items, total = await fetch_pages(
        fetch, page_size=tasks.PAGE_SIZE, most=tasks.WALK_PAGES, paging="page"
    )
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
    assert result.meta.names == {"agency_acronym": WAOB}, "by the packaged agency list"
    assert result.data.files == [
        f"{BASE_URL}/sites/default/release-files/796099/wasde1026.{kind}"
        for kind in ("pdf", "txt", "xls", "xml")
    ], "each file's URL, in upstream order"
    assert sent_urls(route) == [f"{API}/release/findById/796099"]


def test_the_files_of_a_release_are_get_release_s_answer() -> None:
    """No task lists a release's files beside ``get_release``, whose answer holds their URLs
    and whose ``Release.release_files()`` reads their names and formats in Python."""
    package = importlib.import_module(PACKAGE)
    assert "list_release_files" not in tasks.__all__
    assert "list_release_files" not in package.__all__
    assert not hasattr(tasks, "list_release_files")
    assert not hasattr(tasks, "list_release_files_async")


def test_a_second_call_within_the_cache_lifetime_sends_no_request(
    replay_fixture: ReplayFixture,
) -> None:
    """Core's response cache keeps every path for its default 300 s (sdk-core ADR-0061, 11)."""
    assert isinstance(_client.config.cache, MemoryCache)
    assert dict(_client.config.cache.lifetimes) == {"/": 300.0}
    route = replay_fixture("release_find_by_id", "796099")
    first = tasks.get_release(796099)
    second = tasks.get_release(796099)
    assert second.data == first.data
    assert second.meta.retrieved_at == first.meta.retrieved_at, "when the answer was stored"
    assert sent_urls(route) == [f"{API}/release/findById/796099"], "one request for two calls"


def test_get_release_unknown_is_not_found(replay_fixture: ReplayFixture) -> None:
    replay_fixture("release_find_by_id", "unknown")
    with pytest.raises(NotFoundError, match="HTTP 404"):
        tasks.get_release(999999999)


def test_release_files_reads_each_file_s_url_name_and_format() -> None:
    """``Release.release_files()`` on the release that ``get_release(796099)`` answers."""
    (release,) = recorded(ReleaseResults, "release_find_by_id", "796099").results
    assert release.release_files() == [
        ReleaseFile(
            url=f"{BASE_URL}/sites/default/release-files/796099/wasde1026.{kind}",
            name=f"wasde1026.{kind}",
            format=kind,
        )
        for kind in ("pdf", "txt", "xls", "xml")
    ]


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
READ_95621 = (
    "The release was read by GET /api/v1/release/findById/95621, and no file was requested."
)
"""What a refusal of a choice says was sent: the release lookup, and no file."""


def august_2013() -> Release:
    (release,) = recorded(ReleaseResults, "release_find_by_id", "95621").results
    return release


def august_2013_file(name: str) -> ReleaseFile:
    (path,) = [path for path, _ in AUGUST_2013 if path.endswith(f"/{name}")]
    return ReleaseFile.from_url(f"{BASE_URL}/sites/default/release-files/{path}")


def test_release_files_keep_an_original_and_a_revised_file_in_upstream_order() -> None:
    files = august_2013().release_files()
    assert files == [
        ReleaseFile(
            url=f"{BASE_URL}/sites/default/release-files/{path}",
            name=path.rsplit("/", 1)[-1],
            format=kind,
        )
        for path, kind in AUGUST_2013
    ]
    xml = [file.name for file in files if file.format == "xml"]
    assert xml == ["ORIGwasde-08-12-2013.xml", "wasde-08-12-2013.xml"]


def test_get_release_of_an_original_and_a_revised_file(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_id", "95621")
    result = tasks.get_release(95621)
    assert result.data == august_2013()
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
            f"release 95621's file 'wasde-08-12-2013.xml' has the format 'xml', not 'pdf'. "
            f"{READ_95621} Pass format='xml' or leave format out.",
        ),
        (
            None,
            "wasde-08-12-2013.txt",
            f"release 95621 has no file named 'wasde-08-12-2013.txt'; its files: "
            f"{AUGUST_2013_LISTING}. {READ_95621}",
        ),
        (
            "xml",
            "WASDE-08-12-2013.xml",
            f"release 95621 has no file named 'WASDE-08-12-2013.xml'; its files: "
            f"{AUGUST_2013_LISTING}. {READ_95621}",
        ),
        (
            "txt",
            None,
            f"release 95621 has no 'txt' file; its formats: xls, pdf, xml. {READ_95621}",
        ),
    ],
    ids=["name-of-another-format", "unknown-name", "name-as-spelt", "no-such-format"],
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
        ("release_find_all", "page1"),
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
    (lambda dest: tasks.download_release_file(796099, dest=dest, format="txt"), {"format": "txt"}),
    (
        lambda dest: tasks.download_release_file(796099, dest=dest, name="wasde1026.txt"),
        {"name": "wasde1026.txt"},
    ),
    (
        lambda dest: tasks.download_release_file(
            796099, dest=dest, format="txt", name="wasde1026.txt"
        ),
        {"format": "txt", "name": "wasde1026.txt"},
    ),
]
"""The file chosen by ``format``, by ``name`` and by both, each with what ``meta.request``
holds beside the release id and the URL."""


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
        tasks.download_release_file(796099, dest=tmp_path / "wasde1026.zip", format="zip")
    assert str(caught.value) == (
        "release 796099 has no 'zip' file; its formats: pdf, txt, xls, xml. The release was "
        "read by GET /api/v1/release/findById/796099, and no file was requested."
    )
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
        f"name the file of release 796099 to download: pass format, name or both. "
        f"{NOTHING_SENT} get_release answers the release's files, and "
        "Release.release_files() reads their names and formats."
    )
    assert sent_urls(release) == [], "refused before the release is looked up"
    assert sent_urls(download) == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("dest", "message"),
    [
        (".", f"dest is a directory; name the file to write. {NOTHING_SENT}"),
        (
            "missing/wasde1026.txt",
            f"dest's directory does not exist; create it first. {NOTHING_SENT}",
        ),
    ],
    ids=["a-directory", "a-missing-directory"],
)
def test_a_bad_dest_is_refused_before_any_request(
    replay_fixture: ReplayFixture,
    respx_mock: respx.MockRouter,
    tmp_path: Path,
    dest: str,
    message: str,
) -> None:
    replay_fixture("release_find_by_id", "796099")
    replay_fixture("download_release_file", "wasde1026_txt")
    with pytest.raises(InvalidRequestError) as caught:
        tasks.download_release_file(796099, dest=tmp_path / dest, format="txt")
    assert str(caught.value) == message
    assert caught.value.source == SOURCE
    assert respx_mock.calls.call_count == 0, "refused before the release is looked up"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
@pytest.mark.parametrize("dest", [".", "missing/wasde1026.txt"], ids=["a-directory", "a-missing"])
async def test_a_bad_dest_is_refused_as_core_refuses_it(
    respx_mock: respx.MockRouter, tmp_path: Path, dest: str
) -> None:
    """The task's refusal of a directory or a missing directory is core's ``download``'s.

    The task checks ``dest`` by core's ``check_dest`` before the release lookup, the check
    that core's ``download`` makes before it sends, so a bad ``dest`` costs no request and
    is refused in core's words, ``Nothing was sent.`` among them.
    """
    with pytest.raises(InvalidRequestError) as by_core:
        await client.download(WASDE_TXT, tmp_path / dest)
    with pytest.raises(InvalidRequestError) as by_check:
        check_dest(tmp_path / dest, source=SOURCE)
    with pytest.raises(InvalidRequestError) as by_task:
        await tasks.download_release_file_async(796099, dest=tmp_path / dest, format="txt")
    assert str(by_task.value) == str(by_core.value) == str(by_check.value)
    assert str(by_task.value).endswith(NOTHING_SENT)
    assert by_task.value.source == by_core.value.source == SOURCE
    assert respx_mock.calls.call_count == 0
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


def recorded_params(endpoint: str, case: str) -> list[str]:
    """The query parameters a recording was made with, which its replay then requires, so
    that each recorded page answers its own page alone."""
    return list(recorded_query(load_fixture(FIXTURES / endpoint / f"{case}.json")))


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
        [
            ("release_find_by_identifier", "wasde_page0"),
            ("release_find_by_identifier", "wasde_page1"),
        ],
        [f"{WASDE_RELEASES}?page=0", f"{WASDE_RELEASES}?page=1"],
        lambda payload: (
            len(payload["data"]) == 21
            and payload["meta"]["request"]
            == {"publication_identifier": "wasde", "since": "2025-01-01"}
        ),
    ),
    (
        "list_recent_releases",
        {"since": "2026-10-20", "page": 0},
        [("release_find_all", "page0")],
        [f"{ALL_RELEASES}?page=0"],
        lambda payload: (
            len(payload["data"]) == 13
            and payload["meta"]["endpoint"] == "esmis_api_release_findAll"
            and payload["meta"]["request"] == {"since": "2026-10-20", "page": 0}
            and payload["meta"]["total"] == 1542025
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
            and payload["meta"]["names"] == {"agency_acronym": WAOB}
            and [url.rsplit(".", 1)[-1] for url in payload["data"]["files"]]
            == ["pdf", "txt", "xls", "xml"]
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
    routes = [
        replay_fixture(endpoint, case, match_params=recorded_params(endpoint, case))
        for endpoint, case in fixtures
    ]
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
async def test_the_list_publications_tool_follows_its_note_to_every_row(
    respx_mock: respx.MockRouter,
) -> None:
    """``AMS`` lists 2,008 publications: the note's ``offset`` reads them all, each once."""
    whole = [row.id for row in tasks.list_publications(agency_acronym="AMS").data]
    assert len(whole) == 2008
    seen: list[str] = []
    offset = 0
    while True:
        arguments: dict[str, Any] = {"agency_acronym": "AMS", "offset": offset}
        payload = await mcp_call(server, "usda_esmis_list_publications", arguments)
        seen += [row["id"] for row in payload["data"]]
        found = re.search(r"continue with offset=(\d+)$", payload.get("note") or "")
        if found is None:
            break
        offset = int(found.group(1))
    assert seen == whole
    assert respx_mock.calls.call_count == 0, "every page from the packaged table"


@pytest.mark.anyio
async def test_the_list_publications_tool_refuses_an_unknown_acronym_as_text() -> None:
    text = await mcp_call_text(server, "usda_esmis_list_publications", {"agency_acronym": "ers"})
    assert text.startswith("error: UnknownCode: 'ers' is not an agency_acronym")
    assert "Did you mean ERS (Economic Research Service)?" in text


@pytest.mark.anyio
async def test_the_list_recent_releases_tool_walks_from_since(
    replay_fixture: ReplayFixture,
) -> None:
    first = replay_fixture("release_find_all", "page0", match_params=["page"])
    second = replay_fixture("release_find_all", "page1", match_params=["page"])
    payload = await mcp_call(server, "usda_esmis_list_recent_releases", {"since": "2026-10-24"})
    assert [release["id"] for release in payload["data"]] == ["796124"]
    assert payload["meta"]["request"] == {"since": "2026-10-24"}
    assert payload["meta"]["total"] == 1542028
    assert payload["meta"]["notes"][0].startswith("The walk ended at page 1, the first page")
    assert sent_urls(first) + sent_urls(second) == [
        f"{ALL_RELEASES}?page=0",
        f"{ALL_RELEASES}?page=1",
    ]


@pytest.mark.anyio
async def test_the_list_recent_releases_tool_refuses_past_the_bound_and_before_the_migration(
    replay_fixture: ReplayFixture,
) -> None:
    route = replay_fixture("release_find_all", "page0", match_params=["page"])
    old = await mcp_call_text(server, "usda_esmis_list_recent_releases", {"since": "2025-09-11"})
    assert old.startswith("error: InvalidRequestError: since (2025-09-11) is before 2025-09-12")
    assert "list_releases" in old
    assert sent_urls(route) == [], "the migration's bound is refused before any request"
    text = await mcp_call_text(server, "usda_esmis_list_recent_releases", {})
    assert text.startswith(
        "error: InvalidRequestError: the walk needs more than the 24 pages that one call fetches"
    )
    assert sent_urls(route) == [f"{ALL_RELEASES}?page=0"], "the bound after one request"


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


def test_the_readme_scope_names_each_operation_no_task_reads() -> None:
    """The README's ``## Scope`` names what of the OpenAPI document no caller reaches.

    Each operation that no task reads, and ``page`` of ``esmis_api_publication_findAll``,
    whose table the package ships whole, stands in a bullet of its own with its public issue
    (https://github.com/xippios/sdk-faostat/issues/58, part 2). The operations a task reads
    are the operationIds that ``tasks`` names, and the packaged table's ``endpoint``.
    """
    document = (ROOT / "docs" / "upstream" / "openapi" / "esmis_public_api.yaml").read_text(
        encoding="utf-8"
    )
    operations = set(re.findall(r"operationId:\s*(\S+)", document))
    read = {
        value
        for name, value in vars(tasks).items()
        if name.isupper() and isinstance(value, str) and value.startswith("esmis_api_")
    }
    read.add(PackagedList.load(PACKAGE, "publication").endpoint)
    unread = operations - read
    assert unread == {
        "esmis_api_agency_findByAcronym",
        "esmis_api_agency_findById",
        "esmis_api_publication_findByAgency",
        "esmis_api_publication_findById",
        "esmis_api_release_findByPubId",
    }
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "\n## Scope\n" in readme
    scope = readme.split("\n## Scope\n", 1)[1].split("\n## ", 1)[0]
    bullets = ["- " + item for item in scope.split("\n- ")[1:]]
    issue = "https://github.com/xippios/sdk-usda-esmis/issues/"
    for operation in sorted(unread):
        named = [bullet for bullet in bullets if f"`{operation}`" in bullet]
        assert len(named) == 1, operation
        assert issue in named[0], operation
    paged = [
        bullet
        for bullet in bullets
        if "`page`" in bullet and "`esmis_api_publication_findAll`" in bullet
    ]
    assert len(paged) == 1
    assert issue in paged[0]
