"""``GET /api/v1/agency/findAll``: every agency ESMIS publishes for.

Operation ``esmis_api_agency_findAll`` of ``docs/upstream/openapi/esmis_public_api.yaml``,
"Returns a list of all agencies.": no parameters, the response ``AgencyResults``, a bare
JSON array of ``Agency``. Recorded: ``tests/fixtures/agency_find_all/all.json`` (9
agencies). Error answers are mapped once in ``xippios.usda.esmis._client.classify``.
"""

from xippios.core import Answer

from xippios.usda.esmis._client import client
from xippios.usda.esmis.models import Agency

__all__ = ["agency_find_all"]

OPERATION = "esmis_api_agency_findAll"


async def agency_find_all() -> Answer[list[Agency]]:
    """Call ``esmis_api_agency_findAll``.

    Returns:
        The ``Answer``, when it was retrieved and, as its payload, every agency, in upstream order,
        e.g. ``Agency(id="3", title="World Agricultural Outlook Board", acronym="WAOB", ...)``.
    """
    return await client.get_answer("/api/v1/agency/findAll", parse=list[Agency], endpoint=OPERATION)
