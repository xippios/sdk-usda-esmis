"""Refresh the packaged reference tables from upstream (``/refresh-reference-data``).

ESMIS packages two tables, declared in ``LISTS``, core's ``Lists``, one ``Listed`` each, and
named in ``params.PACKAGED_LISTS``; core's frame, ``xippios.core.refresh``, runs them
(sdk-core ADR-0062). It fetches both through the package's client, one attempt per request,
before it writes either, then writes each ``reference/<name>.json`` by ``PackagedList.write``
and its row of the provenance table in ``reference/README.md`` as one, and no ``enums.py``,
since neither table makes an enum; it prints the requests it sent, a failed run's too.

- ``agency``: every agency ``esmis_api_agency_findAll`` answers, with every field of
  ``Agency``, one request (``agencies``);
- ``publication``: every page of ``esmis_api_publication_findAll``, walked from page 0
  (0-based, ``tasks.PAGE_SIZE`` a page) by core's ``fetch_pages``, the package's one walk
  of pages, up to upstream's count, never by the ``current_page`` an answer echoes, each
  publication projected to ``PublicationRow``, the columns ``list_publications`` answers
  with, in upstream order (``publications``).

Records keep upstream's field names (``UpstreamModel.dump_upstream``); each table is a
finished ``PackagedList``, ``fetched`` the UTC time of its first request and its ``note``
naming what was fetched. The walk refuses to write when the pages disagree (an answer
without a ``pager``, a ``total_results``, ``total_pages`` or ``items_per_page`` that changed
between pages, a repeated id, a count that is not ``total_results``): a publication added
during the walk shifts the pages, and the run is repeated. The API is keyless. Run from the
repository root::

    uv run python scripts/refresh_reference.py                  # both tables
    uv run python scripts/refresh_reference.py --only agency    # one table, the other kept
    uv run python scripts/refresh_reference.py --render-only    # the provenance rows alone

The budget: 102 requests, the agency list and the 101 publication pages that the packaged
table was fetched from (2522 publications), one more for each 25 publications upstream added
since, each sent once, at the client's pace of 30 a minute, burst 1: about four minutes.
``--render-only`` sends none.
"""

import math
from collections.abc import Sequence
from datetime import UTC, datetime

from xippios.core import InvalidRequestError, PackagedList, fetch_pages
from xippios.core.refresh import Listed, Lists, run

from xippios.usda.esmis import api
from xippios.usda.esmis._client import SOURCE, client
from xippios.usda.esmis.models import Pager, Publication, PublicationRow
from xippios.usda.esmis.params import PACKAGE, PACKAGED_LISTS
from xippios.usda.esmis.tasks import PAGE_SIZE

AGENCIES = "esmis_api_agency_findAll"
PUBLICATIONS = "esmis_api_publication_findAll"
COLUMNS = ", ".join(PublicationRow.model_fields)
PUBLICATION_PAGES = 200
"""The most pages the walk of every publication fetches: about twice the 101 that the packaged
table was fetched from, so a catalog that doubled stops the run before it spends its requests,
and the bound is raised once the count is checked."""


async def agencies() -> PackagedList:
    """Every agency, one request, every field under upstream's names."""
    fetched = datetime.now(UTC)
    answer = await api.agency_find_all()
    records = [agency.dump_upstream() for agency in answer.payload]
    note = (
        f"Every agency GET /api/v1/agency/findAll answered, one request, {len(records)} "
        "agencies in upstream order, every field of Agency."
    )
    return PackagedList(
        param="agency", endpoint=AGENCIES, fetched=fetched, note=note, records=records
    )


async def walk() -> tuple[list[Publication], Pager]:
    """Every publication, page 0 to upstream's count, and page 0's pager.

    Raises:
        SystemExit: An answer without a ``pager``, pagers that disagree, a walk past
            ``PUBLICATION_PAGES``, a repeated id or a count that is not ``total_results``;
            nothing is written then.
    """
    first: list[Pager] = []

    async def fetch(offset: int) -> tuple[Sequence[Publication], int | None]:
        number = offset // PAGE_SIZE
        answer = await api.publication_find_all(number)
        pager = answer.payload.pager
        if not isinstance(pager, Pager):
            raise SystemExit(f"page {number} answered no pager; nothing written")
        if not first:
            first.append(pager)
        expected = (first[0].total_pages, first[0].total_results, PAGE_SIZE)
        if (pager.total_pages, pager.total_results, pager.items_per_page) != expected:
            raise SystemExit(
                f"page {number} counts {pager.total_results} publications on "
                f"{pager.total_pages} pages of {pager.items_per_page}, page 0 counted "
                f"{first[0].total_results} on {first[0].total_pages} pages of {PAGE_SIZE}: "
                "the catalog changed during the walk; run it again"
            )
        return answer.payload.results, pager.total_results

    try:
        found, _ = await fetch_pages(
            fetch, page_size=PAGE_SIZE, most=PUBLICATION_PAGES, paging="page", source=SOURCE
        )
    except InvalidRequestError:
        pages = first[0].total_pages if first else "more"
        raise SystemExit(
            f"the catalog counts {pages} pages of publications, more than the "
            f"{PUBLICATION_PAGES} this script walks; nothing written: check the count and "
            "raise PUBLICATION_PAGES"
        ) from None
    pager = first[0]
    ids = [publication.id for publication in found]
    if len(set(ids)) != len(ids) or len(ids) != pager.total_results:
        raise SystemExit(
            f"the walk found {len(ids)} publications, {len(set(ids))} distinct ids, where the "
            f"pager counts {pager.total_results}: the pages shifted; run it again"
        )
    return found, pager


async def publications() -> PackagedList:
    """The walk as the packaged publication table."""
    fetched = datetime.now(UTC)
    found, pager = await walk()
    records = [PublicationRow.project(publication).dump_upstream() for publication in found]
    with_acronym = sum(publication.agency_acronym is not None for publication in found)
    with_export = sum(publication.publication_agency_export_1 is not None for publication in found)
    note = (
        f"Every page of GET /api/v1/publication/findAll walked, pages 0 to "
        f"{pager.total_pages - 1} (0-based, {PAGE_SIZE} a page), bounded by pager.total_pages "
        f"{pager.total_pages}, one request a page; pager.total_results {pager.total_results} "
        f"on every page, {len(records)} publications with distinct ids, in upstream order. "
        f"Each record keeps the Publication fields {COLUMNS} (PublicationRow), upstream's "
        f"names and values; agency_acronym on {with_acronym}, publication_agency_export_1 on "
        f"{with_export}, null where upstream leaves it out."
    )
    return PackagedList(
        param="publication", endpoint=PUBLICATIONS, fetched=fetched, note=note, records=records
    )


def publication_origin(table: PackagedList) -> str:
    """The publication table's Origin: the operation, its path and the pages walked."""
    last = math.ceil(len(table.records) / PAGE_SIZE) - 1
    return f"`{PUBLICATIONS}`, `GET /api/v1/publication/findAll`, every page, 0 to {last}"


LISTS = Lists(
    package=PACKAGE,
    lists=(
        Listed(
            name="agency",
            fetch=agencies,
            endpoint=AGENCIES,
            param="agency",
            origin=f"`{AGENCIES}`, `GET /api/v1/agency/findAll`, one request",
        ),
        Listed(
            name="publication",
            fetch=publications,
            endpoint=PUBLICATIONS,
            param="publication",
            origin=publication_origin,
        ),
    ),
    packaged=PACKAGED_LISTS,
    client=client,
    quota_header=None,
)
"""The two tables, each a finished ``PackagedList`` with its note, and no enum; ESMIS reports
no quota, so no header is read."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run core's frame on ``LISTS``: both tables, one with ``--only``, or ``--render-only``."""
    return run(LISTS, argv)


if __name__ == "__main__":
    raise SystemExit(main())
