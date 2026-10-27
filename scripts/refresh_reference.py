"""Refresh the packaged reference tables from upstream (``/refresh-reference-data``).

ESMIS packages two tables, each the records of one operation, fetched through the
layer-1 wrappers in ``api/``, never through a task that answers from the package, and
written with core's ``PackagedList.write`` (conventions §3, ADR-0022):

- ``reference/agency.json``: every agency ``esmis_api_agency_findAll`` answers, with
  every field of ``Agency``, one request;
- ``reference/publication.json``: every page of ``esmis_api_publication_findAll``,
  walked from page 0 (0-based, 25 a page) up to the first answer's
  ``pager.total_pages``, never by the ``current_page`` an answer echoes, each
  publication projected to ``PublicationRow``, the columns ``list_publications``
  answers with, in upstream order.

Records keep upstream's field names (``UpstreamModel.dump_upstream``); ``fetched`` is
the UTC time of the table's first request, which ``write`` keeps to the second; the
publication table's ``note`` names the walk. Then the provenance rows of
``reference/README.md`` are rewritten and the counts printed. The walk refuses to write
when the pages disagree (a ``total_results`` or ``total_pages`` that changed between
pages, a repeated id, a count that is not ``total_results``): a publication added during
the walk shifts the pages, and the run is repeated.

No ``enums.py`` is generated: the three enumerations of ``Publication`` stay hand-written
in ``models.py``, and neither table is a value list, so the scaffold's ``--render-only``,
which regenerated ``enums.py`` alone, is dropped with it. The API is keyless. Run from the
repository root::

    uv run python scripts/refresh_reference.py

The budget: 102 requests, the agency list and 101 publication pages as of 2026-10-27
(2522 publications), at the client's pace of 30 a minute, burst 1: about four minutes.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from xippios.core import PackagedList, sync

from xippios.usda.esmis import api
from xippios.usda.esmis._client import SOURCE
from xippios.usda.esmis.models import Pager, Publication, PublicationRow

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "src/xippios/usda/esmis/reference"
README = REFERENCE / "README.md"
PAGE_SIZE = 25
"""Publications on a page of ``esmis_api_publication_findAll``, a size no parameter changes."""

AGENCIES = "esmis_api_agency_findAll"
PUBLICATIONS = "esmis_api_publication_findAll"
COLUMNS = ", ".join(PublicationRow.model_fields)
PROVENANCE = re.compile(r"(\| File \| Origin \| Fetched \|\n\| --- \| --- \| --- \|\n)(?:\|.*\n)*")
"""The provenance table of ``reference/README.md``: its header kept, its rows replaced."""


class Refused(Exception):
    """A walk the script will not write; ``main`` exits with its message.

    An ``Exception``, never ``SystemExit``: raised inside the coroutine that core's
    ``sync`` runs on its background loop, a ``SystemExit`` stops that loop's thread and
    leaves the caller waiting for ever.
    """


async def agencies() -> PackagedList:
    """Every agency, one request, every field under upstream's names."""
    fetched = datetime.now(UTC)
    records = [agency.dump_upstream() for agency in await api.agency_find_all()]
    note = (
        f"Every agency GET /api/v1/agency/findAll answered, one request, {len(records)} "
        "agencies in upstream order, every field of Agency."
    )
    return PackagedList(
        param="agency", endpoint=AGENCIES, fetched=fetched, note=note, records=records
    )


async def walk() -> tuple[list[Publication], Pager, int]:
    """Every publication, page 0 to the first answer's ``total_pages``, and the requests sent.

    Raises:
        Refused: An answer without a ``pager``, pagers that disagree, a repeated id or a
            count that is not ``total_results``; nothing is written then.
    """
    publications: list[Publication] = []
    first: Pager | None = None
    page = 0
    while first is None or page < first.total_pages:
        answer = await api.publication_find_all(page)
        if not isinstance(answer.pager, Pager):
            raise Refused(f"page {page} answered no pager; nothing written")
        if first is None:
            first = answer.pager
        elif (answer.pager.total_pages, answer.pager.total_results) != (
            first.total_pages,
            first.total_results,
        ):
            raise Refused(
                f"page {page} counts {answer.pager.total_results} publications on "
                f"{answer.pager.total_pages} pages, page 0 counted {first.total_results} on "
                f"{first.total_pages}: the catalog changed during the walk; run it again"
            )
        publications.extend(answer.results)
        page += 1
    if first is None:  # pragma: no cover - the loop runs at least once
        raise Refused("no page fetched")
    ids = [publication.id for publication in publications]
    if len(set(ids)) != len(ids) or len(ids) != first.total_results:
        raise Refused(
            f"the walk found {len(ids)} publications, {len(set(ids))} distinct ids, where the "
            f"pager counts {first.total_results}: the pages shifted; run it again"
        )
    return publications, first, page


async def publications() -> tuple[PackagedList, int]:
    """The walk as the packaged publication table, and the requests it sent."""
    fetched = datetime.now(UTC)
    found, pager, requests = await walk()
    records = [PublicationRow.project(publication).dump_upstream() for publication in found]
    with_acronym = sum(publication.agency_acronym is not None for publication in found)
    with_export = sum(publication.publication_agency_export_1 is not None for publication in found)
    note = (
        f"Every page of GET /api/v1/publication/findAll walked, pages 0 to {requests - 1} "
        f"(0-based, {PAGE_SIZE} a page), bounded by pager.total_pages {pager.total_pages}, "
        f"one request a page; pager.total_results {pager.total_results} on every page, "
        f"{len(records)} publications with distinct ids, in upstream order. Each record "
        f"keeps the Publication fields {COLUMNS} (PublicationRow), upstream's names and "
        f"values; agency_acronym on {with_acronym}, publication_agency_export_1 on "
        f"{with_export}, null where upstream leaves it out."
    )
    table = PackagedList(
        param="publication", endpoint=PUBLICATIONS, fetched=fetched, note=note, records=records
    )
    return table, requests


def provenance(tables: list[PackagedList], pages: int) -> None:
    """Rewrite the provenance rows of ``reference/README.md``: file, origin, fetched."""
    origins = {
        "agency": f"`{AGENCIES}`, `GET /api/v1/agency/findAll`, one request",
        "publication": (
            f"`{PUBLICATIONS}`, `GET /api/v1/publication/findAll`, every page, 0 to {pages - 1}"
        ),
    }
    rows = [
        f"| `{table.param}.json` | {origins[table.param]} ({len(table.records)} records) | "
        f"{table.fetched.replace(microsecond=0):%Y-%m-%dT%H:%M:%SZ} |"
        for table in tables
    ]
    text = README.read_text(encoding="utf-8")
    text = PROVENANCE.sub(lambda match: match.group(1) + "\n".join(rows) + "\n", text, count=1)
    README.write_text(text, encoding="utf-8")


async def refresh() -> None:
    """Fetch both tables, write them, update the provenance rows, print the counts."""
    if not PROVENANCE.search(README.read_text(encoding="utf-8")):
        raise Refused(f"{README.name} has no provenance table to update; nothing fetched")
    agency = await agencies()
    publication, pages = await publications()
    for table in (agency, publication):
        table.write(REFERENCE / f"{table.param}.json")
        fetched = f"{table.fetched:%Y-%m-%dT%H:%M:%SZ}"
        print(f"{table.param}.json: {len(table.records)} records, fetched {fetched}")  # noqa: T201
    provenance([agency, publication], pages)
    print(f"{SOURCE}: {1 + pages} requests, {README.name} updated")  # noqa: T201


def main() -> None:
    """Refresh both tables from upstream; a refused walk exits with its message."""
    try:
        sync(refresh)()
    except Refused as refused:
        raise SystemExit(str(refused)) from None


if __name__ == "__main__":
    main()
