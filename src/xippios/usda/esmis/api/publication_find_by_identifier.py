"""``GET /api/v1/publication/findByIdentifier/{publicationIdentifier}``: one by identifier.

Operation ``esmis_api_publication_findByIdentifier`` of
``docs/upstream/openapi/esmis_public_api.yaml``, "Search for a single publication's
metadata by its identifier.": the path parameter ``publicationIdentifier``, a string (the
document's example: ``CropProg``); the response ``PublicationResults``. Recorded:
``tests/fixtures/publication_find_by_identifier/wasde.json`` (one result); an unknown
identifier answers HTTP 200 with empty ``results`` and ``total_results`` ``0``
(``unknown.json``), returned as such.

The identifier is URL-quoted with ``safe=""``, so a space or a slash stays inside its
path segment. ESMIS's web server refuses an encoded slash with an HTML 404
(``with_slash.json``, ``"Market and Trade Economics Division/FDS"``), which
``_client.classify`` raises as ``InvalidRequestError``, and a raw slash is no route
either (probed 2026-10-27): an identifier carrying ``/`` cannot be looked up.
"""

from urllib.parse import quote

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import PublicationResults

__all__ = ["publication_find_by_identifier"]

OPERATION = "esmis_api_publication_findByIdentifier"


async def publication_find_by_identifier(publication_identifier: str) -> PublicationResults:
    """Call ``esmis_api_publication_findByIdentifier``.

    Args:
        publication_identifier: ``publicationIdentifier``, one of a
            ``Publication.identifier``, e.g. ``"wasde"``, ``"FDS"``, ``"CropProg"``.

    Returns:
        The ``pager`` and the matching publications, one as recorded, none for an
        unknown identifier.

    Raises:
        InvalidRequestError: The identifier carries ``/``, which ESMIS refuses.
    """
    path = f"/api/v1/publication/findByIdentifier/{quote(publication_identifier, safe='')}"
    raw = await client.get_json(path)
    return parse(PublicationResults, raw, source=SOURCE, endpoint=OPERATION)
