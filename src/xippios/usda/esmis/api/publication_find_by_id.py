"""``GET /api/v1/publication/findById/{publicationId}``: one publication by its id.

Operation ``esmis_api_publication_findById`` of
``docs/upstream/openapi/esmis_public_api.yaml``, "Search for a single publication's
metadata by its ID.": the path parameter ``publicationId``, an ``integer`` in the
document (its example: ``2179``), although ``Publication.id`` arrives as a string of
digits; the response ``PublicationResults``, a pager and one result as recorded
(``tests/fixtures/publication_find_by_id/1659.json``, WASDE). An unknown id answers HTTP
404 ``{"message": ""}`` (``unknown.json``), which ``_client.classify`` raises as
``NotFoundError``.
"""

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import PublicationResults

__all__ = ["publication_find_by_id"]

OPERATION = "esmis_api_publication_findById"


async def publication_find_by_id(publication_id: int) -> PublicationResults:
    """Call ``esmis_api_publication_findById``.

    Args:
        publication_id: ``publicationId``, the number of a ``Publication.id``, e.g.
            ``1659`` (WASDE).

    Returns:
        The ``pager`` and the publication, one result.

    Raises:
        NotFoundError: No publication has this id (HTTP 404).
    """
    raw = await client.get_json(f"/api/v1/publication/findById/{publication_id}")
    return parse(PublicationResults, raw, source=SOURCE, endpoint=OPERATION)
