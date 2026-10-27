"""``GET /api/v1/release/findAll``: one page of every release.

Operation ``esmis_api_release_findAll`` of ``docs/upstream/openapi/esmis_public_api.yaml``,
"Returns a paginated list of all releases.": the query parameter ``page``, an integer,
default ``0``; the response ``ReleaseResults``, 0-based pages of 25. Recorded:
``tests/fixtures/release_find_all/page0.json`` (1542025 releases, 61681 pages, the
highest ids first).
"""

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import ReleaseResults

__all__ = ["release_find_all"]

OPERATION = "esmis_api_release_findAll"


async def release_find_all(page: int = 0) -> ReleaseResults:
    """Call ``esmis_api_release_findAll``.

    Args:
        page: ``page``, 0-based, upstream's default ``0``, e.g. ``0``.

    Returns:
        The page's ``pager`` and its releases.
    """
    raw = await client.get_json("/api/v1/release/findAll", params={"page": page})
    return parse(ReleaseResults, raw, source=SOURCE, endpoint=OPERATION)
