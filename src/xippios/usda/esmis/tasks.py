"""Task functions, the public API: the adapters serve ``__all__`` (conventions §2).

``/add-endpoint`` adds them.

The tasks are the contract of the parser packages that depend on this one: such a
package imports these tasks and ``models``, never ``api/`` or ``_client`` (sdk-core ADR-0021).

What every task follows:

- ``meta.endpoint`` is the operationId of ``docs/upstream/openapi/esmis_public_api.yaml``
  (``esmis_api_release_findById``); for the download, the file's name as upstream prints
  it (``wasde1026.txt``; sdk-core ADR-0020, amendment 2026-11-18, point c).
  ``meta.request`` holds the parameters the caller gave, none left ``None``
  (sdk-core ADR-0041); for the download, the ``release_id``, ``format`` and ``name``
  given, never ``dest``, and the chosen file's ``url``.
  ``meta.total`` is ``pager.total_results`` of the last page fetched for the three paged
  list tasks (sdk-core ADR-0034), ``None`` elsewhere.
  ``meta.retrieved_at`` is the client's time of the answer, the oldest where a task reads
  several, a walk's pages or a release and its file (sdk-core ADR-0037; conventions §4):
  the client keeps upstream's answers in core's response cache for 300 s, so a cached
  answer's time is when it was stored. ``list_publications`` carries the packaged table's
  ``fetched``. ``meta.names`` names the agency of every release and publication an answer
  holds, by the packaged agency list (sdk-core ADR-0067).
- The packaged answer: ``list_publications`` answers from ``reference/publication.json``,
  the table ``scripts/refresh_reference.py`` wrote from every page of
  ``esmis_api_publication_findAll``, and checks its ``agency_acronym`` against
  ``reference/agency.json``, both read with core's ``PackagedList``, without a request.
  Its ``meta`` is ``PackagedList.meta``'s (sdk-core ADR-0041, decision 1): ``retrieved_at`` the
  table's ``fetched``, ``endpoint`` the operationId it came from, ``vintage``,
  ``published_at`` and ``total`` empty. An acronym the agency table lacks is refused
  with core's ``UnknownCode``, an ``InvalidRequestError``, naming the closest.
- Absence, as recorded per lookup: an unknown release id answers HTTP 404, raised by
  ``_client.classify`` as ``NotFoundError``; an unknown publication identifier answers
  HTTP 200 with nothing, which the single-record task ``get_publication`` raises as
  ``NotFoundError`` (conventions §5) and the list task ``list_releases`` returns as the
  empty list with ``meta.total`` 0, as the pager says, and a note that says so. An
  identifier carrying ``/`` is refused by ESMIS's web server, raised as
  ``InvalidRequestError``; every publication but 654 has another identifier without it.
- Paging: pages are 0-based and hold 25 items. ``page`` given returns that page; omitted,
  core's ``fetch_pages`` walks them from page 0 under one bound, ``WALK_PAGES``, for
  Python and MCP alike, and refuses a walk that needs more pages, after its first request
  where upstream's count shows it (sdk-core ADR-0034, amendment 2026-11-24). The two release
  lists stop after the first page whose newest release is dated before ``since``
  (``_newest_before``), ``list_recent_releases`` more than ``ORDER_TOLERANCE`` before it;
  ``list_recent_releases`` walks only from a ``since`` on or after ``CATALOG_ORDER_SINCE``
  and refuses an older ``since`` before any request.
- A refusal before the first request says that nothing was sent, and one after a request
  says what was sent (conventions §5; sdk-core ADR-0045, amendment 2026-11-24).
- Release times: ``meta.vintage`` is the release id as printed (``"796099"``). The two
  tasks about one release (``get_release`` and ``download_release_file``) set
  ``meta.published_at`` to its ``release_datetime`` as
  printed with its ``+0000`` dropped, flagged ``published_at_naive`` (sdk-core ADR-0041): ESMIS
  prints ``+0000`` where its own calendar and the files' ``Last-Modified`` put the release
  at noon Eastern, so the time is upstream's text; no zone is attached and no time
  converted. ``Release`` keeps the value as printed; the list tasks leave
  ``meta.published_at`` empty.
- A catalog, never a parser (sdk-core ADR-0020): no task reads a released file's contents,
  and a downloaded file is never cached; ``download_release_file`` writes where the
  caller says. Core's ``load_json`` caches the text of the packaged tables per process.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from os import PathLike
from urllib.parse import quote

from xippios.core import (
    Answer,
    Downloaded,
    InvalidRequestError,
    NotFoundError,
    PackagedList,
    Result,
    ResultCap,
    ResultMeta,
    check_dest,
    fetch_pages,
    matches,
    names_codes,
    sync,
)

from xippios.usda.esmis import api
from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import (
    Agency,
    Pager,
    Publication,
    PublicationRow,
    Release,
    ReleaseFile,
)
from xippios.usda.esmis.params import AGENCIES, PACKAGE

__all__ = [
    "download_release_file",
    "get_publication",
    "get_release",
    "list_agencies",
    "list_publications",
    "list_recent_releases",
    "list_releases",
    "search_publications",
]

MCP_INSTRUCTIONS = (
    "USDA ESMIS via xippios. "
    "Tools are read-only. "
    "Where list tools (usda_esmis_list_*) exist, call them first to find valid values, "
    "then query."
)
"""The read server's instructions for agents, which core's tool set reads from this module
(conventions §8; sdk-core ADR-0063, decision 7)."""

BULK_TASKS = frozenset({"download_release_file"})
"""Tasks the adapters skip (sdk-core ADR-0040, decision 4): they write a file, which no tool
or route hands out. Written by hand, as the template renders it from v0.3.0; core's
``tool_functions``, which ``mcp.py`` and ``http.py`` serve, reads it from this module and
leaves its names out."""

# Four tools have an entry, each the family default cap, 200 rows or 64 KB, with a note
# of its own that names the tool's parameters for seeing the rest, since the default note
# names none (conventions §8, sdk-core ADR-0038). The notes carry the cap's advice, so the task
# docstrings, which are the tool descriptions, leave it out (sdk-core's handover,
# "Adopting core 0.3.0", https://github.com/xippios/sdk-core/blob/v0.4.1/docs/handover.md).
# - list_publications (decided in https://github.com/xippios/sdk-usda-esmis/pull/6) is
#   paged (sdk-core ADR-0061, decision 9): it answers from the packaged table, 2522 rows
#   fetched on 2026-10-27, so a second run costs upstream nothing, and the adapter's offset
#   reads the rest of a cut answer in further calls, the 2,008 rows of AMS among them;
#   its note names the filters beside the offset.
# - list_releases, called without page, answers a publication's releases from since on,
#   up to 24 pages of 25: its note names since, until and page.
# - search_publications, called without page, answers every match of a keyword, about
#   1.8 KB a publication as the WASDE matches average (0.6 KB on publication_find_all's
#   page 0), so 64 KB can cut a broad keyword's list after some 36; a page of 25 fits at
#   those sizes (about 45 KB): its note names page, the one parameter beside query.
# - list_recent_releases, called with since, answers every release of every publication
#   from since on, lately a page of 25 every two weeks or so; a release on
#   /release/findAll is about 0.46 KB (335 to 575 bytes on its pages 0 and 1), so 64 KB
#   cuts after some 140 rows, before the 200-row cap: its note names since, until and page.
# The three walking tools keep no paged cap: a continuation would walk upstream again once
# the cache's 300 s have passed. Every other tool keeps the default and its note:
# list_agencies answers 9 rows, and get_release one release.
MCP_CAPS: Mapping[str, ResultCap] = {
    "list_publications": ResultCap(
        note="filter with search (text of an id, an identifier or a title) or agency_acronym "
        "(as list_agencies spells it) to narrow the list",
        paged=True,
    ),
    "list_releases": ResultCap(
        note="bound the release dates with since and until (e.g. 2026-01-01), or pass page "
        "(0 for the newest 25 releases, then 1, 2, ...) to see the rest",
    ),
    "search_publications": ResultCap(
        note="pass page (0, 1, 2, ...; 25 publications a page) to see the rest",
    ),
    "list_recent_releases": ResultCap(
        note="narrow the window with since and until (e.g. 2026-10-20), or pass page (0 for "
        "the 25 newest catalogued releases, then 1, 2, ...) to see the rest",
    ),
}

PAGE_SIZE = 25
"""Items on a page of every paged operation, a size no documented parameter changes."""

WALK_PAGES = 24
"""The most pages, so the most requests, that one call of a walking task sends.

One bound for Python and MCP alike, core's form of it (sdk-core ADR-0034, amendment
2026-11-24; ADR-0061, decision 8): 600 items for at most 24 requests, 96 attempts with the
client's four each, as sdk-cashctrl's walks have it
(https://github.com/xippios/sdk-cashctrl/issues/135, part 4)."""

AGENCY_LIST = "esmis_api_agency_findAll"
SEARCH = "esmis_api_publication_search"
PUBLICATION = "esmis_api_publication_findByIdentifier"
RELEASE = "esmis_api_release_findById"
RELEASES = "esmis_api_release_findByIdentifier"
ALL_RELEASES = "esmis_api_release_findAll"

ORDER_TOLERANCE = timedelta(days=14)
"""How far release dates may stray from the order ``list_recent_releases``'s walk follows.

``esmis_api_release_findAll`` lists the highest id first, with release dates only mostly
in that order, and 14 days is the largest gap between the two on its recorded pages
(``docs/upstream/OBSERVED.md``, "``/release/findAll`` lists the highest id first"). The
walk stops after a page whose newest release is dated more than this before ``since``
(``_newest_before``)."""

CATALOG_ORDER_SINCE = date(2025, 9, 12)
"""The oldest ``since`` that ``list_recent_releases`` walks from: ESMIS's migration.

``esmis_api_release_findAll``'s id order follows the release dates only for the releases
catalogued since ESMIS's migration, whose first WASDE release, 791996, is dated 2025-09-12;
below it the ids do not follow the dates (``docs/upstream/OBSERVED.md``,
"``/release/findAll`` lists the highest id first"). Every release catalogued in the import
is taken to be dated on or before the bound, as WASDE's are. A walk from an older ``since``
would reach the imported ids, where a page of older-dated releases can sit above a newer
one and end the walk early without a sign; so such a ``since`` is refused, and
``list_releases`` (one publication's list, whose walk ends by that list's own order) or
``page`` serves the older dates (decided in
https://github.com/xippios/sdk-usda-esmis/pull/11)."""

NOTHING_SENT = "Nothing was sent."
"""The sentence after the first of each refusal before a request (conventions §5)."""

SEARCH_BY_KEYWORD = (
    "search_publications (over MCP, the tool usda_esmis_search_publications) finds "
    "identifiers by keyword"
)
"""How a refusal or a note on an unknown identifier names the task to call (conventions §8)."""

type _Page[T] = tuple[Sequence[T], int | None]
"""One page for ``fetch_pages``: its items and upstream's count of the whole list."""


def _meta(
    endpoint: str,
    retrieved: Sequence[datetime],
    request: Mapping[str, object],
    *,
    total: int | None = None,
    release: Release | None = None,
    notes: Sequence[str] = (),
) -> ResultMeta:
    """The ``meta`` of a task that asks upstream, its time the client's (sdk-core ADR-0037).

    ``retrieved_at`` is the oldest of the answers' times, each the wrapper's or the
    download's. For a task about one release, ``published_at`` is its ``release_datetime``
    as printed, ``+0000`` dropped and never converted, flagged ``published_at_naive``, and
    ``vintage`` its id as printed (sdk-core ADR-0041). ``ResultMeta`` drops a parameter of
    ``request`` left ``None``.
    """
    if release is None:
        return ResultMeta(
            source=SOURCE,
            endpoint=endpoint,
            retrieved_at=min(retrieved),
            request=dict(request),
            total=total,
            notes=list(notes),
        )
    return ResultMeta(
        source=SOURCE,
        endpoint=endpoint,
        retrieved_at=min(retrieved),
        published_at=release.release_datetime.replace(tzinfo=None),
        published_at_naive=True,
        vintage=release.id,
        request=dict(request),
        total=total,
        notes=list(notes),
    )


def _total(pager: Pager | tuple[()]) -> int | None:
    """Upstream's ``total_results``, or ``None`` where it sent ``"pager": []``."""
    return pager.total_results if isinstance(pager, Pager) else None


def _page[T](pager: Pager | tuple[()], items: list[T], number: int, sent: str) -> _Page[T]:
    """Page ``number`` as ``fetch_pages`` takes it, once its size is the walk's.

    The walk counts its offsets in pages of ``PAGE_SIZE``, so a pager that states another
    size would skip or repeat items without a sign
    (https://github.com/xippios/sdk-usda-esmis/issues/27).

    Raises:
        InvalidRequestError: The pager states another page size, a refusal from an answer
            that parses (conventions §5); it names the request that was sent, returns
            nothing and names ``page``.
    """
    if isinstance(pager, Pager) and pager.items_per_page != PAGE_SIZE:
        raise InvalidRequestError(
            f"ESMIS answered page {number} of {sent} in pages of {pager.items_per_page} "
            f"items, where the walk counts {PAGE_SIZE}: the walk would skip or repeat items, "
            "so it returns nothing; pass page to read one page as upstream pages it.",
            source=SOURCE,
        )
    return items, _total(pager)


def _check_window(since: date | None, until: date | None) -> None:
    """Refuse a ``since`` after ``until`` before any request: no release lies between them.

    Raises:
        InvalidRequestError: ``since`` is after ``until``.
    """
    if since is not None and until is not None and since > until:
        raise InvalidRequestError(
            f"since ({since}) is after until ({until}): no release can lie between them. "
            f"{NOTHING_SENT}",
            source=SOURCE,
        )


def _between(releases: Sequence[Release], since: date | None, until: date | None) -> list[Release]:
    """The releases whose printed date lies from ``since`` to ``until``, both included.

    The date is ``release_datetime``'s as printed, never converted, since upstream's
    ``+0000`` is its label and not the release's zone. Core holds no filter of dates that
    keeps its bounds' own days (``newer_than`` keeps what is strictly later), so the package
    keeps its own (https://github.com/xippios/sdk-usda-esmis/issues/35).
    """
    return [
        release
        for release in releases
        if (since is None or release.release_datetime.date() >= since)
        and (until is None or release.release_datetime.date() <= until)
    ]


def _newest_before(bound: date) -> Callable[[Sequence[Release]], bool]:
    """The stop rule of both release walks: a page whose newest release is dated before ``bound``.

    On the printed date of ``release_datetime``, never converted. ``list_releases`` passes
    ``since``, ``list_recent_releases`` ``since - ORDER_TOLERANCE``. A page's oldest date
    says little in either list: ``esmis_api_release_findAll`` lists the latest catalogued
    first with dates only mostly in that order (``docs/upstream/OBSERVED.md``,
    "``/release/findAll`` lists the highest id first"), and a publication's list holds
    older releases out of place on early pages, as WASDE's pages 3 and 4 do. Its newest
    says where the walk is: on WASDE's whole list no page holds a release dated after the
    newest of a page before it, so past the page that ends a walk of ``list_releases`` no
    page holds a release from ``since`` on ("A publication's releases come newest first
    page by page"), and a release filed on a later page with a later date would break that;
    ``ORDER_TOLERANCE`` says what findAll's recorded pages hold. An empty page is no stop:
    the walk ends there anyway.
    """

    def last(items: Sequence[Release]) -> bool:
        return bool(items) and max(item.release_datetime.date() for item in items) < bound

    return last


def _release_id(release: Release) -> str:
    """What tells two releases apart in a walk: a release that two pages list is kept once."""
    return release.id


def _publication_id(publication: Publication) -> str:
    """What tells two publications apart in a walk, as ``_release_id`` does for releases."""
    return publication.id


def _no_release(publication_identifier: str) -> str:
    """The note of ``list_releases`` where ESMIS counts no release for the identifier.

    ESMIS answers an identifier it does not know with empty ``results`` and every pager
    count 0 (``release_find_by_identifier/unknown.json``), so the empty list says why it is
    empty: a date filter that keeps no release leaves upstream's count above 0.
    """
    return (
        f"ESMIS counts no release for the identifier {publication_identifier!r}, as it answers "
        f"an identifier it does not know; {SEARCH_BY_KEYWORD}."
    )


def _path(prefix: str, value: str) -> str:
    """A catalog path with ``value`` quoted whole, as the wrappers send it, for a message."""
    return f"/api/v1/{prefix}/{quote(value, safe='')}"


def _listing(files: list[ReleaseFile]) -> str:
    """A release's files for a message, each name with its format, or ``none``."""
    return ", ".join(f"{file.name} ({file.format or 'no format'})" for file in files) or "none"


def _select(release: Release, format: str | None, name: str | None) -> ReleaseFile:
    """The file of ``release`` to download, chosen by ``name``, ``format`` or both.

    ``name`` alone is the file with that name, as ``ReleaseFile.name`` prints it;
    ``format`` alone the first file of that format in upstream order; both the named
    file, which must be of that format. A pure choice on ``Release.release_files()``,
    without a request, made once the release was read: each refusal says that the release
    was read and that no file was requested. The task refuses neither before the lookup.

    Raises:
        InvalidRequestError: ``name`` names no file of the release, naming the release's
            files; the named file is of another format; or no file is of ``format``,
            naming the release's formats.
    """
    files = release.release_files()
    read = (
        f"The release was read by GET /api/v1/release/findById/{release.id}, and no file "
        "was requested."
    )
    if name is not None:
        chosen = next((file for file in files if file.name == name), None)
        if chosen is None:
            raise InvalidRequestError(
                f"release {release.id} has no file named {name!r}; its files: "
                f"{_listing(files)}. {read}",
                source=SOURCE,
            )
        if format is not None and chosen.format != format:
            raise InvalidRequestError(
                f"release {release.id}'s file {name!r} has the format {chosen.format!r}, not "
                f"{format!r}. {read} Pass format={chosen.format!r} or leave format out.",
                source=SOURCE,
            )
        return chosen
    chosen = next((file for file in files if file.format == format), None)
    if chosen is None:
        formats = ", ".join(dict.fromkeys(file.format for file in files)) or "none"
        raise InvalidRequestError(
            f"release {release.id} has no {format!r} file; its formats: {formats}. {read}",
            source=SOURCE,
        )
    return chosen


async def _release(release_id: int) -> Answer[Release]:
    """The release ``release_id`` with its time; an unknown id is raised by ``classify``."""
    answer = await api.release_find_by_id(release_id)
    if not answer.payload.results:
        raise NotFoundError(
            f"ESMIS has no release {release_id}: GET /api/v1/release/findById/{release_id} "
            "answered no result",
            source=SOURCE,
        )
    return Answer(answer.payload.results[0], answer.retrieved_at)


async def list_agencies_async() -> Result[list[Agency]]:
    """Every agency ESMIS publishes reports for, with its acronym, contacts and homepage.

    Nine agencies as recorded on 2026-10-27, from ``"FAS"`` and ``"WAOB"`` to
    ``"AMS-LPS"``, in upstream order, from one request (``esmis_api_agency_findAll``).
    ``meta.total`` stays empty: upstream counts nothing for this list.
    """
    answer = await api.agency_find_all()
    return Result(data=answer.payload, meta=_meta(AGENCY_LIST, [answer.retrieved_at], {}))


@names_codes(agency_acronym=AGENCIES)
async def list_publications_async(
    *, search: str | None = None, agency_acronym: str | None = None
) -> Result[list[PublicationRow]]:
    """Every ESMIS publication (report series) from the packaged table, filtered by text or agency.

    Answered from the table of 2522 publications the package fetched from
    ``esmis_api_publication_findAll`` on 2026-10-27 (``reference/publication.json``),
    without a request; ``search_publications`` searches upstream live instead. A
    publication ESMIS added since is missing until the package's next refresh. Each row
    keeps a publication's ``id``, ``identifier``, ``title``, ``agency_acronym``,
    ``publication_agency_export_1``, ``frequency``, ``status`` and ``resource_type``, in
    upstream order; its ``identifier`` values are what ``get_publication`` and
    ``list_releases`` take (pass one without ``/``). ``meta.retrieved_at`` is when the
    table was fetched, and ``meta.names`` names each agency by its title. An
    ``agency_acronym`` the packaged agency table lacks raises ``InvalidRequestError`` naming
    the closest acronyms.

    Args:
        search: Keep the publications where this text occurs, ignoring case, in the id,
            one of the identifiers or the title, each on its own, e.g. ``"wheat"`` (30
            publications), ``"wasde"`` (World Agricultural Supply and Demand Estimates),
            ``"1659"`` (its id). ``None`` (the default) keeps every publication.
        agency_acronym: Keep the publications whose ``agency_acronym`` lists this
            acronym, spelled exactly as ``list_agencies`` spells it, e.g. ``"ERS"`` (121
            publications), ``"WAOB"`` (2), ``"AMS-LPS"``; one of ``"FAS"``, ``"ERS"``,
            ``"WAOB"``, ``"NASS"``, ``"AMS"``, ``"AMS-CT"``, ``"AMS-DA"``, ``"AMS-SC"``,
            ``"AMS-LPS"`` as packaged. ``None`` (the default) keeps every agency.
    """
    if agency_acronym is not None:
        AGENCIES.check(
            "agency_acronym",
            agency_acronym,
            reason="list_publications keeps the publications that list the acronym exactly, "
            "so one no agency has would select nothing.",
        )
    table = PackagedList.load(PACKAGE, "publication")
    rows = [
        row
        for row in table.parse(PublicationRow, source=SOURCE)
        if matches(search, row.id, *row.identifier, row.title)
        and (agency_acronym is None or agency_acronym in (row.agency_acronym or ()))
    ]
    meta = table.meta(SOURCE, request={"search": search, "agency_acronym": agency_acronym})
    return Result(data=rows, meta=meta)


async def search_publications_async(
    query: str, *, page: int | None = None
) -> Result[list[Publication]]:
    """Publications (report series) matching a keyword: find the identifier other tools take.

    One request per page of 25 (``esmis_api_publication_search``): ``page`` given returns
    that page; omitted, the pages are walked from page 0, at most 24 requests, 96 attempts
    with the client's retries, and a keyword whose matches fill more than 24 pages is
    refused after its first request, naming ``page``. ``"wasde"`` matches WASDE itself
    (identifier ``"wasde"``) among others. A publication's
    ``identifier`` values are what ``get_publication`` and ``list_releases`` take; pass one
    without ``/``. ``meta.total`` is upstream's count of matches. An empty or blank
    ``query`` raises ``InvalidRequestError`` before anything is sent: ESMIS requires one
    and answers an empty one with nothing.

    Args:
        query: The keyword, e.g. ``"wasde"``, ``"crops"``.
        page: A 0-based page of 25, e.g. ``0``; ``None`` (the default) walks the pages.
    """
    if not query.strip():
        raise InvalidRequestError(
            f"query must not be empty or blank. {NOTHING_SENT} ESMIS requires a keyword and "
            "answers an empty one with nothing; pass one, e.g. 'wasde'.",
            source=SOURCE,
        )
    request = {"query": query, "page": page}
    if page is not None:
        answer = await api.publication_search(query, page)
        meta = _meta(SEARCH, [answer.retrieved_at], request, total=_total(answer.payload.pager))
        return Result(data=answer.payload.results, meta=meta)
    retrieved: list[datetime] = []

    async def fetch(offset: int) -> _Page[Publication]:
        number = offset // PAGE_SIZE
        answer = await api.publication_search(query, number)
        retrieved.append(answer.retrieved_at)
        sent = "GET /api/v1/publication/search"
        return _page(answer.payload.pager, answer.payload.results, number, sent)

    publications, total = await fetch_pages(
        fetch,
        page_size=PAGE_SIZE,
        most=WALK_PAGES,
        paging="page",
        key=_publication_id,
        source=SOURCE,
    )
    return Result(data=publications, meta=_meta(SEARCH, retrieved, request, total=total))


async def get_publication_async(publication_identifier: str) -> Result[Publication]:
    """One publication (report series) by its identifier, with its upcoming release times.

    One request (``esmis_api_publication_findByIdentifier``). An identifier ESMIS does not
    know raises ``NotFoundError``; upstream answers it with an empty result. Pass an
    identifier without ``/``: ESMIS's web server refuses one with it, raised as
    ``InvalidRequestError``, and every publication but publication 654 has another without
    it (``"FDS"`` beside ``"Market and Trade Economics Division/FDS"``). An identifier that
    two publications share, as ``"AMS_1045"`` is, raises ``InvalidRequestError`` naming both
    ids. ``upcoming_releases`` print Eastern offsets as upstream gives them.

    Args:
        publication_identifier: One of a publication's ``identifier`` values, as
            ``search_publications`` lists them, e.g. ``"wasde"``, ``"FDS"``,
            ``"CropProg"``.
    """
    answer = await api.publication_find_by_identifier(publication_identifier)
    if not answer.payload.results:
        raise NotFoundError(
            f"ESMIS has no publication with the identifier {publication_identifier!r}: GET "
            f"{_path('publication/findByIdentifier', publication_identifier)} answered no "
            f"result; {SEARCH_BY_KEYWORD}",
            source=SOURCE,
        )
    if len(answer.payload.results) > 1:
        ids = [publication.id for publication in answer.payload.results]
        raise InvalidRequestError(
            f"ESMIS answered GET {_path('publication/findByIdentifier', publication_identifier)} "
            f"with {len(ids)} publications, {', '.join(ids[:-1])} and {ids[-1]}, so the "
            f"identifier names no one publication and none is returned; {SEARCH_BY_KEYWORD}, "
            "and its answer holds each publication whole.",
            source=SOURCE,
        )
    request = {"publication_identifier": publication_identifier}
    meta = _meta(PUBLICATION, [answer.retrieved_at], request)
    return Result(data=answer.payload.results[0], meta=meta)


async def list_releases_async(
    publication_identifier: str,
    *,
    since: date | None = None,
    until: date | None = None,
    page: int | None = None,
) -> Result[list[Release]]:
    """A publication's releases in ESMIS's order, each with its release time and file links.

    ``esmis_api_release_findByIdentifier``, one request per page of 25. ESMIS lists them
    newest first page by page, observed, not documented: row 0 of ``page=0`` is the latest
    release, and no page lists one dated after the newest of an earlier page, though older
    ones can sit out of place. ``page`` given returns that page; omitted, the pages are
    walked from page 0, at most 24 requests, 96 attempts with the client's retries. With
    ``since`` the walk stops after the first page whose newest release is dated before it;
    without it a publication of more than 24 pages, WASDE's 29 among them, is refused after
    its first request, naming ``page``. ``since`` and ``until`` keep the releases whose
    printed date lies between them, both included. An identifier ESMIS does not know gives
    the empty list with ``meta.total`` 0 and a note that says so. ``meta.total`` is
    upstream's count before the date filter.

    Args:
        publication_identifier: One of a publication's ``identifier`` values, e.g.
            ``"wasde"``, ``"CropProg"``; pass one without ``/``, which every publication
            but publication 654 has.
        since: The earliest release date to keep, e.g. ``2026-01-01`` (a date); without
            ``page`` the walk reads one page past the last release it keeps, and a walk
            that 24 pages do not end is refused after them, naming ``page``, as WASDE's is
            for a ``since`` before 1982-02-12. ``None`` (the default) keeps every one.
        until: The latest release date to keep, e.g. ``2026-06-30`` (a date); ``None``
            (the default) keeps every one.
        page: A 0-based page of 25, e.g. ``0`` for the newest releases; ``None`` (the
            default) walks the pages.
    """
    _check_window(since, until)
    request = {
        "publication_identifier": publication_identifier,
        "since": since,
        "until": until,
        "page": page,
    }
    if page is not None:
        answer = await api.release_find_by_identifier(publication_identifier, page)
        releases = answer.payload.results
        retrieved, total = [answer.retrieved_at], _total(answer.payload.pager)
    else:
        retrieved = []

        async def fetch(offset: int) -> _Page[Release]:
            number = offset // PAGE_SIZE
            answer = await api.release_find_by_identifier(publication_identifier, number)
            retrieved.append(answer.retrieved_at)
            sent = f"GET {_path('release/findByIdentifier', publication_identifier)}"
            return _page(answer.payload.pager, answer.payload.results, number, sent)

        releases, total = await fetch_pages(
            fetch,
            page_size=PAGE_SIZE,
            most=WALK_PAGES,
            paging="page",
            stop=None if since is None else _newest_before(since),
            key=_release_id,
            source=SOURCE,
        )
    notes = [] if total != 0 else [_no_release(publication_identifier)]
    meta = _meta(RELEASES, retrieved, request, total=total, notes=notes)
    return Result(data=_between(releases, since, until), meta=meta)


async def list_recent_releases_async(
    *,
    since: date | None = None,
    until: date | None = None,
    page: int | None = None,
) -> Result[list[Release]]:
    """What USDA released across every ESMIS publication since a date, each with its files.

    ``esmis_api_release_findAll``, one request per page of 25, latest catalogued first, an
    order observed, not documented. ``page`` given returns that page. ``since`` without
    ``page`` walks from page 0 to the first page whose newest release is dated more than 14
    days before ``since``, and ``meta.notes`` names the rule that ended the walk: at most 24
    requests, 96 attempts with the client's retries, about eleven months back, an estimate.
    A walk that needs more, and one without ``since``, is refused, naming ``page``; one
    from a ``since`` before 2025-09-12, ESMIS's migration, before any request, and
    ``list_releases`` serves one publication's older releases. ``since`` and ``until``
    keep the releases whose printed date lies between them, both included, ESMIS's test
    releases among them (identifier ``"test"``, title ``"Test DDO"``). ``meta.total`` is
    upstream's count of every release.

    Args:
        since: The earliest release date to keep, e.g. ``2026-10-20`` (a date); without
            ``page`` the walk stops by it, and it must be on or after ``2025-09-12``.
            ``None`` (the default) walks without a stop, which the bound refuses.
        until: The latest release date to keep, e.g. ``2026-10-23`` (a date); ``None``
            (the default) keeps every one up to the newest. It bounds nothing of the walk.
        page: A 0-based page of 25, e.g. ``0`` for the 25 newest catalogued releases;
            ``None`` (the default) walks the pages from page 0 down to ``since``.
    """
    _check_window(since, until)
    if page is None and since is not None and since < CATALOG_ORDER_SINCE:
        raise InvalidRequestError(
            f"since ({since}) is before {CATALOG_ORDER_SINCE}: ESMIS's catalog lists releases "
            f"in an order that follows their release dates only since {CATALOG_ORDER_SINCE}, "
            f"so a walk from an older since could stop early. {NOTHING_SENT} Use list_releases "
            "(over MCP, the tool usda_esmis_list_releases) for one publication's older "
            "releases, pass page to read older pages of the catalog, or pass a since on or "
            f"after {CATALOG_ORDER_SINCE}.",
            source=SOURCE,
        )
    request = {"since": since, "until": until, "page": page}
    if page is not None:
        answer = await api.release_find_all(page)
        meta = _meta(
            ALL_RELEASES, [answer.retrieved_at], request, total=_total(answer.payload.pager)
        )
        return Result(data=_between(answer.payload.results, since, until), meta=meta)
    retrieved: list[datetime] = []
    ended: list[int] = []
    rule = None if since is None else _newest_before(since - ORDER_TOLERANCE)

    async def fetch(offset: int) -> _Page[Release]:
        number = offset // PAGE_SIZE
        answer = await api.release_find_all(number)
        retrieved.append(answer.retrieved_at)
        return _page(
            answer.payload.pager, answer.payload.results, number, "GET /api/v1/release/findAll"
        )

    def stop(items: Sequence[Release]) -> bool:
        if rule is not None and rule(items):
            ended.append(len(retrieved) - 1)
            return True
        return False

    releases, total = await fetch_pages(
        fetch,
        page_size=PAGE_SIZE,
        most=WALK_PAGES,
        paging="page",
        stop=None if rule is None else stop,
        key=_release_id,
        source=SOURCE,
    )
    if ended:
        note = (
            f"The walk ended at page {ended[0]}, the first page whose newest release is dated "
            f"more than 14 days before since ({since}); a release catalogued on a later page "
            "is not listed, and page reads it."
        )
    else:
        note = "The walk ended at the last page of esmis_api_release_findAll."
    meta = _meta(ALL_RELEASES, retrieved, request, total=total, notes=[note])
    return Result(data=_between(releases, since, until), meta=meta)


async def get_release_async(release_id: int) -> Result[Release]:
    """One release by its id: its publication's title, release time and each file's URL.

    One request (``esmis_api_release_findById``); an id ESMIS does not know raises
    ``NotFoundError`` (HTTP 404). ``files`` holds each file's URL in upstream order, its name
    the URL's last segment (``"wasde1026.txt"``), its format the extension (``"pdf"``,
    ``"txt"``, ``"xls"``, ``"xml"``, ``"zip"``), which ``Release.release_files()`` reads in
    Python; a release can keep an original and a revised file of one format (release 95621).
    The catalog states no size, and ``download_release_file`` fetches a file in Python alone.
    ``meta.vintage`` is the release id, e.g. ``"796099"``. ``meta.published_at`` is the
    release's ``release_datetime`` as printed with its ``+0000`` dropped, flagged
    ``published_at_naive``: ESMIS's own calendar puts the release at noon Eastern while the
    API prints ``+0000``, so the time is upstream's text, never converted.

    Args:
        release_id: A ``Release.id`` as a number, e.g. ``796099`` (the WASDE of
            2026-10-09), ``95621`` (the WASDE of 2013-08-12), as ``list_releases`` and
            ``list_recent_releases`` give them.
    """
    found = await _release(release_id)
    meta = _meta(RELEASE, [found.retrieved_at], {"release_id": release_id}, release=found.payload)
    return Result(data=found.payload, meta=meta)


async def download_release_file_async(
    release_id: int,
    *,
    dest: str | PathLike[str],
    format: str | None = None,
    name: str | None = None,
) -> Result[Downloaded]:
    """Download one file of a release to the path you name, e.g. the TXT of a WASDE.

    A bulk task, Python only: neither the MCP server nor the HTTP router serves it
    (``BULK_TASKS``). ``dest`` is checked first by core's ``check_dest``: a directory, or a
    path in a directory that does not exist, raises ``InvalidRequestError`` before any
    request, and so does a call with neither ``format`` nor ``name``. Then two requests, at
    most 8 attempts with the client's retries: the release (``esmis_api_release_findById``),
    and the file chosen from its files as ``Release.release_files()`` reads them, streamed
    to ``dest`` by core's ``download``, never
    held in memory and never cached; nothing in it is read. ``name`` alone chooses the file
    with that name, ``format`` alone the first file of that format in upstream order, and
    both the named file, which must be of that format. A ``name`` the release lacks raises
    ``InvalidRequestError`` naming the release's files, a named file of another format one
    naming its format, and a ``format`` the release lacks one naming its formats, each
    after the release was read and before the file is requested; an unknown id raises
    ``NotFoundError``.
    ``meta.endpoint`` is the file's name as upstream prints it (``"wasde1026.txt"``),
    ``meta.vintage`` the release id, ``meta.request`` the release id, ``format`` and
    ``name`` as given, those left ``None`` omitted, and the file's URL, and
    ``meta.retrieved_at`` the older of the release lookup's time and the time the file was
    complete. ``meta.published_at`` is the
    release's ``release_datetime`` as printed with its ``+0000`` dropped, flagged
    ``published_at_naive``: ESMIS's own calendar puts the release at noon Eastern while
    the API prints ``+0000``, so the time is upstream's text, never converted.

    Args:
        release_id: A ``Release.id`` as a number, e.g. ``796099`` (the WASDE of
            2026-10-09), ``95621`` (the WASDE of 2013-08-12).
        dest: The file to write, in a directory that exists, e.g. ``"wasde1026.txt"`` or
            ``Path("reports") / "wasde1026.txt"``; a file there is replaced.
        format: The file's format as ``Release.release_files()`` gives it, the extension in
            lower case, e.g. ``"txt"``, ``"xls"``, ``"xml"``, ``"pdf"``, ``"zip"``: the
            first file of that format. For release 95621, ``"xml"`` takes
            ``ORIGwasde-08-12-2013.xml``, the original, listed before the revised
            ``wasde-08-12-2013.xml``. ``None`` (the default) leaves the choice to ``name``.
        name: A file's name as ``Release.release_files()`` gives it, e.g.
            ``name="wasde-08-12-2013.xml"`` for release 95621, the revised XML, which
            ``format="xml"`` alone does not reach, or ``name="wasde1026.txt"`` for
            release 796099. ``None`` (the default) chooses by ``format``.
    """
    target = check_dest(dest, source=SOURCE)
    if format is None and name is None:
        raise InvalidRequestError(
            f"name the file of release {release_id} to download: pass format, name or both. "
            f"{NOTHING_SENT} get_release answers the release's files, and "
            "Release.release_files() reads their names and formats.",
            source=SOURCE,
        )
    found = await _release(release_id)
    release = found.payload
    chosen = _select(release, format, name)
    downloaded = await client.download(chosen.url, target)
    request = {"release_id": release_id, "format": format, "name": name, "url": chosen.url}
    retrieved = [found.retrieved_at, downloaded.retrieved_at]
    meta = _meta(chosen.name, retrieved, request, release=release)
    return Result(data=downloaded, meta=meta)


download_release_file = sync(download_release_file_async)
get_publication = sync(get_publication_async)
get_release = sync(get_release_async)
list_agencies = sync(list_agencies_async)
list_publications = sync(list_publications_async)
list_recent_releases = sync(list_recent_releases_async)
list_releases = sync(list_releases_async)
search_publications = sync(search_publications_async)
