"""The reference script's declaration and its fetches on core's frame, offline.

``scripts/refresh_reference.py`` declares its two tables in one ``Lists`` for
``xippios.core.refresh``, whose run, writes and provenance rows core's tests hold
(sdk-core ADR-0062). What stays here is the script's own: that it declares exactly the lists
the package ships, and that its fetches build each table as the packaged one is built, with
its note, and refuse a walk whose pages disagree. The agency fetch replays its recording; the
walk is handed pages through a replaced wrapper.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from xippios.core import Answer, PackagedList
from xippios.core.testing import ReplayFixture, load_fixture, sent_urls

from xippios.usda.esmis import api
from xippios.usda.esmis._client import BASE_URL, SOURCE, client
from xippios.usda.esmis.models import Pager, PublicationResults, PublicationRow
from xippios.usda.esmis.params import PACKAGE, PACKAGED_LISTS

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_reference.py"
FIXTURES = ROOT / "tests" / "fixtures"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_reference", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def recorded_page() -> PublicationResults:
    """Page 0 of ``publication_find_all`` as recorded on 2026-10-27, parsed."""
    body = load_fixture(FIXTURES / "publication_find_all" / "page0.json").response.content
    return PublicationResults.model_validate_json(body)


def catalog(monkeypatch: pytest.MonkeyPatch, pages: list[PublicationResults]) -> list[int]:
    """Hand the walk ``pages`` through a replaced ``api.publication_find_all``.

    Each page is an input of the test, not an answer from ESMIS: page 0 of
    ``publication_find_all`` as recorded, its pager or its results changed in memory, handed
    to the script by the replaced wrapper. The pages asked for are returned as they are
    asked.
    """
    asked: list[int] = []

    async def publication_find_all(page: int = 0) -> Answer[PublicationResults]:
        asked.append(page)
        return Answer(pages[page], datetime.now(UTC))

    monkeypatch.setattr(api, "publication_find_all", publication_find_all)
    return asked


def pager(total_results: int, *, items_per_page: int = 25) -> Pager:
    """A pager of ``total_results`` publications on pages of ``items_per_page``."""
    pages = -(-total_results // items_per_page)
    return Pager(
        current_page=0,
        items_per_page=items_per_page,
        total_pages=pages,
        total_results=total_results,
    )


def test_the_script_declares_the_lists_the_package_ships() -> None:
    lists = script.LISTS
    assert lists.package == PACKAGE
    assert [listed.name for listed in lists.lists] == list(PACKAGED_LISTS)
    assert set(lists.packaged) == {"agency", "publication"}
    assert lists.client is client
    assert lists.quota_header is None, "ESMIS reports no quota"
    assert all(listed.enum is None for listed in lists.lists), "two tables, no enum"
    assert [listed.endpoint for listed in lists.lists] == [
        "esmis_api_agency_findAll",
        "esmis_api_publication_findAll",
    ]
    assert "PAGE_SIZE =" not in SCRIPT.read_text(encoding="utf-8"), "the tasks' page size"


async def test_the_agency_fetch_builds_the_packaged_table(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("agency_find_all", "all")
    table = await script.agencies()
    packaged = PackagedList.load(PACKAGE, "agency")
    assert (table.param, table.endpoint) == ("agency", "esmis_api_agency_findAll")
    assert table.records == packaged.records, "the records of 2026-10-27, as packaged"
    assert table.note == packaged.note
    assert table.fetched.tzinfo is UTC
    assert sent_urls(route) == [f"{BASE_URL}/api/v1/agency/findAll"]


async def test_the_walk_builds_the_publication_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """Thirty publications on two pages: 25, then 5, and no request past the count."""
    page = recorded_page()
    first = page.model_copy(update={"pager": pager(30)})
    second = page.model_copy(update={"pager": pager(30), "results": page.results[:5]})
    second = second.model_copy(
        update={
            "results": [
                publication.model_copy(update={"id": f"9{publication.id}"})
                for publication in second.results
            ]
        }
    )
    asked = catalog(monkeypatch, [first, second])
    table = await script.publications()
    assert asked == [0, 1]
    assert (table.param, table.endpoint) == ("publication", "esmis_api_publication_findAll")
    assert len(table.records) == 30
    assert table.records[0] == PublicationRow.project(page.results[0]).dump_upstream()
    assert table.note is not None
    assert table.note.startswith(
        "Every page of GET /api/v1/publication/findAll walked, pages 0 to 1 (0-based, 25 a "
        "page), bounded by pager.total_pages 2, one request a page; pager.total_results 30 "
        "on every page, 30 publications with distinct ids, in upstream order."
    )
    assert script.publication_origin(table) == (
        "`esmis_api_publication_findAll`, `GET /api/v1/publication/findAll`, every page, 0 to 1"
    )


@pytest.mark.parametrize(
    ("second", "refusal"),
    [
        (
            {"pager": pager(31)},
            "page 1 counts 31 publications on 2 pages of 25, page 0 counted 30 on 2 pages of "
            "25: the catalog changed during the walk; run it again",
        ),
        (
            {"pager": pager(30, items_per_page=50)},
            "page 1 counts 30 publications on 1 pages of 50, page 0 counted 30 on 2 pages of "
            "25: the catalog changed during the walk; run it again",
        ),
        ({"pager": ()}, "page 1 answered no pager; nothing written"),
        (
            {},
            "the walk found 30 publications, 25 distinct ids, where the pager counts 30: the "
            "pages shifted; run it again",
        ),
    ],
    ids=["count-changed", "page-size-changed", "no-pager", "repeated-ids"],
)
async def test_a_walk_whose_pages_disagree_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, second: dict[str, Any], refusal: str
) -> None:
    page = recorded_page()
    first = page.model_copy(update={"pager": pager(30)})
    changed = page.model_copy(update={"pager": pager(30), "results": page.results[:5], **second})
    catalog(monkeypatch, [first, changed])
    with pytest.raises(SystemExit) as caught:
        await script.publications()
    assert str(caught.value) == refusal


async def test_a_catalog_past_the_bound_is_refused_after_its_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = recorded_page()
    huge = page.model_copy(update={"pager": pager(25 * (script.PUBLICATION_PAGES + 1))})
    asked = catalog(monkeypatch, [huge])
    with pytest.raises(SystemExit) as caught:
        await script.publications()
    assert str(caught.value) == (
        f"the catalog counts {script.PUBLICATION_PAGES + 1} pages of publications, more than "
        f"the {script.PUBLICATION_PAGES} this script walks; nothing written: check the count "
        "and raise PUBLICATION_PAGES"
    )
    assert asked == [0]
    assert SOURCE == "usda-esmis"
