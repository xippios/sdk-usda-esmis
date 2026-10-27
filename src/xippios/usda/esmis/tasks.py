"""Task-shaped functions for USDA ESMIS.

The public API (ADR-0001, layer 2), and the contract of the parser packages that depend
on this one: such a package imports these tasks and ``models``, never ``api/`` or
``_client`` (ADR-0021). A task composes endpoint wrappers from ``api/`` and returns
``Result[T]`` with full ``ResultMeta``. The async version is written, the sync one derived
with ``xippios.core.sync`` and listed in ``__all__``: the MCP server and the HTTP router
register exactly what is named there, minus ``BULK_TASKS``.

Docstrings are read by agents: one sentence first, then ``Args:`` with examples of
valid values for every parameter. ``/add-endpoint`` walks through the whole recipe.

What every task follows:

- ``meta.endpoint`` is the operationId of ``docs/upstream/openapi/esmis_public_api.yaml``
  (``esmis_api_release_findById``); for the download, the file's name as upstream prints
  it (``wasde1026.txt``; ADR-0020, decision 5). ``meta.request`` holds the parameters the
  caller gave, none left ``None`` (ADR-0022), and for the download also the file's ``url``.
  ``meta.total`` is ``pager.total_results`` of the last page fetched for the two paged
  list tasks (ADR-0012), ``None`` elsewhere.
  ``meta.retrieved_at`` is when the answer arrived: the client keeps no cache.
- Absence, as recorded per lookup: an unknown release id answers HTTP 404, raised by
  ``_client.classify`` as ``NotFoundError``; an unknown publication identifier answers
  HTTP 200 with nothing, which the single-record tasks ``get_publication`` and
  ``get_latest_release`` raise as ``NotFoundError`` (conventions §5) and the list task
  ``list_releases`` returns as the empty list with ``meta.total`` 0, as the pager says. An
  identifier carrying ``/`` is refused by ESMIS's web server, raised as
  ``InvalidRequestError``.
- Paging: pages are 0-based and hold 25 items. ``page`` given returns that page; omitted,
  ``_Pages`` walks them from page 0.
- Release times: ``meta.vintage`` is the release id as printed (``"796099"``). The four
  tasks about one release (``get_release``, ``get_latest_release``, ``list_release_files``,
  ``download_release_file``) set ``meta.published_at`` to its ``release_datetime`` as
  printed with its ``+0000`` dropped, flagged ``published_at_naive`` (ADR-0022): ESMIS
  prints ``+0000`` where its own calendar and the files' ``Last-Modified`` put the release
  at noon Eastern, so the time is upstream's text; no zone is attached and no time
  converted. ``Release`` keeps the value as printed; the list tasks leave
  ``meta.published_at`` empty.
- A catalog, never a parser (ADR-0020): no task reads a file's contents, and nothing is
  stored or cached; ``download_release_file`` writes where the caller says.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from os import PathLike
from urllib.parse import quote, urlsplit

from xippios.core import (
    Downloaded,
    InvalidRequestError,
    NotFoundError,
    Result,
    ResultCap,
    ResultMeta,
    collect,
    paginate_offset,
    sync,
)

from xippios.usda.esmis import api
from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import Agency, Pager, Publication, Release, ReleaseFile

__all__ = [
    "download_release_file",
    "get_latest_release",
    "get_publication",
    "get_release",
    "list_agencies",
    "list_release_files",
    "list_releases",
    "search_publications",
]

BULK_TASKS = frozenset({"download_release_file"})
"""Tasks the adapters skip (ADR-0019, decision 4): they write a file, which no tool or
route hands out. Hand-written until the template renders it (template v0.3.0)."""

# No tool gets a result cap of its own (conventions §8, ADR-0016): list_agencies answers
# 9 rows and list_release_files at most 4 files as recorded, within the default 200 rows
# or 64 KB. Two tools called without page can exceed it: list_releases answers hundreds
# of rows (703 for WASDE), and search_publications every match of a keyword, about 1.8 KB
# a publication as the WASDE matches average (0.6 KB on publication_find_all's page 0),
# so 64 KB can cut a broad keyword's list after some 36; a page of 25 fits at those sizes
# (about 45 KB). The default cap applies to both, with its note, and their docstrings
# tell an agent to page, list_releases's also to bound the call with since and until.
MCP_CAPS: Mapping[str, ResultCap] = {}

PAGE_SIZE = 25
"""Items on a page of every paged operation, a size no documented parameter changes."""

AGENCIES = "esmis_api_agency_findAll"
SEARCH = "esmis_api_publication_search"
PUBLICATION = "esmis_api_publication_findByIdentifier"
RELEASE = "esmis_api_release_findById"
RELEASES = "esmis_api_release_findByIdentifier"


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
    a task's own end (``list_releases``'s ``since``). The ``current_page`` an answer
    echoes is never read: a page past the last echoes the last one's number.

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


def _path(prefix: str, value: str) -> str:
    """A catalog path with ``value`` quoted whole, as the wrappers send it, for a message."""
    return f"/api/v1/{prefix}/{quote(value, safe='')}"


def _files(release: Release) -> list[ReleaseFile]:
    """The release's ``files``, in upstream order, each with its name and format."""
    files = []
    for url in release.files:
        name = urlsplit(url).path.rsplit("/", 1)[-1]
        _, dot, extension = name.rpartition(".")
        files.append(ReleaseFile(url=url, name=name, format=extension.lower() if dot else ""))
    return files


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


async def search_publications_async(
    query: str, page: int | None = None
) -> Result[list[Publication]]:
    """Publications (report series) matching a keyword: find the identifier other tools take.

    One request per page of 25 (``esmis_api_publication_search``): ``page`` given returns
    that page, omitted every page. ``"wasde"`` matched 7 publications on 2026-10-27, WASDE
    itself (identifier ``"wasde"``) among them. The MCP tool returns at most 200 rows or
    64 KB, about 36 publications at about 1.8 KB each (the recorded WASDE matches range
    0.9-2.5 KB): page a broad keyword with ``page`` (0, 1, ...) until a page is short. A
    publication's ``identifier`` values are what ``get_publication``, ``list_releases``
    and ``get_latest_release`` take; pass one without ``/``. ``meta.total`` is upstream's
    count of matches. An empty or blank ``query`` raises ``InvalidRequestError`` before
    anything is sent: ESMIS requires one and answers an empty one with nothing.

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
    releases, paced at 30 a minute), and the MCP tool returns at most 200 rows or 64 KB:
    bound the call with ``since`` and ``until``, or page. An identifier ESMIS does not
    know gives the empty list with ``meta.total`` 0. ``meta.total`` is upstream's count of
    the publication's releases before the date filter, so it can exceed the rows
    returned. ``meta.vintage`` and ``meta.published_at`` stay empty: each release has its
    own (``get_release``).

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
    four per recorded release. The catalog states no size. An id ESMIS does not know
    raises ``NotFoundError``. ``download_release_file`` fetches a file in Python; no MCP
    tool downloads. ``meta.vintage`` is the release id. ``meta.published_at`` is the
    release's ``release_datetime`` as printed with its ``+0000`` dropped, flagged
    ``published_at_naive``: ESMIS's own calendar puts the release at noon Eastern while
    the API prints ``+0000``, so the time is upstream's text, never converted.

    Args:
        release_id: A ``Release.id`` as a number, e.g. ``796099`` (the WASDE of
            2026-10-09).
    """
    release = await _release(release_id)
    meta = _release_meta(RELEASE, release, {"release_id": release_id})
    return Result(data=_files(release), meta=meta)


async def download_release_file_async(
    release_id: int, format: str, dest: str | PathLike[str]
) -> Result[Downloaded]:
    """Download one file of a release to the path you name, e.g. the TXT of a WASDE.

    A bulk task, Python only: neither the MCP server nor the HTTP router serves it
    (``BULK_TASKS``). Two requests: the release (``esmis_api_release_findById``), then the
    first of its files whose format is ``format``, streamed to ``dest`` by core's
    ``download``, never held in memory and never cached; nothing in it is read. A format
    the release does not have raises ``InvalidRequestError`` naming the formats it has,
    an unknown id ``NotFoundError``, and a ``dest`` that is a directory, or whose
    directory does not exist, ``ValueError`` before the file is requested.
    ``meta.endpoint`` is the file's name as upstream prints it (``"wasde1026.txt"``),
    ``meta.vintage`` the release id, ``meta.request`` the release id, the format and the
    file's URL, and ``meta.retrieved_at`` the time the file was complete.
    ``meta.published_at`` is the release's ``release_datetime`` as printed with its
    ``+0000`` dropped, flagged ``published_at_naive``: ESMIS's own calendar puts the
    release at noon Eastern while the API prints ``+0000``, so the time is upstream's
    text, never converted.

    Args:
        release_id: A ``Release.id`` as a number, e.g. ``796099`` (the WASDE of
            2026-10-09).
        format: The file's format as ``list_release_files`` gives it, the extension in
            lower case, e.g. ``"txt"``, ``"xls"``, ``"xml"``, ``"pdf"``, ``"zip"``.
        dest: The file to write, in a directory that exists, e.g. ``"wasde1026.txt"`` or
            ``Path("reports") / "wasde1026.txt"``; a file there is replaced.
    """
    release = await _release(release_id)
    files = _files(release)
    chosen = next((file for file in files if file.format == format), None)
    if chosen is None:
        formats = ", ".join(dict.fromkeys(file.format for file in files)) or "none"
        raise InvalidRequestError(
            f"release {release_id} has no {format!r} file; its formats: {formats}",
            source=SOURCE,
        )
    downloaded = await client.download(chosen.url, dest)
    meta = ResultMeta(
        source=SOURCE,
        endpoint=chosen.name,
        retrieved_at=downloaded.retrieved_at,
        published_at=_printed(release),
        published_at_naive=True,
        vintage=release.id,
        request={"release_id": release_id, "format": format, "url": chosen.url},
    )
    return Result(data=downloaded, meta=meta)


download_release_file = sync(download_release_file_async)
get_latest_release = sync(get_latest_release_async)
get_publication = sync(get_publication_async)
get_release = sync(get_release_async)
list_agencies = sync(list_agencies_async)
list_release_files = sync(list_release_files_async)
list_releases = sync(list_releases_async)
search_publications = sync(search_publications_async)
