# What ESMIS does but never documents

Notes, written by hand, on what the live API and the ESMIS site do that no page of this
snapshot states (sdk-core's conventions §3). The OpenAPI document,
`openapi/esmis_public_api.yaml`, is the reference for names and parameters; where the
live API answers differently, the wire wins for types, and `models.py` and
`tests/fixtures/` follow it. `scripts/refresh_upstream.py` neither writes nor checks this
file, and `FETCHED.md` lists it in a row of its own.

Each note ends with its probe: the date, the operation or the page, and the sample. A
sample recorded as a fixture is named by its path under `tests/fixtures/`. The walk of
every publication on 2026-10-27 is kept as the packaged table,
`src/xippios/usda/esmis/reference/publication.json`, whose `note` describes the walk. A
page of the snapshot of 2026-10-27, which a later capture replaced, is named by its URL
at the commit that holds it.

## Types and fields

### Every `id` is a string

Every `id` in an answer is a JSON string of digits, where the document types it as an
integer. The walk of every `/publication/findAll` page found 2522 publications with
distinct ids, each a string of digits.

Probe: 2026-10-27, `esmis_api_publication_findAll`, pages 0 to 100, one request a page;
samples `publication_find_all/page0.json` and the packaged table's 2522 ids.

### `agency`, `identifier` and `agency_acronym` are arrays

`Publication.agency`, `.identifier` and `.agency_acronym` are arrays of strings, where
the document types each as a string.

Probe: 2026-10-27, `esmis_api_publication_findAll`, pages 0 to 100; sample
`publication_find_all/page0.json`, whose first publication, 2425, lists two agencies,
two identifiers and two acronyms.

### `agency_acronym` comes from one operation alone

`agency_acronym` is absent on the publications that the four other publication
operations answer, which carry `publication_agency_export_1` instead.
`/publication/findAll` carried `agency_acronym` on all 2522 publications of the walk and
`publication_agency_export_1` on none.

Probe: 2026-10-27, `esmis_api_publication_findAll`, pages 0 to 100, and
`esmis_api_publication_findById`, `esmis_api_publication_findByIdentifier`,
`esmis_api_publication_findByAgency` and `esmis_api_publication_search`; samples
`publication_find_all/page0.json`, `publication_find_by_id/1659.json`,
`publication_find_by_identifier/wasde.json`, `publication_find_by_agency/waob_page0.json`
and `publication_search/wasde_page0.json`.

### `frequency` outside its enumeration

`Publication.frequency` printed `""` on one publication of the walk, 1172, a value the
document's enumeration does not list. `status`, `subscribable` and `resource_type` held
only the document's values.

Probe: 2026-10-27, `esmis_api_publication_findAll`, pages 0 to 100; sample the packaged
table's row of publication 1172.

### The list answers carry three more keys

The list answers have `filters`, `sorters` and `system` (`{"page_key": "page"}`) beside
`pager` and `results`.

Probe: 2026-10-27, the list operations; samples `publication_find_all/page0.json` and
`release_find_all/page0.json`.

### `upcoming_releases` print an Eastern offset

`Publication.upcoming_releases` is `[]` on most publications: the walk found items on
24 of 2522, 67 in all, each printed with an Eastern offset (`2026-10-28T15:00:00-0400`
and `2026-11-04T15:00:00-0500` for publication 1863), where `release_datetime` prints
`+0000`. The document lists no operation for the release calendar.

Probe: 2026-10-27, `esmis_api_publication_findAll`, pages 0 to 100, and
`esmis_api_publication_findById` for 1863; sample `publication_find_by_id/1863.json`.

## Answers and refusals

### `/publication/search` without a query

`/publication/search` without `query`, or with an empty one, answers 200 with
`"pager": []` and empty results, although the document makes `query` required.

Probe: 2026-10-27, `esmis_api_publication_search`; samples
`publication_search/no_query.json` and `publication_search/empty_query.json`.

### Absence answers differ per lookup

An unknown id answers HTTP 404 `{"message": ""}` at `/agency/findById`,
`/publication/findById`, `/release/findById` and `/release/findByPubId`. An unknown name
answers 200 with nothing: `/agency/findByAcronym` an empty array,
`/publication/findByAgency`, `/publication/findByIdentifier` and
`/release/findByIdentifier` empty results with every pager count 0.

Probe: 2026-10-27, the eight lookups named; samples `agency_find_by_id/unknown.json`,
`publication_find_by_id/unknown.json`, `release_find_by_id/unknown.json`,
`release_find_by_pub_id/unknown.json`, `agency_find_by_acronym/unknown.json`,
`publication_find_by_agency/unknown.json`, `publication_find_by_identifier/unknown.json`
and `release_find_by_identifier/unknown.json`.

### An identifier carrying `/` cannot be looked up

An identifier carrying `/` (`Market and Trade Economics Division/FDS`) cannot be looked
up: the web server answers `%2F` in a path with its own HTML 404, and a raw slash is no
route. Of the 71 publications of the walk with such an identifier, 70 have another
without it (`FDS` beside `Market and Trade Economics Division/FDS`), and publication 654
has none: its one identifier is `Market Trade Economic Division/SSS-yearbook`.

Probe: 2026-10-27, `esmis_api_publication_findByIdentifier` for
`Market and Trade Economics Division/FDS`, quoted whole; sample
`publication_find_by_identifier/with_slash.json`, and the packaged table's 71 rows with
an identifier that holds `/`, publication 654's among them.

## Paging and order

### A page holds 25 items, and a page past the last is empty

`page` is 0-based and a page holds 25 items, as the document's defaults say. The
document does not say that the page size is fixed, and no parameter changes it, nor that
a page past the last answers empty results with `current_page` clamped to the last page.

Probe: 2026-10-27, `esmis_api_publication_findAll`, page 500 of 101; sample
`publication_find_all/page500.json`, which answers `current_page` 100.

### `/release/findAll` lists the highest id first

`/release/findAll` comes highest id first, the newest created, for the releases
catalogued since ESMIS's migration, whose first WASDE release is 791996 of 2025-09-12,
with `release_datetime` only mostly in that order: page 0 of 2026-10-27 runs
2026-10-26, 2026-10-09, 2026-10-23, and page 1 of 2026-10-28 runs 2026-10-09,
2026-09-28, 2026-10-07. 14 days, release 796123 against 796122, is the largest gap on
those two pages, which `list_recent_releases` takes as its walk's tolerance. Below the
migration the ids do not follow the dates: WASDE's 96165 to 96171 run May, April, March,
February, August, July and June 2025, and 95511 of 2022-08-12 and 95621 of 2013-08-12
sit above 95482 of 2025-01-10, so `list_recent_releases` refuses a walk from a `since`
before 2025-09-12.

Probe: 2026-10-27 and 2026-10-28, `esmis_api_release_findAll`, pages 0 and 1; samples
`release_find_all/page0.json` and `release_find_all/page1.json`. Below the migration,
`esmis_api_release_findByIdentifier` for `wasde`, pages 0 and 1, on 2026-10-27, and
`esmis_api_release_findById` for 95621 on 2026-10-28; samples
`release_find_by_identifier/wasde_page0.json`,
`release_find_by_identifier/wasde_page1.json` and `release_find_by_id/95621.json`.

### A publication's releases come latest first

A publication's releases (`/release/findByIdentifier`) come latest `release_datetime`
first whatever their ids, as recorded on WASDE's pages 0 and 1: 50 releases, 2026-10-09
back to 2022-08-12.

Probe: 2026-10-27, `esmis_api_release_findByIdentifier` for `wasde`, pages 0 and 1;
samples `release_find_by_identifier/wasde_page0.json` and
`release_find_by_identifier/wasde_page1.json`.

### Publication lists follow no id order

`/publication/findAll` page 0 lists ids 2425, 1801, 1861, 1922, and
`/publication/search?query=wasde` 1762, 1831, 1154.

Probe: 2026-10-27, `esmis_api_publication_findAll`, page 0, and
`esmis_api_publication_search` for `wasde`; samples `publication_find_all/page0.json`
and `publication_search/wasde_page0.json`.

## Release times and files

### `release_datetime` prints a zone with no colon

`release_datetime` is `YYYY-MM-DDTHH:MM:SS+0000`, a zone with no colon.

Probe: 2026-10-27, `esmis_api_release_findById` for 796099; sample
`release_find_by_id/796099.json`, `2026-10-09T12:00:00+0000`.

### The zone label of release times

The API prints `release_datetime` with `+0000` and the release page its `datetime` with
`Z` (`2026-10-09T12:00:00+0000` and `datetime="2026-10-09T12:00:00Z"` for the October
2026 WASDE), while the release calendar, whose settings say
`timeZone: "America/New_York"`, puts the WASDE releases that
`/release/findByIdentifier/wasde` (page 0) prints as `2025-09-12T12:00:00+0000` and
`2025-12-09T12:00:00+0000` at `2025-09-12T12:00:00-04:00` and
`2025-12-09T12:00:00-05:00`, and the October release's own file answers
`HEAD /sites/default/release-files/796099/wasde1026.txt` with
`Last-Modified: Fri, 09 Oct 2026 16:01:00 GMT`, 12:01 Eastern. The `+0000` and `Z` label
is contradicted by upstream's own calendar and file timestamps, which fit a noon Eastern
wall-clock time. The tasks keep `release_datetime` as printed, and those about one
release put its wall-clock time, the `+0000` dropped, into `meta.published_at` with
`published_at_naive` set (sdk-core ADR-0041, decision 2; `CLAUDE.md`, Release times).

Probe: 2026-10-27, the release page of the October 2026 WASDE,
https://github.com/xippios/sdk-usda-esmis/blob/046ed468f76e53403e01462dd65dea17b72f348d/docs/upstream/pages/release-wasde.md;
the release calendar's settings and events, from its full page, excerpted at
https://github.com/xippios/sdk-usda-esmis/blob/046ed468f76e53403e01462dd65dea17b72f348d/docs/upstream/pages/release-calendar.md;
`esmis_api_release_findByIdentifier` for `wasde`, page 0, sample
`release_find_by_identifier/wasde_page0.json`; and a `HEAD` of the file, whose
`Last-Modified` the recorded download `download_release_file/wasde1026_txt.json`
answers too.

### `Release.files` paths take two shapes

Recent releases use `/sites/default/release-files/{release id}/{name}.{ext}`
(`/sites/default/release-files/796099/wasde1026.txt`), older ones the hashed
three-segment path the document's example shows
(`/sites/default/release-files/8336h188j/2514qk05k/j0991c960/prog3925.pdf`).

Probe: 2026-10-27 and 2026-10-28, `esmis_api_release_findById` for 796099 and 95621;
samples `release_find_by_id/796099.json` and `release_find_by_id/95621.json`.

## The release calendar

### The calendar draws on another field than the API

The release calendar page held 3776 events, drawn from a `publication_upcoming_releases`
field (each event's `startField`), while the API's `Publication.upcoming_releases` lists
67 upcoming releases on 24 publications. Every calendar event is classed
`fc-event-past`, future ones included, and WASDE's events stop at 2025-12-09.

Probe: 2026-10-27, the full page https://esmis.nal.usda.gov/release-calendar, 1,290,689
bytes, excerpted at
https://github.com/xippios/sdk-usda-esmis/blob/046ed468f76e53403e01462dd65dea17b72f348d/docs/upstream/pages/release-calendar.md,
whose row in that commit's `FETCHED.md` holds the full page's sha256; the 67 releases
from `esmis_api_publication_findAll`, pages 0 to 100.
