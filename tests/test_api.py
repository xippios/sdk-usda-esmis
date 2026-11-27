"""Replay tests for the endpoint wrappers (layer 1), against answers recorded 2026-10-27.

Each wrapper is called against its recorded answer and the model's shape is checked
together with the wire's quirks that README lists (string ids, arrays where the OpenAPI
document has strings, the list wrapper's extra keys, ``"pager": []``, the clamped page).
What was sent is compared through ``sent_urls(route)``, the URLs with credentials
redacted, never a request kept from ``route.calls``. Every wrapper returns core's
``Answer``, its model the ``payload``, beside the time it was retrieved. Each answer a test
builds says where it comes from and names its kind where it is built (conventions §10).
"""

import importlib
import inspect
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path

import httpx
import pydantic
import pytest
from xippios.core import Answer, InvalidRequestError, NotFoundError, parse
from xippios.core.testing import (
    ReplayFixture,
    assert_time_between,
    load_fixture,
    response_from_fixture,
    sent_urls,
)

from xippios.usda.esmis import api
from xippios.usda.esmis._client import BASE_URL, SOURCE, classify
from xippios.usda.esmis.models import (
    Agency,
    Pager,
    Publication,
    PublicationResults,
    PublicationRow,
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


def snake(name: str) -> str:
    """``publicationIdentifier`` -> ``publication_identifier``."""
    return re.sub(r"(?<=[a-z])([A-Z])", r"_\1", name).lower()


def wrapper_name(operation_id: str) -> str:
    """``esmis_api_publication_findByIdentifier`` -> ``publication_find_by_identifier``."""
    return snake(operation_id.removeprefix("esmis_api_"))


def snapshot_parameters() -> dict[str, list[dict[str, str]]]:
    """Each operationId's parameters as the snapshot declares them, ``$ref`` resolved.

    A reader of this document's layout only: ``components.parameters`` by name, then each
    path's ``parameters`` list, ``$ref`` items and inline ones (``query``), with their
    ``name``, ``in``, ``required``, schema ``type`` and ``default`` as text.
    """
    components: dict[str, dict[str, str]] = {}
    found: dict[str, list[dict[str, str]]] = {}
    declared: list[dict[str, str]] = []
    section = part = ""
    current: dict[str, str] | None = None
    field = re.compile(r"\s+(name|in|required|type|default): (\S+)")
    for line in SNAPSHOT.read_text(encoding="utf-8").splitlines():
        if match := re.fullmatch(r"(\w+):.*", line):
            section, current = match.group(1), None
        elif section == "components":
            if match := re.fullmatch(r"  (\w+):", line):
                part, current = match.group(1), None
            elif part == "parameters" and (match := re.fullmatch(r"    (\w+):", line)):
                current = components[match.group(1)] = {}
            elif part == "parameters" and current is not None and (match := field.fullmatch(line)):
                current[match.group(1)] = match.group(2)
        elif section == "paths":
            ref = re.fullmatch(r'        - \$ref: "#/components/parameters/(\w+)"', line)
            if ref:
                declared.append(components[ref.group(1)])
                current = None
            elif match := re.fullmatch(r"        - name: (\w+)", line):
                current = {"name": match.group(1)}
                declared.append(current)
            elif line == "      responses:":
                current = None
            elif match := re.fullmatch(r"      operationId: (\S+)", line):
                found[match.group(1)] = declared
                declared, current = [], None
            elif current is not None and (match := field.fullmatch(line)):
                current[match.group(1)] = match.group(2)
    return found


TYPES: dict[str, type] = {"integer": int, "string": str}


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


def test_wrapper_signatures_follow_the_document() -> None:
    """Each wrapper takes exactly its operation's parameters, snake_cased, typed as the
    document types them; a required one has no default, ``page`` upstream's ``0``."""
    found = snapshot_parameters()
    assert sorted(found) == sorted(operations())
    assert sum(len(declared) for declared in found.values()) == 15
    for operation_id, declared in found.items():
        signature = inspect.signature(getattr(api, wrapper_name(operation_id)))
        expected = {snake(parameter["name"]): parameter for parameter in declared}
        assert set(signature.parameters) == set(expected), operation_id
        for name, parameter in signature.parameters.items():
            documented = expected[name]
            kind = TYPES[documented["type"]]
            assert parameter.annotation is kind, (operation_id, name)
            if documented.get("required") == "true":
                assert parameter.default is inspect.Parameter.empty, (operation_id, name)
            else:
                assert parameter.default == kind(documented["default"]), (operation_id, name)
    assert {p["name"]: p["in"] for d in found.values() for p in d} == {
        "agencyAcronym": "path",
        "agencyId": "path",
        "page": "query",
        "publicationId": "path",
        "publicationIdentifier": "path",
        "releaseId": "path",
        "query": "query",
    }


async def test_agency_find_all(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("agency_find_all", "all")
    before = datetime.now(UTC)
    answer = await api.agency_find_all()
    after = datetime.now(UTC)
    assert isinstance(answer, Answer), "core's Answer: the model and when it was retrieved"
    assert_time_between(answer.retrieved_at, before, after)
    agencies = answer.payload
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
    assert (await api.agency_find_by_acronym("WAOB")).payload == [WAOB], "a bare array of one"
    assert sent_urls(route) == [f"{API}/agency/findByAcronym/WAOB"]


async def test_agency_find_by_id(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("agency_find_by_id", "3")
    assert (await api.agency_find_by_id(3)).payload == [WAOB], "a bare array of one"
    assert sent_urls(route) == [f"{API}/agency/findById/3"]


async def test_publication_find_all(replay_fixture: ReplayFixture) -> None:
    """findAll's publications carry ``agency_acronym`` and no
    ``publication_agency_export_1``, every one of them, as recorded."""
    route = replay_fixture("publication_find_all", "page0")
    page = (await api.publication_find_all(page=0)).payload
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
    page = (await api.publication_find_all(page=500)).payload
    assert page.pager == Pager(
        current_page=100, items_per_page=25, total_pages=101, total_results=2522
    )
    assert page.results == []
    assert sent_urls(route) == [f"{API}/publication/findAll?page=500"]


async def test_publication_find_by_agency(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_find_by_agency", "waob_page0")
    page = (await api.publication_find_by_agency("WAOB", page=0)).payload
    assert page.pager == Pager(current_page=0, items_per_page=25, total_pages=1, total_results=2)
    assert [p.id for p in page.results] == ["1659", "1699"]
    assert {tuple(p.agency) for p in page.results} == {("World Agricultural Outlook Board",)}
    assert [p.publication_agency_export_1 for p in page.results] == [["WAOB"], ["WAOB"]]
    assert {p.agency_acronym for p in page.results} == {None}
    assert sent_urls(route) == [f"{API}/publication/findByAgency/WAOB?page=0"]


async def test_publication_find_by_id(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_find_by_id", "1659")
    page = (await api.publication_find_by_id(1659)).payload
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
    [hatchery] = (await api.publication_find_by_id(1863)).payload.results
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


def yaml_enums() -> dict[tuple[str, str], list[str]]:
    """Every ``enum`` list of the snapshot, by its schema and its property, as text.

    Read line by line, so that the document's unquoted ``Yes`` and ``No``, which a YAML 1.1
    reader takes for booleans, stay the text that the wire sends. A schema is a line of four
    spaces under ``schemas:``, a property one of eight, and an ``enum:`` of ten spaces opens
    the list of its property. An ``enum`` in any other form, on an array's ``items`` or
    written inline as ``enum: [a, b]``, opens no list here and fails the test's count of the
    document's ``enum`` keys.
    """
    found: dict[tuple[str, str], list[str]] = {}
    schema = prop = ""
    listing: list[str] | None = None
    for line in SNAPSHOT.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"):
        if match := re.fullmatch(r"    (\w+):", line):
            schema, listing = match.group(1), None
        elif match := re.fullmatch(r"        (\w+):", line):
            prop, listing = match.group(1), None
        elif line == "          enum:":
            listing = found.setdefault((schema, prop), [])
        elif listing is not None and (match := re.fullmatch(r"            - (.+)", line)):
            listing.append(match.group(1))
        elif not line.startswith("           "):
            listing = None
    return found


ENUMERATIONS: dict[str, type[StrEnum] | None] = {
    "frequency": None,
    "status": Status,
    "subscribable": Subscribable,
    "resource_type": ResourceType,
}
"""Each ``enum`` of the document, on ``Publication`` alone, with the enumeration that
``models.py`` writes by hand for it, or ``None`` where the field stays ``str``: the wire
printed ``""`` for ``frequency`` on publication 1172, a value the document does not list."""


def test_the_enumerations_written_by_hand_follow_the_document() -> None:
    """Each enumeration that ``models.py`` writes by hand holds exactly the values of its
    ``enum`` in the snapshot, in the document's order, and no ``enum`` of the document is
    left unread (sdk-core ADR-0061, decision 12; conventions §10).

    A refresh of ``docs/upstream/`` that adds a value, drops one or declares an ``enum`` on
    another field or schema fails here until ``models.py`` follows it or this table names
    why a field stays ``str``.
    """
    enums = yaml_enums()
    keys = re.findall(r"\benum\b[\"']?\s*:", SNAPSHOT.read_text(encoding="utf-8"))
    assert len(keys) == len(enums), "an enum on an array's items or in flow form is unread"
    assert sorted(enums) == sorted(("Publication", field) for field in ENUMERATIONS)
    for field, enum in ENUMERATIONS.items():
        documented = enums["Publication", field]
        assert documented, field
        if enum is None:
            assert Publication.model_fields[field].annotation is str, field
            continue
        assert [member.value for member in enum] == documented, field
        assert Publication.model_fields[field].annotation is enum, field
        if field in PublicationRow.model_fields:
            assert PublicationRow.model_fields[field].annotation is enum, field
    assert "" not in enums["Publication", "frequency"]


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
    assert (await api.agency_find_by_acronym("NOPE")).payload == []
    assert sent_urls(route) == [f"{API}/agency/findByAcronym/NOPE"]


async def test_an_unknown_acronym_has_no_publications(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_find_by_agency", "unknown")
    page = (await api.publication_find_by_agency("NOPE", page=0)).payload
    assert (page.pager, page.results) == (EMPTY_PAGER, [])
    assert sent_urls(route) == [f"{API}/publication/findByAgency/NOPE?page=0"]


async def test_an_unknown_identifier_has_no_releases(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_identifier", "unknown")
    page = (await api.release_find_by_identifier("nope-nope", page=0)).payload
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
    # NOT RECORDED: a 404 outside /api/v1/ without a body, of no shape upstream sends, to
    # show that classify leaves it to core (conventions §10, kind 5).
    outside = httpx.Response(404, request=httpx.Request("GET", f"{BASE_URL}/api"))
    assert classify(outside) is None
    # NOT RECORDED: a 500 without a body, of no shape upstream sends, to show that classify
    # leaves it to core (conventions §10, kind 5).
    server_error = httpx.Response(500, request=httpx.Request("GET", f"{API}/release/findAll"))
    assert classify(server_error) is None


async def test_publication_find_by_identifier(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_find_by_identifier", "wasde")
    page = (await api.publication_find_by_identifier("wasde")).payload
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
    page = (await api.publication_find_by_identifier("xippios-no-such-identifier")).payload
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
    assert str(info.value) == (
        "ESMIS's web server refused GET /api/v1/publication/findByIdentifier/"
        "Market%20and%20Trade%20Economics%20Division%2FFDS with HTTP 404: it does not "
        "accept an encoded slash (%2F) in a path, so a value carrying '/' cannot be looked "
        "up. Pass another of the publication's identifiers, as list_publications (over MCP, "
        "the tool usda_esmis_list_publications) lists them: every publication but 654 has one "
        "without '/'."
    )
    assert "by its id" not in str(info.value), "no lookup that no task has"
    assert "esmis.nal.usda.gov" not in str(info.value)
    fixture = load_fixture(FIXTURES / "publication_find_by_identifier" / "with_slash.json")
    assert fixture.response.status == 404
    assert dict(fixture.response.headers)["content-type"].startswith("text/html")
    assert "<title>404 Not Found</title>" in fixture.response.body


def test_classify_keys_the_slash_refusal_on_both_sides() -> None:
    """The refusal needs both the encoded slash sent and the web server's HTML 404: a JSON
    404 for a path with ``%2F``, or an HTML 404 for a path without, is ``NotFoundError``."""
    fixture = load_fixture(FIXTURES / "publication_find_by_identifier" / "with_slash.json")
    refused = response_from_fixture(fixture)
    assert isinstance(classify(refused), InvalidRequestError)
    acronym = httpx.Request("GET", f"{API}/agency/findByAcronym/AMS%2FDA")
    # NOT RECORDED: the catalog's recorded 404 body of an unknown id, {"message": ""}, for a
    # path with %2F, which upstream was not seen to send (conventions §10, kind 4).
    json_404 = httpx.Response(404, json={"message": ""}, request=acronym)
    assert type(classify(json_404)) is NotFoundError
    plain = httpx.Request("GET", f"{API}/publication/findByIdentifier/FDS")
    # NOT RECORDED: the recorded HTML 404 of with_slash.json for a path without %2F, a form
    # upstream was not seen to send (conventions §10, kind 4).
    html_404 = httpx.Response(
        404,
        headers={"content-type": "text/html; charset=iso-8859-1"},
        content=fixture.response.content,
        request=plain,
    )
    assert type(classify(html_404)) is NotFoundError
    # NOT RECORDED: the recorded HTML 404 of with_slash.json for another path with %2F, which
    # ESMIS's web server answers alike for every encoded slash (conventions §10, kind 3).
    refused_acronym = httpx.Response(
        404,
        headers={"content-type": "text/html; charset=iso-8859-1"},
        content=fixture.response.content,
        request=acronym,
    )
    error = classify(refused_acronym)
    assert isinstance(error, InvalidRequestError)
    assert "GET /api/v1/agency/findByAcronym/AMS%2FDA with HTTP 404" in str(error)


async def test_publication_search(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("publication_search", "wasde_page0")
    page = (await api.publication_search("wasde", page=0)).payload
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
    page = (await api.publication_search("", page=0)).payload
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
    """A pager of ``[0]`` is an input of the test, not an answer from ESMIS."""
    with pytest.raises(pydantic.ValidationError):
        PublicationResults.model_validate({"pager": [0], "results": []})


async def test_release_find_all(replay_fixture: ReplayFixture) -> None:
    """The highest ids first; release times are not in order across publications."""
    route = replay_fixture("release_find_all", "page0")
    page = (await api.release_find_all(page=0)).payload
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
    page = (await api.release_find_by_id(796099)).payload
    assert page.pager == Pager(current_page=0, items_per_page=25, total_pages=1, total_results=1)
    assert page.results == [WASDE_RELEASE]
    [raw] = recorded_body("release_find_by_id", "796099")["results"]  # type: ignore[index]
    assert raw["release_datetime"] == "2026-10-09T12:00:00+0000", "as printed"
    assert sent_urls(route) == [f"{API}/release/findById/796099"]


async def test_release_find_by_identifier(replay_fixture: ReplayFixture) -> None:
    """Page 0 of a publication's releases comes with the latest release time first."""
    route = replay_fixture("release_find_by_identifier", "wasde_page0")
    page = (await api.release_find_by_identifier("wasde", page=0)).payload
    assert page.pager == Pager(current_page=0, items_per_page=25, total_pages=29, total_results=703)
    assert page.results[0] == WASDE_RELEASE
    times = [r.release_datetime for r in page.results]
    assert times == sorted(times, reverse=True)
    assert {tuple(r.identifier) for r in page.results} == {("wasde",)}
    assert {len(r.files) for r in page.results} == {4}
    assert sent_urls(route) == [f"{API}/release/findByIdentifier/wasde?page=0"]


async def test_release_find_by_pub_id(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("release_find_by_pub_id", "1659_page0")
    page = (await api.release_find_by_pub_id(1659, page=0)).payload
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
