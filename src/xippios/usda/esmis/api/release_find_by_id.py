"""``GET /api/v1/release/findById/{releaseId}``: one release by its id.

Operation ``esmis_api_release_findById`` of ``docs/upstream/openapi/esmis_public_api.yaml``,
"Search for a single release's metadata by its ID.": the path parameter ``releaseId``, an
``integer`` in the document (its example: ``795266``), although ``Release.id`` arrives as
a string of digits; the response ``ReleaseResults``, a pager and one result as recorded
(``tests/fixtures/release_find_by_id/796099.json``, WASDE of 2026-10-09). An unknown id
is not recorded for releases; a 404 is raised as ``NotFoundError`` by
``_client.classify``, as for publications.
"""

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import ReleaseResults

__all__ = ["release_find_by_id"]

OPERATION = "esmis_api_release_findById"


async def release_find_by_id(release_id: int) -> ReleaseResults:
    """Call ``esmis_api_release_findById``.

    Args:
        release_id: ``releaseId``, the number of a ``Release.id``, e.g. ``796099``.

    Returns:
        The ``pager`` and the release, one result.

    Raises:
        NotFoundError: Upstream answered HTTP 404.
    """
    raw = await client.get_json(f"/api/v1/release/findById/{release_id}")
    return parse(ReleaseResults, raw, source=SOURCE, endpoint=OPERATION)
