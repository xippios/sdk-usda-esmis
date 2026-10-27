"""``GET /api/v1/publication/findAll``: one page of every publication.

Operation ``esmis_api_publication_findAll`` of
``docs/upstream/openapi/esmis_public_api.yaml``, "Returns a paginated list of all
publications.": the query parameter ``page``, an integer, default ``0``; the response
``PublicationResults``. ``page`` is 0-based, 25 publications a page; a page past the last
answers empty ``results`` with ``pager.current_page`` clamped to the last page.
Recorded: ``tests/fixtures/publication_find_all/page0.json`` (2522 publications, 101
pages) and ``page500.json`` (clamped to page 100).
"""

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import PublicationResults

__all__ = ["publication_find_all"]

OPERATION = "esmis_api_publication_findAll"


async def publication_find_all(page: int = 0) -> PublicationResults:
    """Call ``esmis_api_publication_findAll``.

    Args:
        page: ``page``, 0-based, upstream's default ``0``, e.g. ``0``, ``100``.

    Returns:
        The page's ``pager`` and its publications.
    """
    raw = await client.get_json("/api/v1/publication/findAll", params={"page": page})
    return parse(PublicationResults, raw, source=SOURCE, endpoint=OPERATION)
