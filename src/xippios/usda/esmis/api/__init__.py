"""Endpoint wrappers for USDA ESMIS.

Layer 1 of ADR-0001: one module per upstream operation, named after it. A wrapper
takes the parameters as upstream names them (snake_cased), calls
``xippios.usda.esmis._client.client`` and returns models from ``models.py`` that
mirror the payload. No composition and no defaults beyond upstream's own. The reference
is the snapshot in ``docs/upstream/``: ``openapi/esmis_public_api.yaml`` and its twelve
GET operations.

Modules and functions carry the document's ``operationId`` snake_cased without its
constant ``esmis_api_`` prefix, the API's namespace, which ``xippios.usda.esmis.api``
already is: ``esmis_api_publication_findByIdentifier`` is
``publication_find_by_identifier``. Each module's docstring names the full operationId
and path, and ``parse`` names the full operationId in its errors.
"""

from xippios.usda.esmis.api.agency_find_all import agency_find_all
from xippios.usda.esmis.api.agency_find_by_acronym import agency_find_by_acronym
from xippios.usda.esmis.api.agency_find_by_id import agency_find_by_id
from xippios.usda.esmis.api.publication_find_all import publication_find_all
from xippios.usda.esmis.api.publication_find_by_agency import publication_find_by_agency
from xippios.usda.esmis.api.publication_find_by_id import publication_find_by_id
from xippios.usda.esmis.api.publication_find_by_identifier import (
    publication_find_by_identifier,
)
from xippios.usda.esmis.api.publication_search import publication_search
from xippios.usda.esmis.api.release_find_all import release_find_all
from xippios.usda.esmis.api.release_find_by_id import release_find_by_id
from xippios.usda.esmis.api.release_find_by_identifier import release_find_by_identifier
from xippios.usda.esmis.api.release_find_by_pub_id import release_find_by_pub_id

__all__ = [
    "agency_find_all",
    "agency_find_by_acronym",
    "agency_find_by_id",
    "publication_find_all",
    "publication_find_by_agency",
    "publication_find_by_id",
    "publication_find_by_identifier",
    "publication_search",
    "release_find_all",
    "release_find_by_id",
    "release_find_by_identifier",
    "release_find_by_pub_id",
]
