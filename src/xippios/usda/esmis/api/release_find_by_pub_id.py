"""``GET /api/v1/release/findByPubId/{publicationId}``: a publication's releases by its id.

Operation ``esmis_api_release_findByPubId`` of
``docs/upstream/openapi/esmis_public_api.yaml``, "Search a paginated list of releases by
their publication's ID.": the path parameter ``publicationId``, an ``integer`` in the
document (its example: ``2179``), and the query parameter ``page``, an integer, default
``0``; the response ``ReleaseResults``, 0-based pages of 25. Recorded:
``tests/fixtures/release_find_by_pub_id/1659_page0.json`` (703 WASDE releases, 29 pages,
the latest ``release_datetime`` first).
"""

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import ReleaseResults

__all__ = ["release_find_by_pub_id"]

OPERATION = "esmis_api_release_findByPubId"


async def release_find_by_pub_id(publication_id: int, page: int = 0) -> ReleaseResults:
    """Call ``esmis_api_release_findByPubId``.

    Args:
        publication_id: ``publicationId``, the number of a ``Publication.id``, e.g.
            ``1659`` (WASDE).
        page: ``page``, 0-based, upstream's default ``0``, e.g. ``0``.

    Returns:
        The page's ``pager`` and its releases.
    """
    path = f"/api/v1/release/findByPubId/{publication_id}"
    raw = await client.get_json(path, params={"page": page})
    return parse(ReleaseResults, raw, source=SOURCE, endpoint=OPERATION)
