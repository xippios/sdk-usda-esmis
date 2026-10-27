"""``GET /api/v1/publication/search``: one page of publications matching a keyword.

Operation ``esmis_api_publication_search`` of
``docs/upstream/openapi/esmis_public_api.yaml``, "Search a paginated list of publications
by keyword.": the query parameters ``query``, a required string (the document's example:
``crops``), and ``page``, an integer, default ``0``; the response ``PublicationResults``,
paged as ``esmis_api_publication_findAll`` is. Recorded:
``tests/fixtures/publication_search/wasde_page0.json`` (7 publications). An empty
``query`` answers HTTP 200 with ``"pager": []`` and empty ``results``
(``empty_query.json``), as the request without ``query`` does (``no_query.json``);
``PublicationResults.pager`` takes it as ``()``.
"""

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import PublicationResults

__all__ = ["publication_search"]

OPERATION = "esmis_api_publication_search"


async def publication_search(query: str, page: int = 0) -> PublicationResults:
    """Call ``esmis_api_publication_search``.

    Args:
        query: ``query``, the keyword, e.g. ``"wasde"``, ``"crops"``.
        page: ``page``, 0-based, upstream's default ``0``, e.g. ``0``.

    Returns:
        The page's ``pager`` and its publications; ``pager`` is ``()`` when ``query`` is
        empty.
    """
    params = {"query": query, "page": page}
    raw = await client.get_json("/api/v1/publication/search", params=params)
    return parse(PublicationResults, raw, source=SOURCE, endpoint=OPERATION)
