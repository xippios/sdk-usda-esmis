# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [0.4.0] - 2026-11-28

### Added

- `xippios.usda.esmis.params` exports `AGENCIES`, the packaged agency table's acronyms with
  their titles, which `list_publications` checks an `agency_acronym` against and every answer
  names its agencies by in `meta.names`, and `PACKAGE`, the package whose `reference/` holds
  the packaged tables. `PACKAGED_LISTS` names the two tables, `agency` and `publication`,
  where it named none. (https://github.com/xippios/sdk-usda-esmis/pull/64)
- `list_releases` answers an identifier that ESMIS counts no release for with the empty list,
  `meta.total` 0 and a note in `meta.notes` that says so and names `search_publications`.
  A date filter that keeps no release writes no note, since upstream counted the releases.
  (sdk-core ADR-0061, https://github.com/xippios/sdk-usda-esmis/issues/59)
- Every answer that holds a release or a publication names its agencies by their titles in
  `meta.names`, `{"agency_acronym": {"WAOB": "World Agricultural Outlook Board"}}`, by the
  packaged agency list, and `list_publications(agency_acronym=...)` names the acronym asked
  for, also where no row matches. An acronym the list lacks is left out of the names and
  said in `meta.notes`. (https://github.com/xippios/sdk-core/issues/478)
- `usda_esmis_list_publications` takes `offset`, the rows of a cut answer already shown,
  and answers the rows after them from the packaged table. The note of every page but the
  last names the `offset` to continue with, so a caller reads the whole table, or the
  2,008 publications of `AMS`, in further calls. (https://github.com/xippios/sdk-usda-esmis/issues/34)
- The client keeps upstream's answers in core's response cache for 300 seconds, every
  path: a second call of a task within that time sends no request, and its
  `meta.retrieved_at` is the time the first answer was stored. A file that
  `download_release_file` streams is never kept. (sdk-core ADR-0061,
  https://github.com/xippios/sdk-core/issues/479)
- `list_recent_releases` names in `meta.notes` the rule that ended its walk: the first page
  whose newest release is dated more than 14 days before `since`, or the catalog's last
  page. (https://github.com/xippios/sdk-core/issues/478, https://github.com/xippios/sdk-usda-esmis/issues/29)

### Changed

- The text of `format` of `download_release_file` says that it takes the file ESMIS lists
  first, an original or a revision such as release 95622's `R1wasde-07-11-2013.pdf`, and
  that `name` reaches the others. (https://github.com/xippios/sdk-usda-esmis/issues/77)
- The description of `usda_esmis_get_release` gives a file's formats as examples, `"doc"`
  and `"asc"` among them, where it named five as the whole list, and says that an original
  or a revised file of one format can be listed first.
  (https://github.com/xippios/sdk-usda-esmis/issues/76)
- The descriptions of `usda_esmis_list_agencies`, `usda_esmis_search_publications` and
  `usda_esmis_list_releases` date no list of ESMIS by the day it was read, and the package's
  docstrings, its README and its `CLAUDE.md` cite the note of `docs/upstream/OBSERVED.md`
  that holds each probe by its heading. A test of the package holds that no probe stands
  outside the notes. (https://github.com/xippios/sdk-usda-esmis/issues/75)
- The README's `## Scope` states what of ESMIS the package wraps: seven of the twelve
  operations of its OpenAPI document, with every documented parameter an argument of a
  task but `page` of `esmis_api_publication_findAll`, whose table is packaged whole, and
  the five operations without a task, each named with its public issue. The description
  of `list_recent_releases` names ESMIS's test releases, which it returns as listed, and
  `docs/upstream/OBSERVED.md` notes them with ESMIS's own cache headers, each note with
  its probe. (sdk-core ADR-0060, https://github.com/xippios/sdk-usda-esmis/issues/32,
  https://github.com/xippios/sdk-usda-esmis/issues/59)
- The entry point's usage line and its error prefix name the command,
  `xippios-usda-esmis-mcp`, where they named the server, and the help of `--allow-remote`
  is reworded, as xippios-core 0.4.0 has them since this package's 0.3.0, whose notes left
  the change out. That release's move of the core bound to `~=0.4.0` was a breaking change.
  (https://github.com/xippios/sdk-core/issues/167, https://github.com/xippios/sdk-usda-esmis/issues/56)
- The nightly live run compares the packaged agency table with the list ESMIS serves now
  by core's comparison, and sends no probe of the base URL. The publication table, 101
  requests a fetch, is held by the reference refresh before each release. Both refresh
  scripts run on core's frames, the snapshot fetched through core's client, and the
  reference refresh sends each of its requests once.
  (https://github.com/xippios/sdk-usda-esmis/issues/36, https://github.com/xippios/sdk-usda-esmis/issues/37, https://github.com/xippios/sdk-usda-esmis/issues/38)
- Every refusal of a call as given says `Nothing was sent.` after its first sentence, the
  MCP adapter's refusal of an argument among them: an empty `query`, a `since` after
  `until`, a walk from a `since` before 2025-09-12, an `agency_acronym` the packaged list
  lacks, now checked by core's `check`, and a bad `dest`, now checked by core's
  `check_dest`. `download_release_file` refuses a call with neither `format` nor `name`
  before it looks the release up, and a choice the release cannot serve says that the
  release was read and no file requested. The refusals' classes are unchanged.
  (https://github.com/xippios/sdk-core/issues/481, https://github.com/xippios/sdk-usda-esmis/issues/33)
- `meta.retrieved_at` of every task that asks upstream is the client's time of the answer,
  the oldest where a walk reads several pages and the older of the release lookup's and the
  file's for `download_release_file`, where it read the time the answer was built.
  (https://github.com/xippios/sdk-core/issues/479, https://github.com/xippios/sdk-usda-esmis/issues/42,
  https://github.com/xippios/sdk-usda-esmis/issues/73)
- The descriptions of `usda_esmis_list_releases` and `usda_esmis_list_recent_releases` are
  their tasks' docstrings before `Args:`, each under 1,000 characters, and those of the three
  walking tools state the most requests a call spends, retries counted, as
  `download_release_file`'s docstring does. The text of each argument stands in the tool's
  input schema. (https://github.com/xippios/sdk-core/issues/485)

### Fixed

- `list_releases` with `since` returns every release that ESMIS lists from `since` on, where
  its walk ended at the first page whose oldest release was dated before `since` and missed
  the releases of the pages after it: on WASDE's recorded pages a walk from 2015-10-01
  returned 97 of the 135 releases dated from then on. The walk now ends after the first page
  whose newest release is dated before `since`, so it reads one page past the last release
  it keeps, and a walk of WASDE's releases from a `since` before 1982-02-12 is refused after
  its 24 pages, naming `page`. (https://github.com/xippios/sdk-usda-esmis/issues/67)
- The refusal of an identifier that holds a `/` names `list_publications`, which lists a
  publication's other identifiers, where it offered a lookup by id that no task has. It and
  the docstrings say that every publication but 654 has an identifier without a `/`, and it
  names its request by method and path as core's messages do.
  (https://github.com/xippios/sdk-usda-esmis/issues/26, https://github.com/xippios/sdk-usda-esmis/issues/74)
- A walk of pages keeps a release or a publication that two pages list once, as a release
  catalogued during the walk shifts the pages.
  (https://github.com/xippios/sdk-usda-esmis/issues/27)

### Removed

- `xippios.usda.esmis._client` no longer declares `API_KEY_ENV`, a key variable that no
  code read: the API is keyless, and `ENV_VARS` names what a host sets, nothing.
  (https://github.com/xippios/sdk-template/issues/300)
- `xippios.usda.esmis.errors` and `xippios.usda.esmis.enums` are removed: each held the
  template's empty `__all__` and no class or enum, since the package refuses with core's
  errors and generates no enum from its two tables.
  (https://github.com/xippios/sdk-template/issues/300)

### Breaking

- `list_releases`, `list_recent_releases` and `search_publications` refuse a page whose
  pager states another size than 25 with `InvalidRequestError` and return nothing, where
  their walks counted offsets in pages of 25 whatever the pager said. The refusal names the
  request that was sent and `page`, which reads one page as upstream pages it.
  (https://github.com/xippios/sdk-usda-esmis/issues/27, https://github.com/xippios/sdk-usda-esmis/issues/74)
- `get_publication` refuses an identifier that two publications share with
  `InvalidRequestError`, naming both ids and `search_publications`, where it returned the
  first that ESMIS answered and dropped the other. 94 identifiers of the packaged table
  belong to two publications each, `AMS_1045` among them.
  (https://github.com/xippios/sdk-usda-esmis/issues/25)
- What identifies a record stays positional and every other argument is keyword-only:
  `list_publications(*, search=None, agency_acronym=None)`, `search_publications(query, *,
  page=None)`, `list_releases(publication_identifier, *, since=None, until=None, page=None)`,
  `list_recent_releases(*, since=None, until=None, page=None)` and
  `download_release_file(release_id, *, dest, format=None, name=None)`, whose `dest` is
  required. A call that passes one of them by position raises `TypeError` before any request,
  and over MCP and HTTP nothing changes. (sdk-core ADR-0061, https://github.com/xippios/sdk-usda-esmis/issues/59)
- `list_release_files` and its tool `usda_esmis_list_release_files` are removed: `get_release`
  answers the same release from the same request, its `files` holding each file's URL, and
  `Release.release_files()` reads their names and formats in Python. An unknown release id
  raises `NotFoundError` as before. (sdk-core ADR-0061, https://github.com/xippios/sdk-usda-esmis/issues/57)
- The package depends on `xippios-core~=0.5.0`, its extras likewise, is updated to
  sdk-template v0.5.0 and applies conventions 1.30.
  (https://github.com/xippios/sdk-usda-esmis/issues/59)
- `get_latest_release` and its tool `usda_esmis_get_latest_release` are removed, by the
  boundary of a source package: a task that picks the latest release for its caller leaves.
  The same release is the first row of `list_releases(publication_identifier, page=0)`,
  a page that ESMIS lists latest first, one request as before. (sdk-core ADR-0060,
  https://github.com/xippios/sdk-core/issues/474)
- `list_releases`, `list_recent_releases` and `search_publications` walk at most 24 pages
  without `page`, 24 requests and 96 attempts with the client's retries, in Python and over
  MCP alike, and a walk that needs more is refused with `InvalidRequestError` and returns
  nothing, naming upstream's count, the bound, the requests sent, the page reached and
  `page`. No walk sends a request at or past upstream's count. `list_releases("wasde")`
  without `since`, WASDE's 703 releases on 29 pages, is refused after its first request
  where it walked every page, and `list_recent_releases` without `since`, or with `until`
  alone, is refused after one request where it was refused before any. (sdk-core ADR-0034,
  https://github.com/xippios/sdk-core/issues/480, https://github.com/xippios/sdk-usda-esmis/issues/28)
- The endpoint wrappers under `xippios.usda.esmis.api` return core's `Answer`, the parsed
  model as its `payload` beside `retrieved_at`, the time the client retrieved it, in place
  of the bare model, so a caller of a wrapper reads `.payload`. The tasks' answers keep
  their shape. (https://github.com/xippios/sdk-core/issues/479)

## [0.3.0] - 2026-11-20

### Added

- `xippios.usda.esmis.mcp.build()` returns the read-only tool set the entry point serves,
  core's `ToolSet` with the caps of `tasks.MCP_CAPS`, so a host serves the same tools beside
  other sources' in one server. `ENV_VARS`, beside `SOURCE`, names the variables the package
  reads: none, as the API is keyless. (https://github.com/xippios/sdk-core/issues/245,
  https://github.com/xippios/sdk-template/issues/81)

### Changed

- A route answers an argument that its schema refuses, a `since` that is no date or a
  missing `query`, as problem details before the task runs: HTTP 422, the title
  `InvalidRequestError` and the detail `<argument>: <message>`, where FastAPI's own 422
  listed its error details with the input. (https://github.com/xippios/sdk-core/issues/66)
- `list_publications`'s refusal of an `agency_acronym` that the packaged agency table lacks
  ends with `If upstream added it since, the packaged list is out of date.`, where it named
  the maintainers' `/refresh-reference-data`, which an agent cannot run.
  (https://github.com/xippios/sdk-core/issues/111)
- A tool's error answer sets `isError` on its result beside the text
  `error: <ErrorClass>: <message>`, so a client tells a refusal from data without reading
  the text. (https://github.com/xippios/sdk-core/issues/168)
- What the live API does that its OpenAPI document does not state moves from the README
  into `docs/upstream/OBSERVED.md`, where each note ends with the probe that showed it: its
  date, its operation and its sample. The documentation snapshot under `docs/upstream/` is
  refreshed on 2026-11-20, its OpenAPI document unchanged.
  (https://github.com/xippios/sdk-usda-esmis/issues/19)
- A refusal that names another task names its MCP tool too: an unknown identifier in
  `get_publication` and `get_latest_release` points to `search_publications` (over MCP,
  the tool `usda_esmis_search_publications`), and `list_recent_releases`'s refusal of a
  `since` before 2025-09-12 to `list_releases` (`usda_esmis_list_releases`).
  (https://github.com/xippios/sdk-core/issues/111)
- Adopts sdk-template v0.4.0, from v0.3.4, with `core_version=0.4.0`: xippios-core 0.4.0
  and its conventions 1.28. (https://github.com/xippios/sdk-template/releases/tag/v0.4.0,
  https://github.com/xippios/sdk-usda-esmis/issues/45)
- Requires `xippios-core~=0.4.0`, from `~=0.3.0`. A `dest` that core's own download
  refuses, one whose directory went away after the task's check, raises
  `InvalidRequestError`, as the task's check before the release lookup does, where core
  0.3 raised `ValueError`. (https://github.com/xippios/sdk-core/releases/tag/v0.4.0,
  https://github.com/xippios/sdk-core/issues/152)
- Adopts sdk-template v0.3.4, from v0.3.1, with conventions 1.27 and no new core minor: the
  floor stays `xippios-core~=0.3.0`, and no module or test changes. The README lists the
  documents a change follows under `## Documents`, and `CLAUDE.md` takes the place of
  `.claude/family.md`, which the update deletes, and cites sdk-core's records as
  `sdk-core ADR-NNNN`. (https://github.com/xippios/sdk-template/releases/tag/v0.3.4,
  https://github.com/xippios/sdk-usda-esmis/issues/16)
- Adopted sdk-template v0.3.1, with xippios-core 0.3.0 unchanged (conventions §15), no
  new core minor: `.github/CODEOWNERS` is rendered from the template's answers and names
  the code owner of the paths whose changes need one; `.gitignore` leaves copier's
  `*.rej` and `*.orig` out; `.claude/family.md`, `/adopt-release`, `/release-prep` and
  the PR template no longer describe how a pull request is merged.

### Breaking

- A tool refuses an argument that it does not declare before it runs, whatever its value,
  with `error: InvalidRequestError: <argument>: Not an argument of this tool` and the
  arguments it takes, where the argument was dropped and the tool ran without it.
  (https://github.com/xippios/sdk-core/issues/84)

## [0.2.0] - 2026-10-29

0.2.0 chooses a release's file by its name as well as by its format, makes the reading
of a release's files public on the models (`ReleaseFile.from_url`,
`Release.release_files()`) for the packages that depend on this one, and adds
`list_recent_releases`, what USDA released across every publication since a date. It
adopts sdk-template v0.3.0 and conventions 1.22, on xippios-core 0.3.0, the core minor
this package's 0.1.0 already required. It is a minor release for two breaking changes:
`download_release_file` refuses a `dest` left `None`, a directory or a path in a missing
directory with `InvalidRequestError` before any request, where 0.1.0 raised core's
`ValueError` for a directory or a missing directory after the release lookup (Changed),
and `params.PackagedValues` and `params.packaged_values` are gone (Removed). The
packaged reference tables were re-fetched on 2026-10-29 and found unchanged, 9 agencies
and 2522 publications as packaged on 2026-10-27, so this release ships the tables
fetched on 2026-10-27.

### Added

- `download_release_file` takes `name=`, keyword only: the file of that name as
  `list_release_files` prints it, alone or with `format`, which it must then match. A
  release that keeps an original and a revised file of one format is reached this way:
  the WASDE of 2013-08-12 (release 95621) lists `ORIGwasde-08-12-2013.xml` before
  `wasde-08-12-2013.xml`, and `format="xml"` alone takes the first. Neither `format` nor
  `name`, or a name the release lacks, raises `InvalidRequestError` naming the release's
  files. Recorded: `tests/fixtures/release_find_by_id/95621.json`.
- `ReleaseFile.from_url(url)`, the name and format an item of `Release.files` prints,
  and `Release.release_files()`, a release's files in upstream order, read without a
  request: the reading `list_release_files` and `download_release_file` use, which the
  packages that depend on this one call rather than copy.
- `list_recent_releases(since=None, until=None, page=None)` and its MCP tool
  `usda_esmis_list_recent_releases`: what USDA released across every ESMIS publication
  since a date, from `esmis_api_release_findAll`, the one operation that lists releases
  across every publication. `page` given returns that page, which `since` and `until`
  only filter; `since` without `page` walks the pages from page 0 and stops after the
  first page whose newest release is dated more than 14 days before `since`, the largest
  gap on the operation's two recorded pages between its order (highest id first) and the
  release dates. `since` and `until` keep the releases whose printed date lies between
  them. Refused with `InvalidRequestError` before any request: a call with neither
  `since` nor `page`, or with `until` alone, as the whole list is 1,542,025 releases on
  61,681 pages (2026-10-27), about 34 hours at 30 requests a minute; and a walk from a
  `since` before 2025-09-12, the date of the first WASDE release catalogued since
  ESMIS's migration, below which the ids do not follow the release dates, so a walk
  could stop early: `list_releases` lists one publication's releases in release order,
  and `page` reads older pages. The tool keeps the default cap with a note naming
  `since`, `until` and `page`. Recorded: `tests/fixtures/release_find_all/page1.json`.

### Changed

- Adopted sdk-template v0.3.0, with xippios-core 0.3.0 and conventions 1.22 (conventions §15).
- Moved the download's fixture to `tests/fixtures/download_release_file/`, the task's
  name (conventions 1.22 §10), the recording unchanged.
- Corrected the live tests' tolerance docstring, which now says the packaged tables'
  refresh opens a PR only when a table changed, and the README's status-table comment,
  which no longer names `tasks_write.__all__` (the template v0.3.0 wording for a
  read-only package).
- `download_release_file(release_id, format=None, dest=None, *, name=None)`: `format`
  and `dest` are optional in the signature, so the positional
  `(release_id, format, dest)` keeps working, and `dest` is required when called.
  Breaking: a `dest` left `None`, a directory or a path in a missing directory raises
  `InvalidRequestError` before any request, where a bad `dest` raised core's
  `ValueError` after the release lookup; `InvalidRequestError` is no `ValueError`, so a
  caller that caught `ValueError` catches `InvalidRequestError` now. `meta.request`
  holds `name` when given.
- The MCP tools `usda_esmis_list_releases` and `usda_esmis_search_publications` keep the
  default cap, 200 rows or 64 KB, with a note of their own: `list_releases`'s names
  `since`, `until` and `page`, `search_publications`'s names `page`.
- The cap's prose left the docstrings of `list_publications`, `search_publications` and
  `list_releases`, which are the tool descriptions: the cap's notes carry it.

### Removed

- `params.PackagedValues` and `params.packaged_values`, gone with the adoption of
  sdk-template v0.3.0, whose `params.py` keeps only `PACKAGED_LISTS`: they read value
  lists in the `{"param", "fetched", "values"}` files that core 0.3.0's `PackagedList`
  replaced, and since `PACKAGED_LISTS` was empty, `packaged_values` answered `None` for
  every name. `params.PACKAGED_LISTS` stays, empty. The two packaged tables are
  `PackagedList` files that `tasks.py` reads with `PackagedList.load`: a caller reads
  the publications through `list_publications`, without a request, the agencies through
  `list_agencies`, which asks upstream, and either table as packaged with
  `PackagedList.load("xippios.usda.esmis", "publication")` or `"agency"`.

## [0.1.0] - 2026-10-27

### Added

- Scaffold from [sdk-template](https://github.com/xippios/sdk-template): configured
  client for USDA ESMIS, MCP server and FastAPI router wired to the task layer, test
  harness with core's family check, CI, the nightly live tests and the release train,
  in which a release PR's merge tags and publishes.
- Upstream documentation snapshot in `docs/upstream/`, fetched 2026-10-27, and its
  capture script `scripts/refresh_upstream.py`: the ESMIS OpenAPI document verbatim,
  the WASDE publication page and its newest release's page as Markdown, and an excerpt
  of the release calendar, with `FETCHED.md` recording every fetch.
- README and CLAUDE.md name ESMIS in full; the README lists where the live API deviates
  from its OpenAPI document, as probed on 2026-10-27.
- Attribution: the README and `docs/upstream/FETCHED.md` state that the ESMIS
  documentation and release files are works of the United States Government, in the
  public domain in the United States (17 U.S.C. § 105), and cite USDA's policy page.
- Endpoint wrappers for the twelve operations of the ESMIS catalog (agencies,
  publications, releases) under `xippios.usda.esmis.api`, the models `Agency`, `Pager`,
  `Publication`, `Release`, `PublicationResults` and `ReleaseResults` typed as the wire
  sends them, with the `StrEnum`s `Status`, `Subscribable` and `ResourceType` that a walk
  of every publication page confirmed, and the client's `classify`: an unknown id, which
  the four lookups by id answer with HTTP 404, is `NotFoundError`, and an identifier
  carrying `/`, which ESMIS refuses, `InvalidRequestError`; the lookups by acronym or
  identifier answer an unknown one with an empty HTTP 200, returned as such. Recorded
  fixtures and replay tests in `tests/test_api.py`; CLAUDE.md gains the ESMIS specifics.
- Seven catalog tasks, each an MCP tool and an HTTP route: `list_agencies`,
  `search_publications` and `get_publication`, `list_releases` (newest first, with
  `since`, `until` and `page`), `get_release`, `get_latest_release` and
  `list_release_files` (each file's URL, name and format, the model `ReleaseFile`).
  `meta.endpoint` names the operationId, `meta.total` upstream's count for the paged
  lists, `meta.vintage` the release id; `meta.published_at` of a task about one release
  is its `release_datetime` as printed, the `+0000` dropped, with `published_at_naive`
  set (ADR-0022). An unknown identifier raises `NotFoundError` where one record is asked
  for and gives the empty list from `list_releases`.
- `download_release_file(release_id, format, dest)`, a bulk task in `BULK_TASKS`,
  Python only: it streams one file of a release to the path the caller names with
  core's `download`, nothing cached, `meta.endpoint` the file's name as upstream prints
  it (`wasde1026.txt`), `meta.published_at` the release's printed time with the flag.
  Replay tests for every task, the tools called end to end, the October 2026 WASDE
  `.txt` recorded whole for the download's replay, and live tests for every task and
  for the release order the release tasks rely on.
- Two packaged reference tables, written by `scripts/refresh_reference.py` with core's
  `PackagedList.write` on 2026-10-27: `reference/publication.json`, the 2522
  publications of every page of `/publication/findAll`, each the eight columns of the
  new projection `PublicationRow`, and `reference/agency.json`, the 9 agencies with every
  field.
- `list_publications(search=None, agency_acronym=None)`, an MCP tool and an HTTP route
  answered from the packaged publication table without a request: `search` matches the
  id, an identifier or the title (core's `matches`), `agency_acronym` an acronym the row
  lists, and an acronym the packaged agency table lacks is refused with core's
  `UnknownCode`, naming the closest. `meta.retrieved_at` is the table's fetch time and
  `meta.endpoint` `esmis_api_publication_findAll` (ADR-0022). Its MCP tool keeps the
  default cap, 200 rows or 64 KB, with a note naming the two filters, since the whole
  table is 599,402 bytes; Python and HTTP callers get the whole table (ADR-0016). Live
  tests compare the packaged agencies and the publication count with upstream.

### Changed

- `xippios-core` 0.3.0 from PyPI (`core_version` 0.3.0, `~=0.3.0`; template v0.2.2),
  which brings the api.data.gov gateway module (C14, unused by this keyless source),
  `AsyncClient.download` for bulk files (C15, ADR-0019) and ADR-0022's
  `ResultMeta.published_at_naive`, which the release tasks need.
- `scripts/refresh_reference.py` refreshes the two packaged tables through `api/` (102
  requests: the agencies and the 101 publication pages, bounded by `total_pages`) and
  rewrites the provenance rows of `reference/README.md`; it generates no `enums.py`, and
  `params.PACKAGED_LISTS` is empty, since the tables are `PackagedList` files that
  `tasks.py` reads directly.
