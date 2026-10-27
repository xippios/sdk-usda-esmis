"""The configured ``xippios.core`` client for USDA ESMIS.

One ``AsyncClient`` for the whole package: task functions share its rate limiter and
cache, and the same instance serves the sync facades and the MCP server.

The catalog is keyless and sends no rate-limit or quota headers, so the client keeps a
self-imposed pace and installs no ``QuotaPolicy`` (ADR-0010, ADR-0015). ``classify`` maps
the catalog's answers to an unknown id and to an identifier carrying ``/`` once
(ADR-0008); every other answer falls through to core's status mapping, so the endpoint
wrappers never inspect a status code.
"""

import httpx
from xippios.core import (
    AsyncClient,
    ClientConfig,
    InvalidRequestError,
    NotFoundError,
    RateLimit,
    XippiosError,
)

from xippios.usda.esmis._version import __version__

SOURCE = "usda-esmis"
BASE_URL = "https://esmis.nal.usda.gov"
"""The host root; every catalog path keeps its ``/api/v1/`` prefix, as the OpenAPI
document's ``paths`` name it (its one server is ``https://esmis.nal.usda.gov``)."""
API_KEY_ENV: str | None = None
# A self-imposed pace: upstream documents no limit (ADR-0010 decision 1).
RATE_LIMIT = RateLimit(per_minute=30, burst=1)

API_PREFIX = "/api/v1/"
"""The prefix of every operation in ``docs/upstream/openapi/esmis_public_api.yaml``."""


def _upstream_message(response: httpx.Response) -> str:
    """The ``message`` of the catalog's ``{"message": ...}`` error body, or ``""``.

    The 404 recorded for an unknown publication id carries ``{"message": ""}``
    (``tests/fixtures/publication_find_by_id/unknown.json``); a body that is not that
    shape gives ``""``.
    """
    try:
        payload = response.json()
    except ValueError:
        return ""
    message = payload.get("message") if isinstance(payload, dict) else None
    return message.strip() if isinstance(message, str) else ""


APACHE_NOT_FOUND = "<title>404 Not Found</title>"
"""The title of the web server's own 404 page, which the catalog's answers never carry:
the catalog answers JSON, and Drupal's HTML 404 is titled "Page not found"."""


def _sent_path(request: httpx.Request) -> str:
    """The request's path as sent, percent-escapes kept, its query left aside."""
    return request.url.raw_path.split(b"?", 1)[0].decode("ascii")


def _slash_refused(response: httpx.Response) -> bool:
    """Whether this is the web server's refusal of an encoded slash in the path.

    Both sides of the recorded answer
    (``tests/fixtures/publication_find_by_identifier/with_slash.json``): a request whose
    path carries ``%2F``, and a 404 with a ``text/html`` body, the web server's own page,
    not the catalog's JSON.
    """
    if "%2f" not in _sent_path(response.request).lower():
        return False
    if not response.headers.get("content-type", "").startswith("text/html"):
        return False
    try:
        body = response.text
    except (httpx.ResponseNotRead, UnicodeDecodeError):
        return False
    return APACHE_NOT_FOUND in body


def classify(response: httpx.Response) -> XippiosError | None:
    """The catalog's error answers as recorded, mapped once (ADR-0008).

    The OpenAPI document defines one error response, ``ServerError`` ("Internal server
    error."), which no operation references, so the recorded answers are the reference:

    - 404 for a path with an encoded slash (``%2F``), answered with the web server's own
      HTML page (``text/html``, titled ``404 Not Found``), is ``InvalidRequestError``,
      upstream's refusal of the request as given (conventions §5): ESMIS's web server
      answers it before the catalog sees it
      (``tests/fixtures/publication_find_by_identifier/with_slash.json``). A raw slash
      is no route either: probed on 2026-10-27, Drupal answered its HTML "Page not
      found", which falls under the next rule; the wrappers never send one. So an
      identifier carrying ``/`` (``"Market and Trade Economics Division/FDS"``) cannot
      be looked up; the publications recorded with one carry another without ``/``
      (``"FDS"``).
    - Any other 404 under ``/api/v1/`` is ``NotFoundError``: every lookup by id answers an
      unknown id with HTTP 404 ``{"message": ""}``, as recorded for
      ``esmis_api_agency_findById``, ``esmis_api_publication_findById``,
      ``esmis_api_release_findById`` and ``esmis_api_release_findByPubId``
      (``tests/fixtures/<wrapper>/unknown.json``). Upstream's ``message`` is quoted when
      it is not empty.

    Everything else falls through to core's status mapping, and ``None`` is returned: the
    lookups by name answer an unknown acronym or identifier with HTTP 200 and nothing
    (``esmis_api_agency_findByAcronym`` an empty array;
    ``esmis_api_publication_findByAgency``, ``esmis_api_publication_findByIdentifier``
    and ``esmis_api_release_findByIdentifier`` empty ``results``), which is not an error
    at this layer. Messages name the method and the path, never the host or the query
    (conventions §5).
    """
    request = response.request
    path = request.url.path
    if response.status_code != 404 or not path.startswith(API_PREFIX):
        return None
    if _slash_refused(response):
        return InvalidRequestError(
            f"ESMIS's web server refused {request.method} {_sent_path(request)} with HTTP "
            "404: it does not accept an encoded slash (%2F) in a path, so a value carrying "
            "'/' cannot be looked up. Pass one without '/'; a publication can also be found "
            "by another of its identifiers or by its id.",
            source=SOURCE,
        )
    message = _upstream_message(response)
    detail = f": {message}" if message else ""
    return NotFoundError(
        f"ESMIS has no record at {request.method} {path} (HTTP 404{detail})",
        source=SOURCE,
    )


config = ClientConfig(
    source=SOURCE,
    version=__version__,
    base_url=BASE_URL,
    rate_limit=RATE_LIMIT,
    classify=classify,
)

client = AsyncClient(config)

__all__ = [
    "API_KEY_ENV",
    "API_PREFIX",
    "BASE_URL",
    "RATE_LIMIT",
    "SOURCE",
    "classify",
    "client",
    "config",
]
