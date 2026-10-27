"""``GET /api/v1/agency/findByAcronym/{agencyAcronym}``: one agency by its acronym.

Operation ``esmis_api_agency_findByAcronym`` of
``docs/upstream/openapi/esmis_public_api.yaml``, "Search for a single agency's metadata by
its acronym.": the path parameter ``agencyAcronym``, a string (the document's example:
``NASS``); the response ``AgencyResults``, a bare JSON array of ``Agency``, one record as
recorded (``tests/fixtures/agency_find_by_acronym/waob.json``); an unknown acronym
answers HTTP 200 with an empty array (``unknown.json``), returned as such. The acronym is
URL-quoted with ``safe=""``, so a space or a slash stays inside its path segment.
"""

from urllib.parse import quote

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import Agency

__all__ = ["agency_find_by_acronym"]

OPERATION = "esmis_api_agency_findByAcronym"


async def agency_find_by_acronym(agency_acronym: str) -> list[Agency]:
    """Call ``esmis_api_agency_findByAcronym``.

    Args:
        agency_acronym: ``agencyAcronym``, an ``Agency.acronym``, e.g. ``"WAOB"``,
            ``"NASS"``.

    Returns:
        The matching agencies as upstream lists them, one as recorded, none for an
        unknown acronym.
    """
    path = f"/api/v1/agency/findByAcronym/{quote(agency_acronym, safe='')}"
    raw = await client.get_json(path)
    return parse(list[Agency], raw, source=SOURCE, endpoint=OPERATION)
