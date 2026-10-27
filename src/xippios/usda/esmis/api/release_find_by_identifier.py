"""``GET /api/v1/release/findByIdentifier/{publicationIdentifier}``: a publication's releases.

Operation ``esmis_api_release_findByIdentifier`` of
``docs/upstream/openapi/esmis_public_api.yaml``, "Search a paginated list of releases by
their publication's identifier.": the path parameter ``publicationIdentifier``, a string
(the document's example: ``CropProg``), and the query parameter ``page``, an integer,
default ``0``; the response ``ReleaseResults``, 0-based pages of 25. Recorded:
``tests/fixtures/release_find_by_identifier/wasde_page0.json`` (703 WASDE releases, 29
pages, the latest ``release_datetime`` first), the same answer as
``esmis_api_release_findByPubId`` for its publication id. An unknown identifier answers
HTTP 200 with empty ``results`` and every pager count ``0`` (``unknown.json``), returned
as such, where ``esmis_api_release_findByPubId`` answers an unknown id with a 404.

The identifier is URL-quoted with ``safe=""``. The refusal of one carrying ``/`` is
carried over from ``esmis_api_publication_findByIdentifier``, where it is recorded
(``tests/fixtures/publication_find_by_identifier/with_slash.json``); it is not recorded
here. The same web server answers both paths, so ``_client.classify`` would raise it as
``InvalidRequestError`` here too.
"""

from urllib.parse import quote

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import ReleaseResults

__all__ = ["release_find_by_identifier"]

OPERATION = "esmis_api_release_findByIdentifier"


async def release_find_by_identifier(publication_identifier: str, page: int = 0) -> ReleaseResults:
    """Call ``esmis_api_release_findByIdentifier``.

    Args:
        publication_identifier: ``publicationIdentifier``, one of a
            ``Publication.identifier``, e.g. ``"wasde"``, ``"CropProg"``.
        page: ``page``, 0-based, upstream's default ``0``, e.g. ``0``.

    Returns:
        The page's ``pager`` and its releases.

    Raises:
        InvalidRequestError: The identifier carries ``/``, which ESMIS refuses, as recorded
            for the publication lookup by identifier.
    """
    path = f"/api/v1/release/findByIdentifier/{quote(publication_identifier, safe='')}"
    raw = await client.get_json(path, params={"page": page})
    return parse(ReleaseResults, raw, source=SOURCE, endpoint=OPERATION)
