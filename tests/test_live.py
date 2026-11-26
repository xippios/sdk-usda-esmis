"""Live smoke tests, one per task, skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

``/add-endpoint`` adds them.

Each task has a live smoke test, keyless, paced by the client at 30 requests a minute:
``list_agencies``, ``list_publications``, ``search_publications`` (one short page),
``get_publication``, ``list_releases`` (page 0), ``list_recent_releases`` (page 0, which
also checks the id order its walk relies on), ``get_release``, ``list_release_files`` and
``download_release_file``; one more test checks the order of a publication's releases that
``list_releases`` relies on. Each checks the shape of what ESMIS answers today, never a
value that changes with the next release. ``list_publications`` sends nothing: its test
compares the packaged table's size with upstream's count today, read from page 0 of
``esmis_api_publication_findAll``. The download fetches the current WASDE ``.txt`` alone,
named by ``name=`` from the latest release, row 0 of ``list_releases``'s page 0, into a
temporary directory, and checks the file's size, never what it says (sdk-core ADR-0020).

The two packaged tables are held against upstream so: the agency table by core's nightly
comparison, which fetches it through ``api.agency_find_all`` and compares it by acronym
(``LIVE_LISTS``, sdk-core ADR-0055), and the publication table, 101 pages of
``esmis_api_publication_findAll``, by the reference refresh before each release, which walks
it whole, and by the count of ``test_list_publications_live`` (``NO_LIVE_LIST``). Core's
testing plugin prints the run's requests as ``requests sent by the live run: <n>``, the count
in the log of ``live.yml``; core's response cache answers a second read of a path within its
lifetime, so the run sends fewer requests than its calls.
"""

from pathlib import Path

import pytest
from xippios.core.testing.live import *  # noqa: F403

from xippios.usda.esmis import api, tasks
from xippios.usda.esmis._client import BASE_URL
from xippios.usda.esmis.models import Pager
from xippios.usda.esmis.params import AGENCIES

pytestmark = [pytest.mark.live, pytest.mark.anyio]

LIVE_LISTS = {  # each packaged list compared, by its file reference/<name>.json
    "agency": (AGENCIES, api.agency_find_all),
}
NO_LIVE_LIST = {  # each packaged list not compared, with the reason
    "publication": (
        "A fetch walks every page of esmis_api_publication_findAll, 101 requests a night; the "
        "reference refresh before each release walks it whole, and "
        "test_list_publications_live compares its count."
    ),
}

WASDE = "wasde"
OCTOBER_2026_WASDE = 796099
"""A WASDE release the catalog keeps, its id stable; its files are checked by shape and for a
``.txt`` (``test_list_release_files_live``)."""


async def test_list_agencies_live() -> None:
    result = await tasks.list_agencies_async()
    assert result.data
    assert all(agency.acronym and agency.id.isdigit() for agency in result.data)
    assert result.meta.endpoint == "esmis_api_agency_findAll"
    assert result.meta.total is None


PUBLICATION_TOLERANCE = 25
"""How far upstream's count of publications may drift from the packaged table's: a page.

The table is a snapshot: the refresh runs once before each release, and a PR of its own
follows only when a table changed, none when neither table changed. ESMIS lists retired
publications as ``Inactive`` (489 of 2522 on 2026-10-27), so the count moves mostly by
the series it adds; a few new series between releases should not fail the nightly run,
while a page of them means agents miss enough that the refresh is due now."""


async def test_list_publications_live() -> None:
    """The packaged table's size against upstream's ``total_results`` today, within a page."""
    packaged = await tasks.list_publications_async()
    answer = await api.publication_find_all(0)
    assert isinstance(answer.payload.pager, Pager)
    total = answer.payload.pager.total_results
    assert abs(total - len(packaged.data)) <= PUBLICATION_TOLERANCE
    assert packaged.meta.endpoint == "esmis_api_publication_findAll"


async def test_search_publications_live() -> None:
    result = await tasks.search_publications_async(WASDE)
    assert any(WASDE in publication.identifier for publication in result.data)
    assert result.meta.total is not None
    assert result.meta.total >= len(result.data)


async def test_get_publication_live() -> None:
    result = await tasks.get_publication_async(WASDE)
    assert WASDE in result.data.identifier
    assert result.meta.request == {"publication_identifier": WASDE}


async def test_list_releases_live() -> None:
    result = await tasks.list_releases_async(WASDE, page=0)
    assert 0 < len(result.data) <= tasks.PAGE_SIZE
    assert all(WASDE in release.identifier for release in result.data)
    assert result.meta.total is not None
    assert result.meta.total >= len(result.data)


async def test_page_zero_of_a_publication_is_newest_first() -> None:
    """The order ``list_releases`` relies on, observed only: its row 0 is the latest release.

    Page 0 of a publication's releases runs latest ``release_datetime`` first; the
    order is not documented, so it is checked here, never a date or an id.
    """
    answer = await api.release_find_by_identifier(WASDE, 0)
    times = [release.release_datetime for release in answer.payload.results]
    assert len(times) > 1
    assert times == sorted(times, reverse=True)


async def test_list_recent_releases_live() -> None:
    """Page 0 of every release: a full page, the highest id first, as the walk relies on."""
    result = await tasks.list_recent_releases_async(page=0)
    assert len(result.data) == tasks.PAGE_SIZE
    ids = [int(release.id) for release in result.data]
    assert ids == sorted(ids, reverse=True)
    assert result.meta.endpoint == "esmis_api_release_findAll"
    assert result.meta.total is not None
    assert result.meta.total >= len(result.data)


async def test_get_release_live() -> None:
    result = await tasks.get_release_async(OCTOBER_2026_WASDE)
    assert result.data.id == str(OCTOBER_2026_WASDE)
    assert result.data.files
    assert result.meta.vintage == str(OCTOBER_2026_WASDE)
    assert result.meta.published_at == result.data.release_datetime.replace(tzinfo=None)
    assert result.meta.published_at_naive


async def test_list_release_files_live() -> None:
    result = await tasks.list_release_files_async(OCTOBER_2026_WASDE)
    assert result.data
    for file in result.data:
        assert file.url.startswith(f"{BASE_URL}/")
        assert file.name.endswith(f".{file.format}")
    assert "txt" in {file.format for file in result.data}


async def test_download_release_file_live(tmp_path: Path) -> None:
    """The current WASDE ``.txt``, the nightly budget's one file, into a temporary directory.

    The latest release is row 0 of ``list_releases``'s page 0; the file is chosen by
    ``name`` and ``format`` from its own file list, which ``Release.release_files()`` reads
    without a request.
    """
    page = await tasks.list_releases_async(WASDE, page=0)
    latest = page.data[0]
    files = latest.release_files()
    txt = next((file for file in files if file.format == "txt"), None)
    formats = sorted({file.format for file in files})
    assert txt is not None, f"the latest WASDE release has no txt file; its formats: {formats}"
    dest = tmp_path / "wasde.txt"
    result = await tasks.download_release_file_async(int(latest.id), "txt", dest, name=txt.name)
    assert result.data.path == dest
    assert result.data.bytes == dest.stat().st_size > 0
    assert (result.data.content_type or "").startswith("text/")
    assert result.meta.endpoint == txt.name
    assert result.meta.request["url"] == txt.url
    assert result.meta.request["name"] == txt.name
    assert result.meta.vintage == latest.id
    assert [path.name for path in tmp_path.iterdir()] == ["wasde.txt"]
