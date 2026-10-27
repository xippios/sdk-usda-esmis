"""Replay tests for the endpoint wrappers (layer 1), against answers recorded 2026-10-27.

Each wrapper is called against its recorded answer and the model's shape is checked
together with the wire's quirks that README lists (string ids, arrays where the OpenAPI
document has strings, the list wrapper's extra keys, ``"pager": []``, the clamped page).
What was sent is compared through ``sent_urls(route)``, the URLs with credentials
redacted, never a request kept from ``route.calls``.
"""

import importlib
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path

import httpx
import pydantic
import pytest
from xippios.core import InvalidRequestError, NotFoundError, parse
from xippios.core.testing import ReplayFixture, load_fixture, response_from_fixture, sent_urls

from xippios.usda.esmis import api
from xippios.usda.esmis._client import BASE_URL, SOURCE, classify
from xippios.usda.esmis.models import (
    Agency,
    Pager,
    Publication,
    PublicationResults,
    Release,
    ReleaseResults,
    ResourceType,
    Status,
    Subscribable,
)

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).parents[1]
SNAPSHOT = ROOT / "docs" / "upstream" / "openapi" / "esmis_public_api.yaml"
FIXTURES = ROOT / "tests" / "fixtures"
API = f"{BASE_URL}/api/v1"
SLASHED = "Market and Trade Economics Division/FDS"

WAOB = Agency(
    id="3",
    title="World Agricultural Outlook Board",
    acronym="WAOB",
    contact_email="oce@oce.usda.gov",
    contact_phone="202-720-5447",
    location_city="Washington",
    location_state="DC",
    homepage_url="http://www.usda.gov/oce/commodity/",
)

WASDE_FILES = [
    f"{BASE_URL}/sites/default/release-files/796099/wasde1026.{kind}"
    for kind in ("pdf", "txt", "xls", "xml")
]

WASDE_RELEASE = Release(
    id="796099",
    files=WASDE_FILES,
    title="World Agricultural Supply and Demand Estimates",
    release_datetime=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
    identifier=["wasde"],
    agency_acronym="WAOB",
    bibliographic_citation="",
    description="",
    equipment_software="",
    temporal_coverage="",
)


def recorded_body(endpoint: str, case: str) -> object:
    """A recorded answer's body, decoded as upstream sent it."""
    return json.loads(load_fixture(FIXTURES / endpoint / f"{case}.json").response.content)


def recorded_url(endpoint: str, case: str) -> str:
    """The URL a fixture was recorded with."""
    return load_fixture(FIXTURES / endpoint / f"{case}.json").request.url


def operations() -> dict[str, str]:
    """The snapshot's operationIds, each with its path, in document order."""
    text = SNAPSHOT.read_text(encoding="utf-8").replace("\r\n", "\n")
    found: dict[str, str] = {}
    path = ""
    for line in text.splitlines():
        if match := re.fullmatch(r"  (/api/v1/\S+):", line):
            path = match.group(1)
        elif match := re.fullmatch(r"      operationId: (\S+)", line):
            found[match.group(1)] = path
    return found


def wrapper_name(operation_id: str) -> str:
    """``esmis_api_publication_findByIdentifier`` -> ``publication_find_by_identifier``."""
    name = operation_id.removeprefix("esmis_api_")
    return re.sub(r"(?<=[a-z])([A-Z])", r"_\1", name).lower()


def test_one_wrapper_per_operation() -> None:
    """Twelve operations in the snapshot, one module and function each, named after the
    operationId without ``esmis_api_``; each module names the full operationId and path."""
    found = operations()
    assert len(found) == 12
    assert sorted(api.__all__) == sorted(wrapper_name(op) for op in found)
    for operation_id, path in found.items():
        name = wrapper_name(operation_id)
        module = importlib.import_module(f"xippios.usda.esmis.api.{name}")
        assert operation_id == module.OPERATION
        assert getattr(api, name) is getattr(module, name)
        assert module.__doc__ is not None
        assert f"``GET {path}``" in module.__doc__
        assert f"``{operation_id}``" in module.__doc__


async def test_agency_find_all(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("agency_find_all", "all")
    agencies = await api.agency_find_all()
    assert [a.id for a in agencies] == [str(n) for n in range(1, 10)], "ids are strings"
    assert [a.acronym for a in agencies] == [
        "FAS",
        "ERS",
        "WAOB",
        "NASS",
        "AMS",
        "AMS-CT",
        "AMS-DA",
        "AMS-SC",
        "AMS-LPS",
    ]
    assert agencies[2] == WAOB
    assert agencies[0].contact_phone == "", "FAS lists no telephone number"
    assert sent_urls(route) == [f"{API}/agency/findAll"]


async def test_agency_find_by_acronym(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("agency_find_by_acronym", "waob")
    assert await api.agency_find_by_acronym("WAOB") == [WAOB], "a bare array of one"
    assert sent_urls(route) == [f"{API}/agency/findByAcronym/WAOB"]


async def test_agency_find_by_id(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("agency_find_by_id", "3")
    assert await api.agency_find_by_id(3) == [WAOB], "a bare array of one"
    assert sent_urls(route) == [f"{API}/agency/findById/3"]


async def test_publication_find_all(replay_fixture: ReplayFixture) -> None:
    """findAll's publications carry ``agency_acronym`` and no
    ``publication_agency_export_1``, every one of them, as recorded."""
    route = replay_fixture("publication_find_all", "page0")
    page = await api.publication_find_all(page=0)
    assert page.pager == Pager(
        current_page=0, items_per_page=25, total_pages=101, total_results=2522
    )
    assert len(page.results) == 25
    assert all(p.id.isdigit() for p in page.results), "ids are strings of digits"
    assert all(p.agency_acronym for p in page.results)
    assert {p.publication_agency_export_1 for p in page.results} == {None}
    assert {len(p.upcoming_releases) for p in page.results} == {0}
    dairy = next(p for p in page.results if p.id == "2425")
    assert dairy.agency == ["Agricultural Marketing Service", "Dairy Program"]
    assert dairy.agency_acronym == ["AMS", "AMS-DA"]
    assert dairy.identifier == ["MD_DA950", "AMS_1054"]
    assert sent_urls(route) == [f"{API}/publication/findAll?page=0"]


async def test_publication_find_all_past_the_last_page(replay_fixture: ReplayFixture) -> None:
    """Page 500 of 101 answers no results and ``current_page`` clamped to the last."""
    route = replay_fixture("publication_find_all", "page500")
    page = await api.publication_find_all(page=500)
    assert page.pager == Pager(
        current_page=100, items_per_page=25, total_pages=101, total_results=2522
    )
    assert page.results == []
    assert sent_urls(route) == [f"{API}/publication/findAll?page=500"]


async def test_publication_find_by_agency(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_find_by_agency", "waob_page0")
    page = await api.publication_find_by_agency("WAOB", page=0)
    assert page.pager == Pager(current_page=0, items_per_page=25, total_pages=1, total_results=2)
    assert [p.id for p in page.results] == ["1659", "1699"]
    assert {tuple(p.agency) for p in page.results} == {("World Agricultural Outlook Board",)}
    assert [p.publication_agency_export_1 for p in page.results] == [["WAOB"], ["WAOB"]]
    assert {p.agency_acronym for p in page.results} == {None}
    assert sent_urls(route) == [f"{API}/publication/findByAgency/WAOB?page=0"]


async def test_publication_find_by_id(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_find_by_id", "1659")
    page = await api.publication_find_by_id(1659)
    assert page.pager == Pager(current_page=0, items_per_page=25, total_pages=1, total_results=1)
    [wasde] = page.results
    assert wasde.id == "1659"
    assert wasde.title == "World Agricultural Supply and Demand Estimates"
    assert wasde.agency == ["World Agricultural Outlook Board"]
    assert wasde.identifier == ["wasde"]
    assert wasde.agency_acronym is None, "absent on the wire"
    assert wasde.publication_agency_export_1 == ["WAOB"]
    assert wasde.keywords == ["dairy", "grains", "soybeans", "sugars", "supply", "Livestock"]
    assert wasde.subject == [
        "Grains and Oilseeds",
        "Animals and Animal Products",
        "Crops and Crop Products",
    ]
    assert (wasde.frequency, wasde.status, wasde.subscribable, wasde.resource_type) == (
        "Monthly",
        "Active",
        "No",
        "Report",
    )
    assert wasde.status is Status.ACTIVE
    assert wasde.subscribable is Subscribable.NO
    assert wasde.resource_type is ResourceType.REPORT
    dumped = wasde.model_dump(mode="json")
    assert (dumped["status"], dumped["subscribable"], dumped["resource_type"]) == (
        "Active",
        "No",
        "Report",
    )
    assert wasde.upcoming_releases == []
    assert "&nbsp;" in wasde.description, "kept as printed"
    assert sent_urls(route) == [f"{API}/publication/findById/1659"]


async def test_publication_upcoming_releases(replay_fixture: ReplayFixture) -> None:
    """Upcoming release times print an Eastern offset, which the model keeps."""
    route = replay_fixture("publication_find_by_id", "1863")
    [hatchery] = (await api.publication_find_by_id(1863)).results
    assert hatchery.title == "Broiler Hatchery"
    raw = recorded_body("publication_find_by_id", "1863")
    printed = raw["results"][0]["upcoming_releases"]  # type: ignore[index]
    assert printed[:2] == ["2026-10-28T15:00:00-0400", "2026-11-04T15:00:00-0500"]
    assert len(hatchery.upcoming_releases) == len(printed) == 10
    edt, est = timezone(timedelta(hours=-4)), timezone(timedelta(hours=-5))
    assert hatchery.upcoming_releases[:2] == [
        datetime(2026, 10, 28, 15, 0, tzinfo=edt),
        datetime(2026, 11, 4, 15, 0, tzinfo=est),
    ]
    assert [t.utcoffset() for t in hatchery.upcoming_releases[:2]] == [
        timedelta(hours=-4),
        timedelta(hours=-5),
    ]
    assert sent_urls(route) == [f"{API}/publication/findById/1863"]


def yaml_enums(schema: str) -> dict[str, list[str]]:
    """The ``enum`` lists of one schema's properties in the snapshot, as text."""
    text = SNAPSHOT.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    start = lines.index(f"    {schema}:")
    found: dict[str, list[str]] = {}
    prop = ""
    for line in lines[start + 1 :]:
        if re.fullmatch(r"    \S.*", line):
            break
        if match := re.fullmatch(r"        (\w+):", line):
            prop = match.group(1)
        elif match := re.fullmatch(r"            - (.+)", line):
            if prop in found:
                found[prop].append(match.group(1))
        elif line == "          enum:":
            found[prop] = []
    return found


def test_publication_enumerations_follow_the_document() -> None:
    """Three of the document's four enumerations are ``StrEnum`` with exactly its values;
    ``frequency`` stays ``str``, since the wire printed a value it does not list."""
    enums = yaml_enums("Publication")
    assert sorted(enums) == ["frequency", "resource_type", "status", "subscribable"]
    typed: dict[str, type[StrEnum]] = {
        "status": Status,
        "subscribable": Subscribable,
        "resource_type": ResourceType,
    }
    for field, enum in typed.items():
        assert [member.value for member in enum] == enums[field]
        assert Publication.model_fields[field].annotation is enum
    assert Publication.model_fields["frequency"].annotation is str
    assert "" not in enums["frequency"]


async def test_publication_find_by_id_unknown(replay_fixture: ReplayFixture) -> None:
    """HTTP 404 ``{"message": ""}`` is ``NotFoundError`` through ``classify``, naming the
    method and path, never the host."""
    route = replay_fixture("publication_find_by_id", "unknown")
    assert recorded_body("publication_find_by_id", "unknown") == {"message": ""}
    with pytest.raises(NotFoundError) as info:
        await api.publication_find_by_id(99999999)
    assert str(info.value) == (
        "ESMIS has no record at GET /api/v1/publication/findById/99999999 (HTTP 404)"
    )
    assert info.value.source == SOURCE
    assert "esmis.nal.usda.gov" not in str(info.value)
    assert sent_urls(route) == [f"{API}/publication/findById/99999999"]


EMPTY_PAGER = Pager(current_page=0, items_per_page=25, total_pages=0, total_results=0)


@pytest.mark.parametrize(
    ("endpoint", "call", "path"),
    [
        ("agency_find_by_id", lambda: api.agency_find_by_id(999999999), "agency/findById"),
        ("release_find_by_id", lambda: api.release_find_by_id(999999999), "release/findById"),
        (
            "release_find_by_pub_id",
            lambda: api.release_find_by_pub_id(999999999, page=0),
            "release/findByPubId",
        ),
    ],
    ids=["agency_find_by_id", "release_find_by_id", "release_find_by_pub_id"],
)
async def test_an_unknown_id_is_not_found(
    replay_fixture: ReplayFixture,
    endpoint: str,
    call: Callable[[], Awaitable[object]],
    path: str,
) -> None:
    """Every lookup by id answers an unknown id with HTTP 404 ``{"message": ""}``, as
    recorded, the release list by publication id included."""
    route = replay_fixture(endpoint, "unknown")
    assert recorded_body(endpoint, "unknown") == {"message": ""}
    with pytest.raises(NotFoundError) as info:
        await call()
    assert str(info.value) == f"ESMIS has no record at GET /api/v1/{path}/999999999 (HTTP 404)"
    [sent] = sent_urls(route)
    assert sent.startswith(f"{API}/{path}/999999999")


async def test_an_unknown_acronym_answers_an_empty_array(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("agency_find_by_acronym", "unknown")
    assert await api.agency_find_by_acronym("NOPE") == []
    assert sent_urls(route) == [f"{API}/agency/findByAcronym/NOPE"]


async def test_an_unknown_acronym_has_no_publications(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_find_by_agency", "unknown")
    page = await api.publication_find_by_agency("NOPE", page=0)
    assert (page.pager, page.results) == (EMPTY_PAGER, [])
    assert sent_urls(route) == [f"{API}/publication/findByAgency/NOPE?page=0"]


async def test_an_unknown_identifier_has_no_releases(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_identifier", "unknown")
    page = await api.release_find_by_identifier("nope-nope", page=0)
    assert (page.pager, page.results) == (EMPTY_PAGER, [])
    assert sent_urls(route) == [f"{API}/release/findByIdentifier/nope-nope?page=0"]


def test_classify_maps_the_recorded_404() -> None:
    fixture = load_fixture(FIXTURES / "publication_find_by_id" / "unknown.json")
    assert isinstance(classify(response_from_fixture(fixture)), NotFoundError)


def test_classify_leaves_the_rest_to_core() -> None:
    """A success, the empty 200s of unknown names and a 404 outside ``/api/v1/`` fall
    through."""
    for endpoint, case in (
        ("publication_find_by_id", "1659"),
        ("publication_find_by_identifier", "unknown"),
        ("agency_find_by_acronym", "unknown"),
        ("publication_find_by_agency", "unknown"),
        ("release_find_by_identifier", "unknown"),
    ):
        fixture = load_fixture(FIXTURES / endpoint / f"{case}.json")
        assert classify(response_from_fixture(fixture)) is None
    outside = httpx.Response(404, request=httpx.Request("GET", f"{BASE_URL}/api"))
    assert classify(outside) is None
    server_error = httpx.Response(500, request=httpx.Request("GET", f"{API}/release/findAll"))
    assert classify(server_error) is None


async def test_publication_find_by_identifier(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_find_by_identifier", "wasde")
    page = await api.publication_find_by_identifier("wasde")
    by_id = parse(
        PublicationResults,
        recorded_body("publication_find_by_id", "1659"),
        source=SOURCE,
        endpoint="esmis_api_publication_findById",
    )
    assert page.results == by_id.results, "the same record as findById/1659"
    assert page.pager == by_id.pager
    assert sent_urls(route) == [f"{API}/publication/findByIdentifier/wasde"]


async def test_publication_find_by_identifier_unknown(replay_fixture: ReplayFixture) -> None:
    """An unknown identifier answers HTTP 200 with nothing: returned as such."""
    route = replay_fixture("publication_find_by_identifier", "unknown")
    page = await api.publication_find_by_identifier("xippios-no-such-identifier")
    assert page.pager == Pager(current_page=0, items_per_page=25, total_pages=0, total_results=0)
    assert page.results == []
    assert sent_urls(route) == [f"{API}/publication/findByIdentifier/xippios-no-such-identifier"]


async def test_publication_find_by_identifier_with_a_slash(replay_fixture: ReplayFixture) -> None:
    """The identifier is quoted whole, its spaces and its slash included; ESMIS's web server
    answers the encoded slash with its own HTML 404, raised as ``InvalidRequestError``."""
    route = replay_fixture("publication_find_by_identifier", "with_slash")
    sent = f"{API}/publication/findByIdentifier/Market%20and%20Trade%20Economics%20Division%2FFDS"
    with pytest.raises(InvalidRequestError) as info:
        await api.publication_find_by_identifier(SLASHED)
    assert sent_urls(route) == [sent]
    assert recorded_url("publication_find_by_identifier", "with_slash") == sent
    assert "carries '/'" in str(info.value)
    assert "esmis.nal.usda.gov" not in str(info.value)
    fixture = load_fixture(FIXTURES / "publication_find_by_identifier" / "with_slash.json")
    assert fixture.response.status == 404
    assert dict(fixture.response.headers)["content-type"].startswith("text/html")


async def test_publication_search(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_search", "wasde_page0")
    page = await api.publication_search("wasde", page=0)
    assert page.pager == Pager(current_page=0, items_per_page=25, total_pages=1, total_results=7)
    assert [p.id for p in page.results] == ["1762", "1831", "1154", "1830", "1763", "1646", "1659"]
    feed = page.results[0]
    assert feed.title == "Feed Outlook"
    assert feed.identifier == [SLASHED, "FDS"], "one with a slash, one without"
    assert {p.agency_acronym for p in page.results} == {None}
    assert all(p.publication_agency_export_1 for p in page.results)
    assert sent_urls(route) == [f"{API}/publication/search?query=wasde&page=0"]


async def test_publication_search_empty_query(replay_fixture: ReplayFixture) -> None:
    """An empty query answers ``"pager": []``: accepted as ``()``, dumped back as ``[]``,
    the wrapper's ``filters``, ``sorters`` and ``system`` dropped."""
    route = replay_fixture("publication_search", "empty_query")
    raw = recorded_body("publication_search", "empty_query")
    assert raw == {
        "filters": [],
        "pager": [],
        "results": [],
        "sorters": [],
        "system": {"page_key": "page"},
    }
    page = await api.publication_search("", page=0)
    assert page.pager == ()
    assert page.results == []
    assert page.model_dump(mode="json") == {"pager": [], "results": []}
    assert sent_urls(route) == [f"{API}/publication/search?query=&page=0"]


def test_publication_search_without_query_answers_alike() -> None:
    """The request without ``query``, which the wrapper never sends since the document
    requires it, answers what the empty query answers."""
    raw = recorded_body("publication_search", "no_query")
    assert raw == recorded_body("publication_search", "empty_query")
    page = parse(PublicationResults, raw, source=SOURCE, endpoint="esmis_api_publication_search")
    assert page.pager == ()
    assert recorded_url("publication_search", "no_query") == f"{API}/publication/search?page=0"


def test_pager_refuses_a_non_empty_list() -> None:
    with pytest.raises(pydantic.ValidationError):
        PublicationResults.model_validate({"pager": [0], "results": []})


async def test_release_find_all(replay_fixture: ReplayFixture) -> None:
    """The highest ids first; release times are not in order across publications."""
    route = replay_fixture("release_find_all", "page0")
    page = await api.release_find_all(page=0)
    assert page.pager == Pager(
        current_page=0, items_per_page=25, total_pages=61681, total_results=1542025
    )
    assert len(page.results) == 25
    ids = [int(r.id) for r in page.results]
    assert ids == sorted(ids, reverse=True)
    times = [r.release_datetime for r in page.results]
    assert times != sorted(times, reverse=True)
    assert {r.release_datetime.utcoffset() for r in page.results} == {UTC.utcoffset(None)}
    assert {r.agency_acronym for r in page.results} == {"NASS", "WAOB"}
    assert {len(r.files) for r in page.results} == {1, 3, 4}
    assert all(f.startswith(f"{BASE_URL}/") for r in page.results for f in r.files)
    assert WASDE_RELEASE in page.results
    assert sent_urls(route) == [f"{API}/release/findAll?page=0"]


async def test_release_find_by_id(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_id", "796099")
    page = await api.release_find_by_id(796099)
    assert page.pager == Pager(current_page=0, items_per_page=25, total_pages=1, total_results=1)
    assert page.results == [WASDE_RELEASE]
    [raw] = recorded_body("release_find_by_id", "796099")["results"]  # type: ignore[index]
    assert raw["release_datetime"] == "2026-10-09T12:00:00+0000", "as printed"
    assert sent_urls(route) == [f"{API}/release/findById/796099"]


async def test_release_find_by_identifier(replay_fixture: ReplayFixture) -> None:
    """A publication's releases come with the latest release time first."""
    route = replay_fixture("release_find_by_identifier", "wasde_page0")
    page = await api.release_find_by_identifier("wasde", page=0)
    assert page.pager == Pager(current_page=0, items_per_page=25, total_pages=29, total_results=703)
    assert page.results[0] == WASDE_RELEASE
    times = [r.release_datetime for r in page.results]
    assert times == sorted(times, reverse=True)
    assert {tuple(r.identifier) for r in page.results} == {("wasde",)}
    assert {len(r.files) for r in page.results} == {4}
    assert sent_urls(route) == [f"{API}/release/findByIdentifier/wasde?page=0"]


async def test_release_find_by_pub_id(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_pub_id", "1659_page0")
    page = await api.release_find_by_pub_id(1659, page=0)
    by_identifier = parse(
        ReleaseResults,
        recorded_body("release_find_by_identifier", "wasde_page0"),
        source=SOURCE,
        endpoint="esmis_api_release_findByIdentifier",
    )
    assert page == by_identifier, "the same answer as findByIdentifier/wasde"
    assert sent_urls(route) == [f"{API}/release/findByPubId/1659?page=0"]


def test_release_datetime_must_carry_a_zone() -> None:
    record = WASDE_RELEASE.model_dump(mode="json") | {"release_datetime": "2026-10-09T12:00:00"}
    with pytest.raises(pydantic.ValidationError):
        Release.model_validate(record)


def test_models_serialise_snake_case() -> None:
    assert WASDE_RELEASE.model_dump(mode="json") == {
        "id": "796099",
        "files": WASDE_FILES,
        "title": "World Agricultural Supply and Demand Estimates",
        "release_datetime": "2026-10-09T12:00:00Z",
        "identifier": ["wasde"],
        "agency_acronym": "WAOB",
        "bibliographic_citation": "",
        "description": "",
        "equipment_software": "",
        "temporal_coverage": "",
    }
    assert set(Publication.model_fields) >= {"agency_acronym", "publication_agency_export_1"}
