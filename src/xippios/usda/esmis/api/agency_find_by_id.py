"""``GET /api/v1/agency/findById/{agencyId}``: one agency by its id.

Operation ``esmis_api_agency_findById`` of ``docs/upstream/openapi/esmis_public_api.yaml``,
"Search for a single agency's metadata by its ID.": the path parameter ``agencyId``, an
``integer`` in the document (its example: ``4``), although ``Agency.id`` arrives as a
string of digits; the response ``AgencyResults``, a bare JSON array of ``Agency``, one
record as recorded (``tests/fixtures/agency_find_by_id/3.json``).
"""

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import Agency

__all__ = ["agency_find_by_id"]

OPERATION = "esmis_api_agency_findById"


async def agency_find_by_id(agency_id: int) -> list[Agency]:
    """Call ``esmis_api_agency_findById``.

    Args:
        agency_id: ``agencyId``, the number of an ``Agency.id``, e.g. ``3`` (WAOB),
            ``4`` (NASS).

    Returns:
        The matching agencies as upstream lists them, one as recorded.
    """
    raw = await client.get_json(f"/api/v1/agency/findById/{agency_id}")
    return parse(list[Agency], raw, source=SOURCE, endpoint=OPERATION)
