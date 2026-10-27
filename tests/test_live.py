"""Live smoke tests: skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

One live smoke test per task, eight in all, next to the reachability check and one test
of the order the release tasks rely on; keyless, twelve requests in all, paced by the
client at 30 a minute. Each task test checks the shape of what ESMIS answers today,
never a value that changes with the next release. The download fetches the current
WASDE ``.txt`` alone (about 120 KB; the nightly budget is one small ``.txt``) into a
temporary directory, and checks the file's size, never what it says (ADR-0020). Requests:
the reachability check 1, ``list_agencies`` 1, ``search_publications`` 1 (one short
page), ``get_publication`` 1, ``list_releases`` 1 (page 0), ``get_release`` 1,
``get_latest_release`` 1, ``list_release_files`` 1, the download 3 (the latest WASDE
release, the release, the file) and the order check 1.
"""

from datetime import date
from pathlib import Path

import httpx
import pytest

from xippios.usda.esmis import api, tasks
from xippios.usda.esmis._client import BASE_URL, config

pytestmark = [pytest.mark.live, pytest.mark.anyio]

WASDE = "wasde"
OCTOBER_2026_WASDE = 796099
"""A WASDE release the catalog keeps, its id stable; its files are checked by shape and for a
``.txt`` (``test_list_release_files_live``)."""


async def test_upstream_answers() -> None:
    """The base URL answers without a server error.

    A plain request, not the package's client; any answer below 500 (a 404 at the
    root, say) shows the host is up.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": config.user_agent},
        timeout=config.timeouts.to_httpx(),
        follow_redirects=True,
    ) as http:
        response = await http.get(BASE_URL)
    assert response.status_code < 500


async def test_list_agencies_live() -> None:
    result = await tasks.list_agencies_async()
    assert result.data
    assert all(agency.acronym and agency.id.isdigit() for agency in result.data)
    assert result.meta.endpoint == "esmis_api_agency_findAll"
    assert result.meta.total is None


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
    """The order ``list_releases`` and ``get_latest_release`` rely on, observed only.

    Page 0 of a publication's releases runs latest ``release_datetime`` first; the
    order is not documented, so it is checked here, never a date or an id.
    """
    answer = await api.release_find_by_identifier(WASDE, 0)
    times = [release.release_datetime for release in answer.results]
    assert len(times) > 1
    assert times == sorted(times, reverse=True)


async def test_get_release_live() -> None:
    result = await tasks.get_release_async(OCTOBER_2026_WASDE)
    assert result.data.id == str(OCTOBER_2026_WASDE)
    assert result.data.files
    assert result.meta.vintage == str(OCTOBER_2026_WASDE)
    assert result.meta.published_at == result.data.release_datetime.replace(tzinfo=None)
    assert result.meta.published_at_naive


async def test_get_latest_release_live() -> None:
    result = await tasks.get_latest_release_async(WASDE)
    assert WASDE in result.data.identifier
    assert result.meta.vintage == result.data.id
    assert result.meta.published_at == result.data.release_datetime.replace(tzinfo=None)
    assert result.meta.published_at_naive
    assert result.data.release_datetime.date() <= date.today()


async def test_list_release_files_live() -> None:
    result = await tasks.list_release_files_async(OCTOBER_2026_WASDE)
    assert result.data
    for file in result.data:
        assert file.url.startswith(f"{BASE_URL}/")
        assert file.name.endswith(f".{file.format}")
    assert "txt" in {file.format for file in result.data}


async def test_download_release_file_live(tmp_path: Path) -> None:
    """The current WASDE ``.txt``, the nightly budget's one file, into a temporary directory."""
    latest = await tasks.get_latest_release_async(WASDE)
    dest = tmp_path / "wasde.txt"
    result = await tasks.download_release_file_async(int(latest.data.id), "txt", dest)
    assert result.data.path == dest
    assert result.data.bytes == dest.stat().st_size > 0
    assert (result.data.content_type or "").startswith("text/")
    assert result.meta.endpoint.endswith(".txt")
    assert result.meta.request["url"].endswith(f"/{result.meta.endpoint}")
    assert result.meta.vintage == latest.data.id
    assert [path.name for path in tmp_path.iterdir()] == ["wasde.txt"]
