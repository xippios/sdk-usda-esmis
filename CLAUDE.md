# sdk-usda-esmis — instructions for Claude Code

`xippios-usda-esmis` wraps USDA ESMIS, the Economics, Statistics, and Market Information
System of USDA's National Agricultural Library, as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file holds what an agent needs to work on
the package: what it wraps, its layout, its commands and what only it knows. The documents it
follows, sdk-core's conventions among them, are listed under
[`## Documents` in the README](README.md#documents); read them before you change a file. The
rules that no change breaks stand in `.claude/rules/never.md`, which Claude Code loads with
this file.

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

What this package adds to the family's tree, and its import path, stand in `docs/layout.md`,
imported here:

@docs/layout.md

## Commands

```bash
uv sync --all-extras
uv run pytest                      # offline, replays the fixtures
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit run --all-files
python3 -I scripts/adr_index.py --check   # the index matches the records in docs/adr/
uv run pytest -m live --tb=short --assert=plain   # needs XIPPIOS_LIVE_TESTS=1

uv run xippios-usda-esmis-mcp   # stdio; add --http for streamable HTTP
```

`.github/workflows/live.yml` runs the live tests nightly at 01:27 UTC, a time derived from
the slug, and on demand; a pull request never runs them.
Its `uv run pytest -m live --tb=short --assert=plain` step reads no secret: the API needs no
key.
Every live run takes `--tb=short --assert=plain`, since the log of `live.yml` is public:
the first keeps a failing test's frame arguments out of it, a raw upstream payload among
them, and the second the values a failed `assert` compares. A live test asserts on shapes
and counts, never on a raw payload.

## Template updates

This repository is generated from sdk-template, at the tag `.copier-answers.yml` records. A
template release reaches it in a pull request of its own, with
`uvx --from 'copier>=9.19' copier update --defaults --vcs-ref=<tag>` (conventions §15). The
update never overwrites a file this package fills, those that `_skip_if_exists` lists in
sdk-template's [`copier.yml`](https://github.com/xippios/sdk-template/blob/main/copier.yml),
and sdk-template's
[CHANGELOG](https://github.com/xippios/sdk-template/blob/main/CHANGELOG.md) says, per
release, what to port into those by hand in the same pull request.

The update writes every other file it renders again, since they are the template's,
`.claude/rules/never.md` among them. This package keeps no text of its own in them, the
docstring of `mcp.py` included: its own words go into a file it fills. A line it has to
add to one, such as a dependency in `pyproject.toml`, the update carries into the new
render, silently where the release leaves the lines around it alone and as a conflict
where it changes them.

## ESMIS specifics

- **Reference.** `docs/upstream/openapi/esmis_public_api.yaml` (OpenAPI 3.0.0, twelve
  GET operations) is the reference for operation names, paths, parameters and schema
  names. Where the live API answers differently, the wire wins for types, and
  `models.py` and `tests/fixtures/` show it. What ESMIS does that the document does not
  state stands in `docs/upstream/OBSERVED.md` once, each note with the probe that showed
  it: the wire's types, the absence answers, the identifiers with a `/` or of two
  publications, the pages, the order of the catalog, the release times, the files, the
  cache headers and the test releases. This section holds what the package does with it
  and cites a note by its heading.
- **Wrappers.** Every operation sits under `/api/v1/` on `https://esmis.nal.usda.gov`. A
  module and its function are the operationId snake_cased without the constant
  `esmis_api_` prefix (`esmis_api_release_findByPubId` is `api.release_find_by_pub_id`),
  since `xippios.usda.esmis.api` already is that namespace; the tasks name the full
  operationId in `meta.endpoint`. Path parameters are quoted whole (`safe=""`); the id
  parameters are integers, as the document types them, and the models keep each `id` of
  an answer a string ("Every `id` is a string").
- **Pagination.** `tasks.PAGE_SIZE` is 25, a size no documented parameter changes ("A page
  holds 25 items, and a page past the last is empty"), and `pager.total_results` is
  upstream's count, the value for `meta.total` (sdk-core ADR-0034).
  `PublicationResults.pager` takes the `"pager": []` of a search without a query as `()`
  ("`/publication/search` without a query").
- **Order.** `list_recent_releases` walks `/release/findAll` in its id order and takes the
  largest gap between that order and the dates on the two recorded pages, 14 days, as its
  tolerance (`tasks.ORDER_TOLERANCE`), and it refuses a walk from a `since` before
  2025-09-12, ESMIS's migration, below which the ids do not follow the dates
  (`tasks.CATALOG_ORDER_SINCE`; "`/release/findAll` lists the highest id first"). The order
  beyond the two pages is read from the WASDE recordings, not probed, and the live test
  checks the id order of page 0 nightly. `list_releases` relies on a publication's
  releases coming latest first ("A publication's releases come latest first") and says so
  in its docstring: the first row of its `page=0` is the publication's latest release; the
  live test `test_page_zero_of_a_publication_is_newest_first` checks it nightly.
- **Enumerations.** `status`, `subscribable` and `resource_type` of `Publication` are
  `StrEnum`s written by hand in `models.py`, which
  `test_the_enumerations_written_by_hand_follow_the_document` holds against the
  document's `enum`; `frequency` stays `str` ("`frequency` outside its enumeration").
- **Absence and refusals** (`_client.classify`, "Absence answers differ per lookup"). An
  unknown id's HTTP 404 is `NotFoundError`; the empty answer to an unknown name the
  wrappers return as such. `get_publication` raises `NotFoundError` for an identifier
  ESMIS does not know, and `InvalidRequestError` for one that two publications share,
  naming both ids and `search_publications` ("An identifier that two publications share
  answers both"); `get_release` raises through `classify`; and `list_releases`, a list
  task, returns the empty list with `meta.total` 0 and a note that names
  `search_publications`. The web server's HTML 404 for a path with `%2F` is
  `InvalidRequestError`, whose message names `list_publications`, since every publication
  but 654 has an identifier without a `/` ("An identifier carrying `/` cannot be looked
  up"); the README's `## Scope` names the lookup by publication id that would reach 654
  (https://github.com/xippios/sdk-usda-esmis/issues/22).
- **Release times** ("The zone label of release times"). As
  https://github.com/xippios/sdk-usda-esmis/pull/5 decided, `Release.release_datetime`
  keeps the time as printed, an aware datetime at `+00:00`, and
  `Publication.upcoming_releases` keep their Eastern offsets; the two tasks about one
  release (`get_release`, `download_release_file`) set `meta.published_at` to that time
  with the offset dropped (`.replace(tzinfo=None)`, the printed wall-clock time, never
  converted) and `published_at_naive=True` (sdk-core ADR-0041, decision 2); the list tasks
  leave it empty. `meta.vintage` is the release id.
- **Tasks.** Eight, `tasks.__all__`. `xippios-usda-wasde` 0.2.0 calls three tasks of
  0.3.0, `list_releases` and `download_release_file`, which stay, and
  `get_latest_release`, which 0.4.0 removed with the tasks that pick the latest release
  (sdk-core ADR-0060, decision 8), and reads `Release.release_files()` and `ReleaseFile`
  (sdk-core ADR-0021); a change of what it calls or reads breaks it. What identifies a
  record is positional, in the order of upstream's path, and every other argument is
  keyword-only (https://github.com/xippios/sdk-usda-esr/issues/60, part 1):
  `list_publications(*, search=None, agency_acronym=None)`,
  `search_publications(query, *, page=None)`, `get_publication(publication_identifier)`,
  `list_releases(publication_identifier, *, since=None, until=None, page=None)`,
  `list_recent_releases(*, since=None, until=None, page=None)`, `get_release(release_id)`
  and `download_release_file(release_id, *, dest, format=None, name=None)`. A paged task
  given `page` returns that page; without it, core's `fetch_pages` walks the pages from 0
  (`page = offset // 25`) under one bound, `tasks.WALK_PAGES`, 24 pages, for Python and
  MCP alike (sdk-core ADR-0034, amendment 2026-11-24;
  https://github.com/xippios/sdk-cashctrl/issues/135, part 4), and upstream's count, never
  the echoed `current_page`: a walk ends at a short page, at upstream's count, for
  `list_releases` after the first page whose oldest release is dated before `since`, and
  for `list_recent_releases` after the first page whose newest release is dated more than
  `tasks.ORDER_TOLERANCE` before `since` (Order, above); the two stop rules are passed
  only where `since` is given. A walk that needs more than 24 pages is refused with core's
  `InvalidRequestError`, naming the count, the bound and `page`: after its first request
  where upstream's count shows it, as for `list_releases("wasde")` without `since`, and
  `list_recent_releases` without `since`, or with `until` alone, and after its 24th where
  a walk from `since` reaches no page that ends it within them. Each walk drops a release
  or a publication that two pages list, and refuses a page whose `pager.items_per_page`
  is not 25 (https://github.com/xippios/sdk-usda-esmis/issues/27), and
  `list_recent_releases` names in `meta.notes` the rule that ended its walk.
  `list_recent_releases` walks only from a `since` on or after
  `tasks.CATALOG_ORDER_SINCE`: an older `since` without `page` is refused with
  `InvalidRequestError` before any request, naming `list_releases` and `page` (decided in
  https://github.com/xippios/sdk-usda-esmis/pull/11). With `page` given, `since` and
  `until` only filter that page, whatever their dates. `list_releases` and
  `list_recent_releases` filter `since` and `until` on the printed date of
  `release_datetime`, never converted, by the package's own `tasks._between`, since core
  holds no filter that keeps its bounds' days, and their `meta.total` is upstream's count
  before that filter. Every refusal before the first request says `Nothing was sent.`, and
  one after the release lookup says that the release was read and no file requested
  (conventions §5). `meta.request` omits what the caller left `None`.
- **The cache.** The client keeps upstream's answers in core's response cache for its
  default 300 s, every path (sdk-core ADR-0061, decision 11), so a second call within that
  time sends nothing and its `meta.retrieved_at` is when the first answer was stored; a
  file that `download_release_file` streams is never kept. Most of ESMIS's own answers
  allow a cache an hour ("Answers carry ESMIS's own cache headers").
- **The caps.** Every tool keeps the default cap (200 rows or 64 KB); `MCP_CAPS` gives
  four tools a note of their own that names their parameters for seeing the rest
  (sdk-core ADR-0038, conventions §8): `list_publications` (next item), and the three the
  default can cut when called without `page`, `list_releases` (its note names `since`,
  `until` and `page`), `list_recent_releases` (the same) and a broad `search_publications`
  (its note names `page`), at the sizes the comment above `MCP_CAPS` measures. The notes
  carry the cap, so the task docstrings, which are the tool descriptions, never state it
  (sdk-core's handover, "Adopting core 0.3.0",
  https://github.com/xippios/sdk-core/blob/v0.4.1/docs/handover.md), and each description
  stays under 1,000 characters, stating the most requests a call spends (sdk-core
  ADR-0063, decision 9; ADR-0061, decision 8).
- **The packaged tables.** `reference/publication.json` (2522 publications, each the
  eight columns of `PublicationRow`, a projection of `Publication`) and
  `reference/agency.json` (9 agencies, every field) are `PackagedList` files, written by
  `scripts/refresh_reference.py` with `PackagedList.write`, never by hand; `fetched` is
  the UTC time of each table's first request. `list_publications` answers from them
  without a request, `meta` from `PackagedList.meta` (`retrieved_at` the table's
  `fetched`, `endpoint` `esmis_api_publication_findAll`, sdk-core ADR-0041), and refuses
  an `agency_acronym` the agency table lacks by core's `check` on `params.AGENCIES`, the
  agency table's acronyms and titles declared once, with `UnknownCode`; `list_agencies`
  stays live. Every answer that holds a release or a publication names its agencies by
  `params.AGENCIES` in `meta.names`, through the models' `NamedBy` (sdk-core ADR-0067),
  and `list_publications` names the acronym asked for too, also where no row matches. As
  https://github.com/xippios/sdk-usda-esmis/pull/6 decided, its MCP tool keeps the default
  cap, 200 rows or 64 KB, and is never served the whole table at once; the cap is paged
  (sdk-core ADR-0061, decision 9), since a second run answers from the package and costs
  upstream nothing, so its note names the `offset` that reads the rest, beside `search` and
  `agency_acronym`. No enum is generated from the tables: the package holds no
  `enums.py`, the document's enums are hand-written in `models.py`, and
  `params.PACKAGED_LISTS` names the two tables, which `scripts/refresh_reference.py`
  declares in its one `LISTS` on core's frame, each a finished `PackagedList` with its
  note. The refresh budget: 102 keyless requests (the agencies, then
  `/publication/findAll` pages 0 to 100, up to upstream's count), each sent once, at 30 a
  minute, about four minutes, run once before each release and committed in a refresh PR
  of its own when a table changed, none when both are unchanged (conventions §12; decided
  in https://github.com/xippios/sdk-usda-esmis/pull/6); the script refuses to write a walk
  whose pages disagree. Core's nightly comparison holds the agency table against upstream
  (`LIVE_LISTS` of `tests/test_live.py`); the publication table, 101 requests a fetch,
  stands in `NO_LIVE_LIST`, held by the refresh before each release and by the count of
  `test_list_publications_live` within a page.
- **A catalog, never a parser** (sdk-core ADR-0020). This package lists publications,
  releases and their files, and downloads a file; it never parses one. Parser packages
  such as `xippios-usda-wasde` depend on its tasks and models, never on `api/` or
  `_client` (sdk-core ADR-0021). `download_release_file` is its one bulk task, named in
  `BULK_TASKS` (written by hand, as the template renders it from v0.3.0) and skipped by
  core's `tool_functions` and `router_from_tasks` (sdk-core ADR-0040): it streams one file
  with core's `download` to the path the caller names, `meta.endpoint` the file's name as
  upstream prints it (sdk-core ADR-0020, amendment 2026-11-18, point c); the file is never
  cached. `dest` is keyword-only and required, as sdk-faostat's
  `download_dataset(dataset_code, *, dest)` has it, so a call without it is Python's
  `TypeError`, and core's `check_dest` refuses a directory or a path in a missing
  directory before the release lookup. The file is chosen by `name` alone (the file of
  that name), `format` alone (the first of that format in upstream order) or both (the
  named file, which must be of that format); a call with neither is refused before the
  lookup, an unknown name is `InvalidRequestError` naming the release's files, and a name
  of another format one naming its format, each saying that the release was read and no
  file requested. A release with an original and a revised file of one format (95621,
  "A release lists one to six files") is reached by `name` (decided in
  https://github.com/xippios/sdk-usda-esmis/pull/10). A release's files are
  `Release.release_files()`, `ReleaseFile.from_url` on each URL, in upstream order: the
  reading a dependent calls rather than copies (sdk-core ADR-0021); `get_release` answers
  their URLs, and no task lists them beside it. The download budget: one small file, the
  current WASDE `.txt` (about 120 KB), for the fixture
  (`download_release_file/wasde1026_txt.json`, recorded whole) and for the nightly live
  test, which writes it to a temporary directory.
- **Core.** The package depends on `xippios-core` 0.5.0 from PyPI (`core_version`
  0.5.0, `~=0.5.0`; template v0.5.0), which carries `get_answer` and its `Answer`, the
  one reader of JSON (sdk-core ADR-0037), the walk `fetch_pages` (ADR-0034), the response
  cache (ADR-0040; ADR-0061, decision 11), `check_dest` and the `BULK_TASKS` skip of
  ADR-0040, `check` and `NamedBy` (ADR-0045, ADR-0067), ADR-0041's `published_at_naive`,
  and the package contract that `mcp.py` builds from `tasks.py`, `build()` and `ENV_VARS`
  (ADR-0063, decisions 7 and 8).
