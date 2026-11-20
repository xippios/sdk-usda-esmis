# sdk-usda-esmis — instructions for Claude Code

`xippios-usda-esmis` wraps USDA ESMIS, the Economics, Statistics, and Market Information
System of USDA's National Agricultural Library, as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file holds what an agent needs to work on
the package: what it wraps, its layout, its commands and its code rules. The documents it
follows, sdk-core's conventions among them, are listed under
[`## Documents` in the README](README.md#documents); read them before you change a file.

## What this package wraps

| | |
| --- | --- |
| Upstream | USDA ESMIS (Economics, Statistics, and Market Information System), https://esmis.nal.usda.gov |
| API base URL | `https://esmis.nal.usda.gov` |
| Documentation | https://esmis.nal.usda.gov/api-documentation, snapshotted in `docs/upstream/` |
| Credentials | none; the API is open |
| Rate limit | 30 requests per minute, burst 1; a self-imposed pace, upstream documents none (sdk-core ADR-0033); enforced client-side in `_client.py` |
| Write tools | no, this package is read-only |

The snapshot listed in `docs/upstream/FETCHED.md` is the reference for names, parameters and
semantics; a wrapper is never written from memory of the API.

## Layout

```
src/xippios/usda/esmis/
  __init__.py      public surface: __version__ and re-exported task functions
  py.typed         PEP 561 marker; consumers' mypy --strict needs it
  _version.py      __version__ from distribution metadata
  _client.py       the one configured AsyncClient (base URL, rate limit), ENV_VARS and
                   classify, upstream's documented error shapes
  errors.py        the package's own error classes, where conventions §5 calls for one
  models.py        pydantic models mirroring upstream payloads (UpstreamModel); by the
                   family's precedent also an enumeration written by hand, for a value set
                   upstream documents and no packaged list renders
  api/             endpoint wrappers, one module per upstream operation (conventions §2)
  tasks.py         task functions; __all__ minus BULK_TASKS is what the adapters
                   register, MCP_CAPS any per-tool result caps
  mcp.py           xippios-usda-esmis-mcp entry point: build() the tool set, server
  http.py          FastAPI router
  params.py        packaged value lists: PACKAGED_LISTS, empty here; the packaged tables
                   are PackagedList files tasks.py reads
  enums.py         no enum: no packaged value list, nothing generated; the document's
                   enums are in models.py; a value list packaged later renders here
                   through core's render_enums
  reference/       publication.json and agency.json, PackagedList files, plus README with
                   provenance
scripts/
  refresh_reference.py   fetches agency/findAll and every page of publication/findAll
                         through api/ and writes reference/agency.json and
                         reference/publication.json with PackagedList.write (102 requests)
  refresh_upstream.py    captures docs/upstream/ and writes FETCHED.md (/refresh-upstream)
  adr_index.py           writes docs/adr.md and docs/adr.json from the records in docs/adr/;
                         --check fails while either is stale
tests/
  conftest.py      enables xippios.core.testing.plugin, which keeps the run offline
  fixtures/        recorded responses, <wrapper>/<case>.json (conventions 1.22 §10),
                   never hand-written; a recording made through a task sits under the
                   task's name (download_release_file/)
  test_family.py   core's family check, one line: namespace levels, py.typed, __version__,
                   the adapters serving exactly the tasks, task shapes and docstrings, the
                   README status table, the template tag, the core bound
  test_api.py      replay tests for the endpoint wrappers, one or more per operation
  test_tasks.py    per-task replay tests, every tool called through the MCP server, the
                   bulk task's absence from the server and the router
  test_live.py     @pytest.mark.live smoke tests, one per task, the release-order check,
                   the packaged agency table against upstream, the current WASDE .txt
                   downloaded into a temporary directory
  test_refresh_upstream.py   FETCHED.md as the capture script renders it, offline, with
                   the row of OBSERVED.md, which a snapshot leaves as written
  test_observed.py docs/upstream/OBSERVED.md as committed: its row in FETCHED.md, a probe
                   ending every note, and the fixtures the notes cite
docs/
  upstream/        documentation snapshot, FETCHED.md, and OBSERVED.md, the notes written by
                   hand on what upstream does but never documents
  adr/             this package's design decisions, one NNNN-<slug>.md record each, laid
                   out in its README.md
  adr.md           the index of the decisions, written by scripts/adr_index.py, never by hand
  adr.json         the same index, for machines
  reports/         dated reports, the evidence a decision cites, laid out in its README.md
changelog/         the next release's changelog entries, one fragment per change, laid out
                   in its README.md
CHANGELOG.md       the releases, each section assembled from the fragments
.github/workflows/ ci.yml (the required ci check, with the changelog and fixture-size steps),
                   publish.yml (the release train: tag, build, PyPI), live.yml (nightly live
                   tests), organization.yml (the organization's checks from xippios/.github:
                   conventions, a review of a pull request against the documents the README
                   lists, and adr-index, which runs scripts/adr_index.py --check),
                   siblings.yml (the sibling proof of sdk-core ADR-0006: this wheel beside the
                   siblings under xippios.usda, a visible check the ruleset does not require)
.github/scripts/   check-siblings.sh, which siblings.yml runs; the template's, as is the workflow
.claude/commands/  add-endpoint, record-fixture, refresh-upstream, refresh-reference-data, release-prep
```

The import path is `xippios.usda.esmis` (sdk-core ADR-0006); `src/xippios/` is a
namespace package, and so is `src/xippios/usda/`, the provider level.
Where the API's operation ids repeat across its services, `api/` keeps one module per service
instead, named after the service, and this Layout says so (conventions §2).

## Commands

```bash
uv sync --all-extras
uv run pytest                      # offline, replays the fixtures
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit run --all-files
python3 scripts/adr_index.py --check   # the index matches the records in docs/adr/
uv run pytest -m live --tb=short --assert=plain   # needs XIPPIOS_LIVE_TESTS=1

uv run xippios-usda-esmis-mcp   # stdio; add --http for streamable HTTP
```

`uv run pytest` is offline: core's plugin refuses the network and skips the rate limiter's
waits in every test not marked `live` (conventions §10, sdk-core ADR-0035). A test that
asserts a limiter wait or a quota pause is marked `rate_limited`, one that must reach the
network `network`.

`.github/workflows/live.yml` runs the live tests nightly at 01:27 UTC, a time derived from
the slug, and on demand; a pull request never runs them.
Its `uv run pytest -m live --tb=short --assert=plain` step reads no secret: the API needs no
key.
Every live run takes `--tb=short --assert=plain`, since the log of `live.yml` is public:
the first keeps a failing test's frame arguments out of it, a raw upstream payload among
them, and the second the values a failed `assert` compares. A live test asserts on shapes
and counts, never on a raw payload.

## Code rules

- Three layers (sdk-core ADR-0001, conventions §2): endpoint wrappers in `api/`, task
  functions in `tasks.py`, adapters in `mcp.py` and `http.py`. The adapters register
  `tasks.__all__` and call only tasks, the tasks call only wrappers and reference data, and
  a wrapper returns models.
- Upstream's documented error shapes go into `classify` in `_client.py`, once, and an error
  class of the package's own into `errors.py`; a wrapper never inspects a status code
  (conventions §5, §6).
- One limiter paces each host the package sends to (conventions §2, §6). A second base URL
  on the host of the API base URL goes through the one `client` of `_client.py` by its
  absolute URL, and `classify`'s path checks name both bases. An origin or mirror that the
  publisher runs itself, where its canonical host refuses automated requests, takes that
  host's pace through the same client, and `docs/upstream/` names both hosts; a mirror that
  anyone else runs is never sent to. A host that a dependency sends to is reached through
  the dependency's tasks alone. Any other host gets a client of its own in `_client.py`,
  its base URL and its `RateLimit` beside the first's, and a row of its own in the table
  under What this package wraps, with its pace and where the pace comes from.
- A change brings its tests, written before the code, and passes the offline checks above;
  its changelog entry is a fragment under `changelog/`, one file holding its bullet, as
  `changelog/README.md` lays it out (conventions §12). Commit subjects follow Conventional
  Commits (conventions §13): the rule binds a pull request's own commits, not the commit
  that lands the pull request on `main`, whose subject GitHub writes.
- `ruff` leaves `docs/` and `.claude/` alone (`pyproject.toml`), so the upstream snapshot
  keeps its bytes: never reformat it.
- A convention that seems wrong is followed anyway and said in the pull request; changing
  it is a change of sdk-core's `docs/conventions.md` with an ADR.

## Never

- Never hand-write a fixture, and never commit one without grepping it for key patterns
  (conventions §10).
- Never read or print `.envrc`, `.env`, or any variable ending in `_API_KEY`, `_TOKEN`
  or `_SECRET`.
- Never write a key, a token or another credential into a file or a commit.
- Never put logic in `mcp.py` or `http.py`, and never add a route or a tool by hand: the
  adapters register `tasks.__all__` (sdk-core ADR-0001).
- Never rename or re-map an upstream concept to another source's (sdk-core ADR-0028).
- Never return a documented personal identifier in a task's projection, echo one in
  `meta.request`, or commit one in a fixture (sdk-core ADR-0017).
- Never edit `docs/upstream/` by hand but `docs/upstream/OBSERVED.md`, the notes on what
  upstream does but never documents: `/refresh-upstream` fetches the rest, and the pull
  request shows its diff (conventions §3).
- Never add `src/xippios/__init__.py`, nor an `__init__.py` at a level between it and the
  package (sdk-core ADR-0006).
- Never push a tag by hand: a release's tag comes from `publish.yml` alone (conventions §12).

## Template updates

This repository is generated from sdk-template, at the tag `.copier-answers.yml` records. A
template release reaches it in a pull request of its own, with
`uvx --from 'copier>=9.19' copier update --defaults --vcs-ref=<tag>` (conventions §15): the
update renders the template's files again and never overwrites the files this package
fills, `__init__.py`, `_client.py`, `errors.py`, `models.py`, `api/`, `parse/`, `tasks.py`,
`tasks_write.py`, `params.py`, `enums.py`, `reference/`, `scripts/refresh_reference.py`,
`scripts/refresh_upstream.py`, `tests/test_tasks.py`, `tests/test_live.py`,
`tests/fixtures/`, `docs/upstream/`, `docs/adr.md`, `docs/adr.json`, `README.md`,
`CHANGELOG.md` and `CLAUDE.md`. sdk-template's
[CHANGELOG](https://github.com/xippios/sdk-template/blob/main/CHANGELOG.md) says, per
release, what to port into those by hand in the same pull request.

## When something is unclear

Prefer the smallest change that satisfies the documents the README lists, state the
assumption in the pull request's description, and stop rather than guess at upstream
semantics or the shape of the public API.

## ESMIS specifics

- **Reference.** `docs/upstream/openapi/esmis_public_api.yaml` (OpenAPI 3.0.0, twelve
  GET operations) is the reference for operation names, paths, parameters and schema
  names. Where the live API answers differently, the wire wins for types;
  `docs/upstream/OBSERVED.md` lists the differences, each with the probe that showed it,
  and `models.py` and `tests/fixtures/` show them.
- **Wrappers.** Every operation sits under `/api/v1/` on `https://esmis.nal.usda.gov`. A
  module and its function are the operationId snake_cased without the constant
  `esmis_api_` prefix (`esmis_api_release_findByPubId` is `api.release_find_by_pub_id`),
  since `xippios.usda.esmis.api` already is that namespace; the tasks name the full
  operationId in `meta.endpoint`. Path parameters are quoted whole (`safe=""`); the id
  parameters are integers, as the document types them, while every `id` in an answer is
  a string. Release `files` are absolute URLs on the same host.
- **Pagination.** `page` is 0-based with 25 items a page, a size no documented parameter
  changes; `pager.total_results` is upstream's count, the value for `meta.total`
  (sdk-core ADR-0034). A page past the last answers empty `results` with `current_page`
  clamped to the last page. `publication_search` with an empty `query` answers
  `"pager": []`, which `PublicationResults.pager` takes as `()`.
- **Order**, observed, not documented. `/release/findAll` lists the highest id first.
  Since ESMIS's migration, whose first WASDE release is 791996 of 2025-09-12, the ids
  follow creation: the newest created first, not the newest released. On findAll's two
  recorded pages (page 0 of 2026-10-27 runs 2026-10-26, 2026-10-09, 2026-10-23, page 1
  of 2026-10-28 runs 2026-10-09, 2026-09-28, 2026-10-07) the largest gap between that
  order and the dates is 14 days, release 796123 against 796122. Below the migration the
  ids, 96171 and lower for WASDE, do not follow the dates: WASDE's 96165 to 96171 run
  May, April, March, February, August, July and June 2025, 95482 to 95486 rise while the
  dates fall, and 95511 (2022-08-12) and 95621 (2013-08-12) sit above 95482
  (2025-01-10). `list_recent_releases` walks the new ids only: it takes the 14 days as
  its tolerance (`tasks.ORDER_TOLERANCE`) and refuses a walk from a `since` before
  2025-09-12 (`tasks.CATALOG_ORDER_SINCE`); the order beyond findAll's two pages is read
  from the WASDE recordings, not probed, and the live test checks the id order of page 0
  nightly. Within a publication ESMIS lists the releases latest `release_datetime`
  first, whatever their ids, as recorded on WASDE's pages 0 and 1
  (`release_find_by_identifier/wasde_page0.json`, `wasde_page1.json`). `list_releases`
  and `get_latest_release` rely on that order and say so in their docstrings; the live
  test `test_page_zero_of_a_publication_is_newest_first` checks it nightly. Publication
  lists follow no id order.
- **The publication walk** (2026-10-27, `/publication/findAll` pages 0 to 100, 101
  calls): 2522 publications, ids distinct strings of digits, every `Publication` field
  on all of them but `publication_agency_export_1` (on none). `status`, `subscribable`
  and `resource_type` hold only the document's values and are `StrEnum`; `frequency`
  stays `str`, since publication 1172 prints `""`. 24 publications list
  `upcoming_releases`, 67 times in all, each with an Eastern offset.
- **Absence and refusals** (`_client.classify`), as recorded per lookup. An unknown id
  answers HTTP 404 `{"message": ""}`, raised as `NotFoundError`, at `agency/findById`,
  `publication/findById`, `release/findById` and `release/findByPubId`. An unknown name
  answers HTTP 200 with nothing: `agency/findByAcronym` an empty array,
  `publication/findByAgency`, `publication/findByIdentifier` and
  `release/findByIdentifier` empty `results` with every pager count 0. The wrappers
  return those as such; the tasks that return one record raise `NotFoundError` for them
  (`get_publication`, `get_latest_release`; `get_release` through `classify`), and
  `list_releases`, a list task, returns the empty list with `meta.total` 0. An
  identifier carrying `/` (`Market and Trade Economics Division/FDS`) cannot be looked
  up: ESMIS's web server refuses `%2F` with an HTML 404, raised as
  `InvalidRequestError`, and a raw slash is no route; the publications recorded with one
  carry another identifier without it (`FDS`).
- **Release times.** The API prints `release_datetime` with `+0000`, but upstream's own
  calendar and file times put the release at noon Eastern (`docs/upstream/OBSERVED.md`,
  the zone label of release times),
  and `Publication.upcoming_releases` print Eastern offsets (`2026-10-28T15:00:00-0400`,
  `2026-11-04T15:00:00-0500`), which the model keeps. Decided by Johannes on 2026-10-27:
  `Release.release_datetime` keeps the time as printed, an aware datetime at `+00:00`;
  the four tasks about one release (`get_release`, `get_latest_release`,
  `list_release_files`, `download_release_file`) set `meta.published_at` to that time
  with the offset dropped (`.replace(tzinfo=None)`, the printed wall-clock time, never
  converted) and `published_at_naive=True` (sdk-core ADR-0041, decision 2); the list tasks
  leave it empty. `meta.vintage` is the release id.
- **Tasks.** Ten: eight are the contract of `xippios-usda-wasde` (sdk-core ADR-0021),
  `list_publications` answers from the packaged table (next item), and
  `list_recent_releases` lists every publication's releases from
  `esmis_api_release_findAll`. A paged task given `page` returns that page; without it,
  `tasks._Pages` walks the pages from 0 with core's `paginate_offset`
  (`page = offset // 25`), bounded by the last answer's `pager.total_pages`, an empty or
  a short page, for `list_releases` the first page whose oldest release is dated before
  `since`, and for `list_recent_releases` the first page whose newest release is dated
  more than 14 days (`tasks.ORDER_TOLERANCE`, the largest gap on findAll's two recorded
  pages) before `since`, as its dates only mostly follow the id order (Order, above);
  never by the echoed `current_page`. `list_recent_releases` walks only from a `since`
  on or after 2025-09-12 (`tasks.CATALOG_ORDER_SINCE`, ESMIS's migration; Order, above):
  an older `since` without `page` is refused with `InvalidRequestError` before any
  request, naming `list_releases` and `page`, and so is a call with neither `since` nor
  `page`, or with `until` alone, as a walk of every release is 61,681 pages, about 34
  hours (decided by Johannes on 2026-10-28; sdk-core ADR-0007). With `page` given,
  `since` and `until` only filter that page, whatever their dates. `list_releases` and
  `list_recent_releases` filter `since` and `until` on the printed date of
  `release_datetime`, never converted, and their `meta.total` is upstream's count before
  that filter. `get_latest_release` takes the latest `release_datetime` of page 0, never
  the highest id. `meta.request` omits what the caller left `None`. Every tool keeps the
  default cap (200 rows or 64 KB); `MCP_CAPS` gives four tools a note of their own that
  names their parameters for seeing the rest (sdk-core ADR-0038, conventions §8):
  `list_publications` (next item), and the three the default can cut when called without
  `page`, `list_releases` (703 rows for WASDE; its note names `since`, `until` and
  `page`), `list_recent_releases` (about 0.46 KB a release, so after some 140 rows; its
  note names `since`, `until` and `page`) and a broad `search_publications` (about
  1.8 KB a publication, so after some 36 matches; its note names `page`). The notes
  carry the cap, so the task docstrings, which are the tool descriptions, never state it
  (sdk-core's handover, "Adopting core 0.3.0").
- **The packaged tables.** `reference/publication.json` (2522 publications, each the
  eight columns of `PublicationRow`, a projection of `Publication`) and
  `reference/agency.json` (9 agencies, every field) are `PackagedList` files, written by
  `scripts/refresh_reference.py` with `PackagedList.write`, never by hand; `fetched` is
  the UTC time of each table's first request. `list_publications` answers from them
  without a request, `meta` from `PackagedList.meta` (`retrieved_at` the table's
  `fetched`, `endpoint` `esmis_api_publication_findAll`, sdk-core ADR-0041), and refuses
  an `agency_acronym` the agency table lacks with core's `UnknownCode`; `list_agencies`
  stays live. Decided by Johannes on 2026-10-27: its MCP tool keeps the default cap, 200
  rows or 64 KB, with a note naming `search` and `agency_acronym` and that Python and
  HTTP callers get the whole table; unfiltered the result is 599,402 bytes of compact
  JSON, about 150k tokens, so an agent filters it, as with sdk-comtrade's HS list, and is
  never served it whole (sdk-core ADR-0038). No enum is generated from the tables
  (`enums.py` holds none, the document's enums are hand-written in `models.py`) and
  `params.PACKAGED_LISTS` stays empty. The template's `/refresh-reference-data` command
  (v0.3.0) puts a table in the script's `TABLES` and its name in `PACKAGED_LISTS`;
  ESMIS's own script has neither, renders no enum and leaves `PACKAGED_LISTS` empty
  (queue row 101); its docstring is the recipe for this package. The refresh budget:
  102 keyless requests (the agencies, then
  `/publication/findAll` pages 0 to 100, bounded by `total_pages`) at 30 a minute, about
  four minutes, run once before each release and committed in a refresh PR of its own
  when a table changed, none when both are unchanged (conventions §12; decided by
  Johannes on 2026-10-27); the script refuses to write a walk whose pages disagree.
  The nightly live tests compare the agency table with upstream and the publication
  count within a page.
- **A catalog, never a parser** (sdk-core ADR-0020). This package lists publications,
  releases and their files, and downloads a file; it never parses one. Parser packages
  such as `xippios-usda-wasde` depend on its tasks and models, never on `api/` or
  `_client` (sdk-core ADR-0021). `download_release_file` is its one bulk task, named in
  `BULK_TASKS` (written by hand, as the template renders it from v0.3.0) and skipped by
  core's `tool_functions` and `router_from_tasks` (sdk-core ADR-0040): it streams one file
  with core's `download` to the path the caller names, `meta.endpoint` the file's name as
  upstream prints it (sdk-core ADR-0020, amendment 2026-11-18, point c); nothing is stored
  or cached. Its signature is `(release_id, format=None, dest=None, *, name=None)`, so the
  positional `(release_id, format, dest)` that `xippios-usda-wasde` sends keeps working.
  `dest` is required and checked before any request: `None`, a directory or a path in a
  missing directory is `InvalidRequestError`, the last two in the words core's `download`
  refuses them with, which it does only after the release lookup. The file is chosen by
  `name` alone (the file of that name), `format` alone (the first of that format in
  upstream order) or both (the named file, which must be of that format); neither, or an
  unknown name, is `InvalidRequestError` naming the release's files, and a name of another
  format one naming its format. A release with an original and a revised file of one
  format (95621, the WASDE of 2013-08-12, lists `ORIGwasde-08-12-2013.xml` before
  `wasde-08-12-2013.xml`) is reached by `name` (decided by Johannes on 2026-10-28). A
  release's files are `Release.release_files()`, `ReleaseFile.from_url` on each URL, in
  upstream order: the reading a dependent calls rather than copies (sdk-core ADR-0021).
  The download budget: one small file, the current WASDE `.txt` (about 120 KB), for the
  fixture (`download_release_file/wasde1026_txt.json`, recorded whole) and for the nightly
  live test, which writes it to a temporary directory.
- **Core.** The package depends on `xippios-core` 0.4.0 from PyPI (`core_version`
  0.4.0, `~=0.4.0`; template v0.4.0), which carries sdk-core ADR-0040's `download`, its
  refusal of a bad `dest` and the `BULK_TASKS` skip, sdk-core ADR-0041's
  `published_at_naive`, and the package contract of sdk-core ADR-0026 that `mcp.py`
  builds, `build()` and `ENV_VARS`.
