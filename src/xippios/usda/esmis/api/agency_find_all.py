"""``GET /api/v1/agency/findAll``: every agency ESMIS publishes for.

Operation ``esmis_api_agency_findAll`` of ``docs/upstream/openapi/esmis_public_api.yaml``,
"Returns a list of all agencies.": no parameters, the response ``AgencyResults``, a bare
JSON array of ``Agency``. Recorded: ``tests/fixtures/agency_find_all/all.json`` (9
agencies). Error answers are mapped once in ``xippios.usda.esmis._client.classify``.
"""

from xippios.core import parse

from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import Agency

__all__ = ["agency_find_all"]

OPERATION = "esmis_api_agency_findAll"


async def agency_find_all() -> list[Agency]:
    """Call ``esmis_api_agency_findAll``.

    Returns:
        Every agency, in upstream order, e.g. ``Agency(id="3", title="World Agricultural
        Outlook Board", acronym="WAOB", ...)``.
    """
    raw = await client.get_json("/api/v1/agency/findAll")
    return parse(list[Agency], raw, source=SOURCE, endpoint=OPERATION)
