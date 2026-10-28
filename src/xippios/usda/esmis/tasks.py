"""Task functions, the public API: the adapters serve ``__all__`` (conventions §2).

``/add-endpoint`` adds them.

The tasks are the contract of the parser packages that depend on this one: such a
package imports these tasks and ``models``, never ``api/`` or ``_client`` (ADR-0021).

What every task follows:

- ``meta.endpoint`` is the operationId of ``docs/upstream/openapi/esmis_public_api.yaml``
  (``esmis_api_release_findById``); for the download, the file's name as upstream prints
  it (``wasde1026.txt``; ADR-0020, decision 5). ``meta.request`` holds the parameters the
  caller gave, none left ``None`` (ADR-0022); for the download, the ``release_id``,
  ``format`` and ``name`` given, never ``dest``, and the chosen file's ``url``.
  ``meta.total`` is ``pager.total_results`` of the last page fetched for the three paged
  list tasks (ADR-0012), ``None`` elsewhere.
  ``meta.retrieved_at`` is when the answer arrived for the tasks that ask upstream: the
  client keeps no cache; ``list_publications`` carries the packaged table's ``fetched``.
- The packaged answer: ``list_publications`` answers from ``reference/publication.json``,
  the table ``scripts/refresh_reference.py`` wrote from every page of
  ``esmis_api_publication_findAll``, and checks its ``agency_acronym`` against
  ``reference/agency.json``, both read with core's ``PackagedList``, without a request.
  Its ``meta`` is ``PackagedList.meta``'s (ADR-0022, rule 1): ``retrieved_at`` the
  table's ``fetched``, ``endpoint`` the operationId it came from, ``vintage``,
  ``published_at`` and ``total`` empty. An acronym the agency table lacks is refused
  with core's ``UnknownCode``, an ``InvalidRequestError``, naming the closest.
- Absence, as recorded per lookup: an unknown release id answers HTTP 404, raised by
  ``_client.classify`` as ``NotFoundError``; an unknown publication identifier answers
  HTTP 200 with nothing, which the single-record tasks ``get_publication`` and
  ``get_latest_release`` raise as ``NotFoundError`` (conventions §5) and the list task
  ``list_releases`` returns as the empty list with ``meta.total`` 0, as the pager says. An
  identifier carrying ``/`` is refused by ESMIS's web server, raised as
  ``InvalidRequestError``.
- Paging: pages are 0-based and hold 25 items. ``page`` given returns that page; omitted,
  ``_Pages`` walks them from page 0. ``list_recent_releases`` walks only from a ``since``
  on or after ``CATALOG_ORDER_SINCE``, under its own stop rule (``_newest_before``), and
  refuses an older ``since`` and a call with neither ``since`` nor ``page`` before any
  request: every page of ``esmis_api_release_findAll`` is some 34 hours of requests
  (ADR-0007).
- Release times: ``meta.vintage`` is the release id as printed (``"796099"``). The four
  tasks about one release (``get_release``, ``get_latest_release``, ``list_release_files``,
  ``download_release_file``) set ``meta.published_at`` to its ``release_datetime`` as
  printed with its ``+0000`` dropped, flagged ``published_at_naive`` (ADR-0022): ESMIS
  prints ``+0000`` where its own calendar and the files' ``Last-Modified`` put the release
  at noon Eastern, so the time is upstream's text; no zone is attached and no time
  converted. ``Release`` keeps the value as printed; the list tasks leave
  ``meta.published_at`` empty.
- A catalog, never a parser (ADR-0020): no task reads a released file's contents, and no
  answer from upstream is stored or cached; ``download_release_file`` writes where the
  caller says. Core's ``load_json`` caches the text of the packaged tables per process.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from os import PathLike
from pathlib import Path
from urllib.parse import quote

from xippios.core import (
    Downloaded,
    InvalidRequestError,
    NotFoundError,
    PackagedList,
    Result,
    ResultCap,
    ResultMeta,
    UnknownCode,
    closest,
    collect,
    matches,
    paginate_offset,
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

__all__ = [
    "download_release_file",
    "get_latest_release",
    "get_publication",
    "get_release",
    "list_agencies",
    "list_publications",
    "list_recent_releases",
    "list_release_files",
    "list_releases",
    "search_publications",
]

BULK_TASKS = frozenset({"download_release_file"})
"""Tasks the adapters skip (ADR-0019, decision 4): they write a file, which no tool or
route hands out. Written by hand, as the template renders it from v0.3.0; core's
``register_tasks`` (which ``build_server`` calls) and ``router_from_tasks`` read it from
this module and leave its names out, so ``mcp.py`` and ``http.py`` pass ``__all__``
whole."""

# Four tools have an entry, each the family default cap, 200 rows or 64 KB, with a note
# of its own that names the tool's parameters for seeing the rest, since the default note
# names none (conventions §8, ADR-0016). The notes carry the cap's advice, so the task
# docstrings, which are the tool descriptions, leave it out (sdk-core's handover,
# "Adopting core 0.3.0").
# - list_publications (decided by Johannes on 2026-10-27): unfiltered it answers the
#   whole packaged table, 2522 rows fetched on 2026-10-27, whose result, envelope
#   included, measured 599,402 bytes of compact JSON (UTF-8, as cap_result counts them),
#   about 150k tokens: too much for one tool result, so, as with sdk-comtrade's HS list,
#   an agent filters it with search or agency_acronym and is never served it whole;
#   Python and HTTP callers get the whole table.
# - list_releases, called without page, answers every release of a publication from
#   since on, hundreds of rows (703 for WASDE): its note names since, until and page.
# - search_publications, called without page, answers every match of a keyword, about
#   1.8 KB a publication as the WASDE matches average (0.6 KB on publication_find_all's
#   page 0), so 64 KB can cut a broad keyword's list after some 36; a page of 25 fits at
#   those sizes (about 45 KB): its note names page, the one parameter beside query.
# - list_recent_releases, called with since, answers every release of every publication
#   from since on, lately a page of 25 every two weeks or so; a release on
#   /release/findAll is about 0.46 KB (335 to 575 bytes on its pages 0 and 1), so 64 KB
#   cuts after some 140 rows, before the 200-row cap: its note names since, until and page.
# Every other tool keeps the default and its note: list_agencies answers 9 rows, and
# list_release_files at most 6 files as recorded.
MCP_CAPS: Mapping[str, ResultCap] = {
    "list_publications": ResultCap(
        note="filter with search (text of an id, an identifier or a title) or agency_acronym "
        "(as list_agencies spells it) to see the rest; Python and HTTP callers get the whole "
        "table",
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

PACKAGE = "xippios.usda.esmis"
"""The package whose ``reference/`` holds the packaged tables, for ``PackagedList.load``."""

AGENCIES = "esmis_api_agency_findAll"
SEARCH = "esmis_api_publication_search"
PUBLICATION = "esmis_api_publication_findByIdentifier"
RELEASE = "esmis_api_release_findById"
RELEASES = "esmis_api_release_findByIdentifier"
ALL_RELEASES = "esmis_api_release_findAll"

ORDER_TOLERANCE = timedelta(days=14)
"""How far release dates may stray from the order ``list_recent_releases``'s walk follows.

``esmis_api_release_findAll`` lists the highest id first; the walk stops after a page
whose newest release is dated more than this before ``since`` (``_newest_before``). The
largest gap on the operation's two recorded pages: release 796123 (``CropProd``, dated
2026-10-09) was catalogued after four releases dated 2026-10-23
(``release_find_all/page0.json``, 2026-10-27). The only other one on those pages is 9
days: 796098 (dated 2026-09-28) was catalogued after 796097 (dated 2026-10-07;
``page1.json``, 2026-10-28). No release on those two pages is dated after the newest of
the 25 catalogued after it. The order beyond them is read from the WASDE recordings
(``CATALOG_ORDER_SINCE``), not probed."""

CATALOG_ORDER_SINCE = date(2025, 9, 12)
"""The oldest ``since`` that ``list_recent_releases`` walks from: ESMIS's migration.

``esmis_api_release_findAll``'s id order follows creation only for the releases
catalogued since ESMIS's migration. WASDE's releases as recorded
(``release_find_by_identifier/wasde_page0.json`` and ``wasde_page1.json``, 2026-10-27;
``release_find_by_id/95621.json``, 2026-10-28) jump from id 96171 (dated 2025-06-12) to
791996 (dated 2025-09-12), and below the jump the dates do not follow the ids: 96165 to
96171 run May, April, March, February, August, July and June 2025, and 95511
(2022-08-12) and 95621 (2013-08-12) sit above 95482 (2025-01-10). The bound is 791996's
date, the first WASDE release of the new ids, so every release catalogued in the import
is taken to be dated on or before it, as WASDE's are (the newest, 96169, is dated
2025-08-12). A walk from an older ``since`` would reach the imported ids, where a page of
older-dated releases can sit above a newer one and end the walk early without a sign; so
such a ``since`` is refused, and ``list_releases`` (one publication, in release order)
or ``page`` serves the older dates (decided by Johannes on 2026-10-28). Read from the
WASDE recordings, not probed for other publications."""


def _request(**parameters: object) -> dict[str, object]:
    """The parameters the caller gave, those left ``None`` omitted (ADR-0022)."""
    return {name: value for name, value in parameters.items() if value is not None}


type _PageAnswer[T] = tuple[Pager | tuple[()], list[T]]


@dataclass
class _Pages[T]:
    """A walk of 0-based pages, driven by core's ``paginate_offset``.

    ``paginate_offset`` advances by a full page and ends on a short or empty one; ESMIS's
    page is ``offset // PAGE_SIZE``. Two bounds it cannot see live in ``fetch``, which
    answers an empty page without a request once one is reached: ``pager.total_pages``
    of the last answer, so a full last page costs no request past the end, and ``last``,
    a task's own end (``since``, for ``list_releases`` and ``list_recent_releases``). The
    ``current_page`` an answer echoes is never read: a page past the last echoes the last
    one's number.

    Attributes:
        fetch_page: The wrapper call for one page, answering its ``pager`` and items.
        last: Whether the page just fetched is the last one wanted; ``None`` walks on.
        pager: The ``pager`` of the last answer; ``None`` before one, or where upstream
            sent ``[]``.
        ended: Whether ``last`` said the page just fetched was the last one wanted; once
            set, ``fetch`` answers ``[]`` without a request.
    """

    fetch_page: Callable[[int], Awaitable[_PageAnswer[T]]]
    last: Callable[[list[T]], bool] | None = None
    pager: Pager | None = None
    ended: bool = False

    async def fetch(self, offset: int) -> list[T]:
        """The items of the page at ``offset``, or ``[]`` without a request past a bound."""
        page = offset // PAGE_SIZE
        if self.ended or (self.pager is not None and page >= self.pager.total_pages):
            return []
        pager, items = await self.fetch_page(page)
        self.pager = pager if isinstance(pager, Pager) else None
        self.ended = self.last is not None and self.last(items)
        return items

    async def walk(self) -> tuple[list[T], int | None]:
        """Every item, in upstream order, and ``total_results`` of the last page fetched."""
        items = await collect(paginate_offset(self.fetch, page_size=PAGE_SIZE))
        return items, None if self.pager is None else self.pager.total_results


def _total(pager: Pager | tuple[()]) -> int | None:
    """Upstream's ``total_results``, or ``None`` where it sent ``"pager": []``."""
    return pager.total_results if isinstance(pager, Pager) else None


def _newest_before(since: date) -> Callable[[list[Release]], bool]:
    """The stop rule of ``list_recent_releases``'s walk from page 0, for a ``since``.

    A page ends the walk when its newest release is dated more than ``ORDER_TOLERANCE``
    before ``since``, on the printed date of ``release_datetime``, never converted.
    ``esmis_api_release_findAll`` lists the latest catalogued first, and release dates only
    mostly follow it, so a page's oldest date says little (page 0 of 2026-10-27 ends with
    a release dated 2026-09-28 after 24 dated 2026-10-09 or later); its newest says where
    the walk is. An empty page is no stop: the walk ends there anyway.
    """
    bound = since - ORDER_TOLERANCE

    def last(items: list[Release]) -> bool:
        return bool(items) and max(item.release_datetime.date() for item in items) < bound

    return last


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
    without a request.

    Raises:
        InvalidRequestError: Neither is given, or ``name`` names no file of the release,
            each naming the release's files; the named file is of another format; or no
            file is of ``format``, naming the release's formats.
    """
    files = release.release_files()
    if name is not None:
        chosen = next((file for file in files if file.name == name), None)
        if chosen is None:
            raise InvalidRequestError(
                f"release {release.id} has no file named {name!r}; its files: {_listing(files)}",
                source=SOURCE,
            )
        if format is not None and chosen.format != format:
            raise InvalidRequestError(
                f"release {release.id}'s file {name!r} has the format {chosen.format!r}, not "
                f"{format!r}; pass format={chosen.format!r} or leave format out",
                source=SOURCE,
            )
        return chosen
    if format is None:
        raise InvalidRequestError(
            f"name the file of release {release.id} to download: pass format, name or both; "
            f"its files: {_listing(files)}",
            source=SOURCE,
        )
    chosen = next((file for file in files if file.format == format), None)
    if chosen is None:
        formats = ", ".join(dict.fromkeys(file.format for file in files)) or "none"
        raise InvalidRequestError(
            f"release {release.id} has no {format!r} file; its formats: {formats}",
            source=SOURCE,
        )
    return chosen


def _target(dest: str | PathLike[str] | None) -> Path:
    """``dest`` as a path, refused before any request when no file can be written there.

    ``None`` is refused as a missing argument; a directory, or a path whose directory
    does not exist, with core's own text (``AsyncClient.download``), as the taxonomy's
    refusal (conventions §5, ADR-0007), so a bad ``dest`` costs no request.

    Raises:
        InvalidRequestError: ``dest`` is ``None``, a directory, or in a directory that
            does not exist.
    """
    if dest is None:
        raise InvalidRequestError(
            "dest is required: name the file to write, e.g. 'wasde1026.txt'", source=SOURCE
        )
    target = Path(dest)
    if target.is_dir():
        raise InvalidRequestError("dest is a directory; name the file to write", source=SOURCE)
    if not target.parent.is_dir():
        raise InvalidRequestError("dest's directory does not exist; create it first", source=SOURCE)
    return target


def _printed(release: Release) -> datetime:
    """``release_datetime`` as printed, its ``+0000`` dropped, never converted (ADR-0022)."""
    return release.release_datetime.replace(tzinfo=None)


def _release_meta(endpoint: str, release: Release, request: dict[str, object]) -> ResultMeta:
    """``ResultMeta`` of a task about one release: its printed time, its id as printed."""
    return ResultMeta(
        source=SOURCE,
        endpoint=endpoint,
        published_at=_printed(release),
        published_at_naive=True,
        vintage=release.id,
        request=request,
    )


async def _release(release_id: int) -> Release:
    """The release ``release_id``; an unknown id is raised by ``classify`` (HTTP 404)."""
    answer = await api.release_find_by_id(release_id)
    if not answer.results:
        raise NotFoundError(
            f"ESMIS has no release {release_id}: GET /api/v1/release/findById/{release_id} "
            "answered no result",
            source=SOURCE,
        )
    return answer.results[0]


async def list_agencies_async() -> Result[list[Agency]]:
    """Every agency ESMIS publishes reports for, with its acronym, contacts and homepage.

    Nine agencies as recorded on 2026-10-27, from ``"FAS"`` and ``"WAOB"`` to
    ``"AMS-LPS"``, in upstream order, from one request (``esmis_api_agency_findAll``).
    ``meta.total`` stays empty: upstream counts nothing for this list.
    """
    agencies = await api.agency_find_all()
    return Result(data=agencies, meta=ResultMeta(source=SOURCE, endpoint=AGENCIES))


async def list_publications_async(
    search: str | None = None, agency_acronym: str | None = None
) -> Result[list[PublicationRow]]:
    """Every ESMIS publication (report series) from the packaged table, filtered by text or agency.

    Answered from the table of 2522 publications the package fetched from
    ``esmis_api_publication_findAll`` on 2026-10-27 (``reference/publication.json``),
    without a request; ``search_publications`` searches upstream live instead. A
    publication ESMIS added since is missing until the package's next refresh. Each row
    keeps a publication's ``id``, ``identifier``, ``title``, ``agency_acronym``,
    ``publication_agency_export_1``, ``frequency``, ``status`` and ``resource_type``, in
    upstream order; its ``identifier`` values are what ``get_publication``,
    ``list_releases`` and ``get_latest_release`` take (pass one without ``/``).
    ``meta.retrieved_at`` is when the table was fetched, ``meta.endpoint`` the operation it
    came from. An ``agency_acronym`` the packaged agency table lacks raises
    ``InvalidRequestError`` naming the closest acronyms.

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
        agencies = PackagedList.load(PACKAGE, "agency")
        names = {agency.acronym: agency.title for agency in agencies.parse(Agency, source=SOURCE)}
        if agency_acronym not in names:
            raise UnknownCode(
                "agency_acronym",
                agency_acronym,
                list_name="agency",
                fetched=agencies.fetched,
                closest=closest(agency_acronym, names),
                reason="list_publications keeps the publications that list the acronym "
                "exactly, so one no agency has would select nothing.",
                source=SOURCE,
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
    query: str, page: int | None = None
) -> Result[list[Publication]]:
    """Publications (report series) matching a keyword: find the identifier other tools take.

    One request per page of 25 (``esmis_api_publication_search``): ``page`` given returns
    that page, omitted every page, walked from page 0. ``"wasde"`` matched 7 publications
    on 2026-10-27, WASDE itself (identifier ``"wasde"``) among them. A publication's
    ``identifier`` values are what ``get_publication``, ``list_releases`` and
    ``get_latest_release`` take; pass one without ``/``. ``meta.total`` is upstream's count
    of matches. An empty or blank ``query`` raises ``InvalidRequestError`` before anything
    is sent: ESMIS requires one and answers an empty one with nothing.

    Args:
        query: The keyword, e.g. ``"wasde"``, ``"crops"``.
        page: A 0-based page of 25, e.g. ``0``; ``None`` (the default) returns every page.
    """
    if not query.strip():
        raise InvalidRequestError(
            "query must not be empty or blank: ESMIS requires a keyword and answers an "
            "empty one with nothing; pass one, e.g. 'wasde'",
            source=SOURCE,
        )
    request = _request(query=query, page=page)
    if page is not None:
        answer = await api.publication_search(query, page)
        meta = ResultMeta(
            source=SOURCE, endpoint=SEARCH, request=request, total=_total(answer.pager)
        )
        return Result(data=answer.results, meta=meta)

    async def fetch_page(number: int) -> _PageAnswer[Publication]:
        answer = await api.publication_search(query, number)
        return answer.pager, answer.results

    publications, total = await _Pages(fetch_page).walk()
    meta = ResultMeta(source=SOURCE, endpoint=SEARCH, request=request, total=total)
    return Result(data=publications, meta=meta)


async def get_publication_async(publication_identifier: str) -> Result[Publication]:
    """One publication (report series) by its identifier, with its upcoming release times.

    One request (``esmis_api_publication_findByIdentifier``). An identifier ESMIS does not
    know raises ``NotFoundError``; upstream answers it with an empty result. Pass an
    identifier without ``/``: ESMIS's web server refuses one with it, raised as
    ``InvalidRequestError``, and every publication recorded with such an identifier has
    another without it (``"Market and Trade Economics Division/FDS"`` and ``"FDS"``).
    ``upcoming_releases`` print Eastern offsets as upstream gives them.

    Args:
        publication_identifier: One of a publication's ``identifier`` values, as
            ``search_publications`` lists them, e.g. ``"wasde"``, ``"FDS"``,
            ``"CropProg"``.
    """
    answer = await api.publication_find_by_identifier(publication_identifier)
    if not answer.results:
        raise NotFoundError(
            f"ESMIS has no publication with the identifier {publication_identifier!r}: GET "
            f"{_path('publication/findByIdentifier', publication_identifier)} answered no "
            "result; search_publications finds identifiers by keyword",
            source=SOURCE,
        )
    meta = ResultMeta(
        source=SOURCE,
        endpoint=PUBLICATION,
        request=_request(publication_identifier=publication_identifier),
    )
    return Result(data=answer.results[0], meta=meta)


async def list_releases_async(
    publication_identifier: str,
    since: date | None = None,
    until: date | None = None,
    page: int | None = None,
) -> Result[list[Release]]:
    """A publication's releases, newest first, each with its release time and file links.

    ``esmis_api_release_findByIdentifier``, one request per page of 25. ESMIS lists a
    publication's releases newest first by ``release_datetime``, an order observed on
    2026-10-27, not documented. ``page`` given returns that page; omitted, the pages are
    walked from page 0 and the walk stops after the first page whose oldest release is
    dated before ``since``, or at the last page. ``since`` and ``until`` keep the releases
    whose ``release_datetime`` date, as printed, lies between them, both included.
    Without ``page`` or ``since`` every page is fetched (29 requests for WASDE's 703
    releases, paced at 30 a minute): pass ``since``, which ends the walk, or ``page`` to
    send fewer. An identifier ESMIS does not know gives the empty list with
    ``meta.total`` 0. ``meta.total`` is upstream's count of the publication's releases
    before the date filter, so it can exceed the rows returned. ``meta.vintage`` and
    ``meta.published_at`` stay empty: each release has its own (``get_release``).

    Args:
        publication_identifier: One of a publication's ``identifier`` values, e.g.
            ``"wasde"``, ``"CropProg"``; pass one without ``/``.
        since: The earliest release date to keep, e.g. ``2026-01-01`` (a date); ``None``
            (the default) keeps every one.
        until: The latest release date to keep, e.g. ``2026-06-30`` (a date); ``None``
            (the default) keeps every one.
        page: A 0-based page of 25, e.g. ``0`` for the newest releases; ``None`` (the
            default) walks the pages.
    """
    if since is not None and until is not None and since > until:
        raise InvalidRequestError(
            f"since ({since}) is after until ({until}): no release can lie between them",
            source=SOURCE,
        )
    request = _request(
        publication_identifier=publication_identifier, since=since, until=until, page=page
    )

    def kept(release: Release) -> bool:
        day = release.release_datetime.date()  # the printed date, never converted
        return (since is None or day >= since) and (until is None or day <= until)

    if page is not None:
        answer = await api.release_find_by_identifier(publication_identifier, page)
        releases, total = answer.results, _total(answer.pager)
    else:

        async def fetch_page(number: int) -> _PageAnswer[Release]:
            answer = await api.release_find_by_identifier(publication_identifier, number)
            return answer.pager, answer.results

        def older_than_since(items: list[Release]) -> bool:
            return (
                since is not None
                and bool(items)
                and min(item.release_datetime.date() for item in items) < since
            )

        releases, total = await _Pages(fetch_page, older_than_since).walk()
    meta = ResultMeta(source=SOURCE, endpoint=RELEASES, request=request, total=total)
    return Result(data=[release for release in releases if kept(release)], meta=meta)


async def list_recent_releases_async(
    since: date | None = None,
    until: date | None = None,
    page: int | None = None,
) -> Result[list[Release]]:
    """What USDA released across every ESMIS publication since a date, each with its files.

    ``esmis_api_release_findAll``, one request per page of 25: the releases of every
    publication, latest catalogued first (the highest id), an order observed on
    2026-10-27, not documented. Release dates only mostly follow it: a release can be
    catalogued days after its release time and sit among newer ones (page 0 of 2026-10-27
    runs 2026-10-26, 2026-10-09, 2026-10-23). ``page`` given returns that page, which
    ``since`` and ``until`` only filter, whatever their dates. ``since`` given without
    ``page`` walks the pages from page 0 and stops after the first page whose newest
    release is dated more than 14 days before ``since``: 14 days is the largest gap on
    the operation's two recorded pages, release 796123, dated 2026-10-09, catalogued after
    four dated 2026-10-23. The walk misses a release catalogued more than 14 days before
    its release time, and one catalogued before a page of older-dated releases; ``page``
    reaches them. The ids follow creation only since ESMIS's migration, whose first WASDE
    release is dated 2025-09-12; below it the dates do not follow the ids, so a walk from
    a ``since`` before 2025-09-12 raises ``InvalidRequestError`` before any request:
    ``list_releases`` lists one publication's releases in release order, and ``page``
    reads older pages. ``since`` and ``until`` keep the releases whose
    ``release_datetime`` date, as printed, lies between them, both included. Lately a
    page holds about two weeks of releases (page 1 of 2026-10-28 runs 2026-10-09 back to
    2026-09-24), fetched at 30 requests a minute, so a ``since`` a month back costs about
    four requests and one a year back some 26 to 30, about a minute. A call with neither
    ``since`` nor ``page`` raises ``InvalidRequestError`` before any request: it would
    walk all 1,542,025 releases on 61,681 pages, as recorded on 2026-10-27, about 34
    hours; so does ``until`` alone, which bounds nothing of the walk, and a ``since``
    after ``until``. ``meta.total`` is upstream's count of every release, before the date
    filter. ``meta.vintage`` and ``meta.published_at`` stay empty: each release has its
    own (``get_release``).

    Args:
        since: The earliest release date to keep, e.g. ``2026-10-20`` (a date); without
            ``page`` the walk stops by it, and it must be on or after ``2025-09-12``.
            ``None`` (the default) needs ``page``.
        until: The latest release date to keep, e.g. ``2026-10-23`` (a date); ``None``
            (the default) keeps every one up to the newest.
        page: A 0-based page of 25, e.g. ``0`` for the 25 newest catalogued releases;
            ``None`` (the default) walks the pages from page 0 down to ``since``.
    """
    if since is not None and until is not None and since > until:
        raise InvalidRequestError(
            f"since ({since}) is after until ({until}): no release can lie between them",
            source=SOURCE,
        )
    if page is None and since is not None and since < CATALOG_ORDER_SINCE:
        raise InvalidRequestError(
            f"since ({since}) is before {CATALOG_ORDER_SINCE}: ESMIS's catalog lists releases "
            f"in an order that follows their release dates only since {CATALOG_ORDER_SINCE}, "
            "so a walk from an older since could stop early; use list_releases for one "
            "publication's releases in release order, pass page to read older pages of the "
            f"catalog, or pass a since on or after {CATALOG_ORDER_SINCE}",
            source=SOURCE,
        )
    request = _request(since=since, until=until, page=page)

    def kept(release: Release) -> bool:
        day = release.release_datetime.date()  # the printed date, never converted
        return (since is None or day >= since) and (until is None or day <= until)

    if page is not None:
        answer = await api.release_find_all(page)
        releases, total = answer.results, _total(answer.pager)
    elif since is None:
        alone = (
            "until alone bounds nothing of the walk, which starts at the newest catalogued "
            "release; "
            if until is not None
            else ""
        )
        raise InvalidRequestError(
            f"pass since or page: {alone}without either, list_recent_releases would walk "
            "every page of esmis_api_release_findAll, 1,542,025 releases on 61,681 pages as "
            "recorded on 2026-10-27, about 34 hours at 30 requests a minute; pass since (e.g. "
            "2026-10-20) or page (0 for the 25 newest catalogued releases)",
            source=SOURCE,
        )
    else:

        async def fetch_page(number: int) -> _PageAnswer[Release]:
            answer = await api.release_find_all(number)
            return answer.pager, answer.results

        releases, total = await _Pages(fetch_page, _newest_before(since)).walk()
    meta = ResultMeta(source=SOURCE, endpoint=ALL_RELEASES, request=request, total=total)
    return Result(data=[release for release in releases if kept(release)], meta=meta)


async def get_release_async(release_id: int) -> Result[Release]:
    """One release by its id: its publication's title, release time and file links.

    One request (``esmis_api_release_findById``); an id ESMIS does not know raises
    ``NotFoundError`` (HTTP 404). ``meta.vintage`` is the release id, e.g. ``"796099"``.
    ``meta.published_at`` is the release's ``release_datetime`` as printed with its
    ``+0000`` dropped, flagged ``published_at_naive``: ESMIS's own calendar puts the
    release at noon Eastern while the API prints ``+0000``, so the time is upstream's
    text, never converted. ``release_datetime`` keeps the time as printed.

    Args:
        release_id: A ``Release.id`` as a number, e.g. ``796099`` (the WASDE of
            2026-10-09), as ``list_releases`` and ``get_latest_release`` give them.
    """
    release = await _release(release_id)
    return Result(data=release, meta=_release_meta(RELEASE, release, {"release_id": release_id}))


async def get_latest_release_async(publication_identifier: str) -> Result[Release]:
    """A publication's latest release: the one with the latest release time.

    One request, page 0 of ``esmis_api_release_findByIdentifier``, and of its releases the
    one with the latest ``release_datetime``, never the highest id (within a publication
    the ids do not follow the dates). It relies on ESMIS listing a publication's releases
    newest first by ``release_datetime``, an order observed on 2026-10-27, not documented.
    An identifier ESMIS does not know, or a publication without releases, raises
    ``NotFoundError``. ``meta.vintage`` is the release id. ``meta.published_at`` is the
    release's ``release_datetime`` as printed with its ``+0000`` dropped, flagged
    ``published_at_naive``: ESMIS's own calendar puts the release at noon Eastern while
    the API prints ``+0000``, so the time is upstream's text, never converted.
    ``release_datetime`` keeps the time as printed.

    Args:
        publication_identifier: One of a publication's ``identifier`` values, e.g.
            ``"wasde"``, ``"CropProg"``; pass one without ``/``.
    """
    answer = await api.release_find_by_identifier(publication_identifier, 0)
    if not answer.results:
        raise NotFoundError(
            f"ESMIS lists no release for the identifier {publication_identifier!r}: GET "
            f"{_path('release/findByIdentifier', publication_identifier)} answered no "
            "result; search_publications finds identifiers by keyword",
            source=SOURCE,
        )
    latest = max(answer.results, key=lambda release: release.release_datetime)
    request = _request(publication_identifier=publication_identifier)
    return Result(data=latest, meta=_release_meta(RELEASES, latest, request))


async def list_release_files_async(release_id: int) -> Result[list[ReleaseFile]]:
    """The files of one release, each with its URL, name and format: pick one to download.

    One request (``esmis_api_release_findById``): the release's ``files`` in upstream
    order, each with its name as the URL prints it (``"wasde1026.txt"``) and its format,
    the extension lowercased (``"pdf"``, ``"txt"``, ``"xls"``, ``"xml"``, ``"zip"``); one to
    six per recorded release, two of one format where a release keeps an original and a
    revised file (``ORIGwasde-08-12-2013.xml`` before ``wasde-08-12-2013.xml`` in release
    95621). The catalog states no size. An id ESMIS does not know raises
    ``NotFoundError``. ``download_release_file`` fetches a file in Python, by its format
    or its name; no MCP tool downloads. ``meta.vintage`` is the release id.
    ``meta.published_at`` is the release's ``release_datetime`` as printed with its
    ``+0000`` dropped, flagged ``published_at_naive``: ESMIS's own calendar puts the
    release at noon Eastern while the API prints ``+0000``, so the time is upstream's
    text, never converted.

    Args:
        release_id: A ``Release.id`` as a number, e.g. ``796099`` (the WASDE of
            2026-10-09), ``95621`` (the WASDE of 2013-08-12).
    """
    release = await _release(release_id)
    meta = _release_meta(RELEASE, release, {"release_id": release_id})
    return Result(data=release.release_files(), meta=meta)


async def download_release_file_async(
    release_id: int,
    format: str | None = None,
    dest: str | PathLike[str] | None = None,
    *,
    name: str | None = None,
) -> Result[Downloaded]:
    """Download one file of a release to the path you name, e.g. the TXT of a WASDE.

    A bulk task, Python only: neither the MCP server nor the HTTP router serves it
    (``BULK_TASKS``). ``dest`` is checked first: left ``None``, a directory, or in a
    directory that does not exist, it raises ``InvalidRequestError`` before any request.
    Then two requests: the release (``esmis_api_release_findById``), and the file chosen
    from its files as ``list_release_files`` lists them, streamed to ``dest`` by core's
    ``download``, never held in memory and never cached; nothing in it is read. ``name``
    alone chooses the file with that name, ``format`` alone the first file of that format
    in upstream order, and both the named file, which must be of that format. Neither, or
    a ``name`` the release lacks, raises ``InvalidRequestError`` naming the release's
    files, a named file of another format one naming its format, and a ``format`` the
    release lacks one naming its formats, all before the file is requested; an unknown id
    raises ``NotFoundError``.
    ``meta.endpoint`` is the file's name as upstream prints it (``"wasde1026.txt"``),
    ``meta.vintage`` the release id, ``meta.request`` the release id, ``format`` and
    ``name`` as given, those left ``None`` omitted, and the file's URL, and
    ``meta.retrieved_at`` the time the file was complete. ``meta.published_at`` is the
    release's ``release_datetime`` as printed with its ``+0000`` dropped, flagged
    ``published_at_naive``: ESMIS's own calendar puts the release at noon Eastern while
    the API prints ``+0000``, so the time is upstream's text, never converted.

    Args:
        release_id: A ``Release.id`` as a number, e.g. ``796099`` (the WASDE of
            2026-10-09), ``95621`` (the WASDE of 2013-08-12).
        format: The file's format as ``list_release_files`` gives it, the extension in
            lower case, e.g. ``"txt"``, ``"xls"``, ``"xml"``, ``"pdf"``, ``"zip"``: the
            first file of that format. For release 95621, ``"xml"`` takes
            ``ORIGwasde-08-12-2013.xml``, the original, listed before the revised
            ``wasde-08-12-2013.xml``. ``None`` (the default) leaves the choice to ``name``.
        dest: The file to write, in a directory that exists, e.g. ``"wasde1026.txt"`` or
            ``Path("reports") / "wasde1026.txt"``; a file there is replaced. Required:
            its default ``None`` only keeps ``format`` optional before it, and raises
            ``InvalidRequestError``.
        name: A file's name as ``list_release_files`` gives it, keyword only, e.g.
            ``name="wasde-08-12-2013.xml"`` for release 95621, the revised XML, which
            ``format="xml"`` alone does not reach, or ``name="wasde1026.txt"`` for
            release 796099. ``None`` (the default) chooses by ``format``.
    """
    target = _target(dest)
    release = await _release(release_id)
    chosen = _select(release, format, name)
    downloaded = await client.download(chosen.url, target)
    meta = ResultMeta(
        source=SOURCE,
        endpoint=chosen.name,
        retrieved_at=downloaded.retrieved_at,
        published_at=_printed(release),
        published_at_naive=True,
        vintage=release.id,
        request=_request(release_id=release_id, format=format, name=name, url=chosen.url),
    )
    return Result(data=downloaded, meta=meta)


download_release_file = sync(download_release_file_async)
get_latest_release = sync(get_latest_release_async)
get_publication = sync(get_publication_async)
get_release = sync(get_release_async)
list_agencies = sync(list_agencies_async)
list_publications = sync(list_publications_async)
list_recent_releases = sync(list_recent_releases_async)
list_release_files = sync(list_release_files_async)
list_releases = sync(list_releases_async)
search_publications = sync(search_publications_async)
