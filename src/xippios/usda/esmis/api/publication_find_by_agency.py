"""``GET /api/v1/publication/findByAgency/{agencyAcronym}``: one page of an agency's publications.

Operation ``esmis_api_publication_findByAgency`` of
``docs/upstream/openapi/esmis_public_api.yaml``, "Search a paginated list of publications
by agency acronym.": the path parameter ``agencyAcronym``, a string (the document's
example: ``NASS``), and the query parameter ``page``, an integer, default ``0``; the
response ``PublicationResults``, paged as ``esmis_api_publication_findAll`` is. Recorded:
``tests/fixtures/publication_find_by_agency/waob_page0.json`` (WAOB's 2 publications).
The acronym is URL-quoted with ``safe=""``.
"""

from urllib.parse import quote

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import PublicationResults

__all__ = ["publication_find_by_agency"]

OPERATION = "esmis_api_publication_findByAgency"


async def publication_find_by_agency(agency_acronym: str, page: int = 0) -> PublicationResults:
    """Call ``esmis_api_publication_findByAgency``.

    Args:
        agency_acronym: ``agencyAcronym``, an ``Agency.acronym``, e.g. ``"WAOB"``,
            ``"NASS"``.
        page: ``page``, 0-based, upstream's default ``0``, e.g. ``0``.

    Returns:
        The page's ``pager`` and its publications.
    """
    path = f"/api/v1/publication/findByAgency/{quote(agency_acronym, safe='')}"
    raw = await client.get_json(path, params={"page": page})
    return parse(PublicationResults, raw, source=SOURCE, endpoint=OPERATION)
