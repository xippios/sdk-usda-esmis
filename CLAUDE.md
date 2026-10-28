# sdk-usda-esmis — instructions for Claude Code

`xippios-usda-esmis` wraps USDA ESMIS, the Economics, Statistics, and Market Information
System of USDA's National Agricultural Library, as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file is the contract for every session
that works here; the family rules it points to apply as well.

@.claude/family.md

## What this package wraps

| | |
| --- | --- |
| Upstream | USDA ESMIS (Economics, Statistics, and Market Information System), https://esmis.nal.usda.gov |
| API base URL | `https://esmis.nal.usda.gov` |
| Documentation | https://esmis.nal.usda.gov/api-documentation, snapshotted in `docs/upstream/` |
| Credentials | none; the API is open |
| Rate limit | 30 requests per minute, burst 1; a self-imposed pace, upstream documents none (ADR-0010); enforced client-side in `_client.py` |
| Write tools | no, this package is read-only |

The snapshot in `docs/upstream/` is the reference for names, parameters and semantics.

## ESMIS specifics

- **Reference.** `docs/upstream/openapi/esmis_public_api.yaml` (OpenAPI 3.0.0, twelve
  GET operations) is the reference for operation names, paths, parameters and schema
  names. Where the live API answers differently, the wire wins for types; README's
  section "Where the live API deviates from its OpenAPI document" lists the differences,
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
  (ADR-0012). A page past the last answers empty `results` with `current_page` clamped
  to the last page. `publication_search` with an empty `query` answers `"pager": []`,
  which `PublicationResults.pager` takes as `()`.
- **Order**, observed, not documented. `/release/findAll` is creation order, highest id
  first: the newest created, not the newest released (page 0 runs 2026-10-26,
  2026-10-09, 2026-10-23). Within a publication the ids do not follow the dates: WASDE's
  96169, 96170 and 96171 are August, July and June 2025, and 95482 to 95486 rise while
  the dates fall; its releases come latest `release_datetime` first, as recorded on its
  pages 0 and 1 (`release_find_by_identifier/wasde_page0.json`, `wasde_page1.json`).
  `list_releases` and `get_latest_release` rely on that order and say so in their
  docstrings; the live test `test_page_zero_of_a_publication_is_newest_first` checks it
  nightly. Publication lists follow no id order.
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
  calendar and file times put the release at noon Eastern (README, the zone-label item),
  and `Publication.upcoming_releases` print Eastern offsets (`2026-10-28T15:00:00-0400`,
  `2026-11-04T15:00:00-0500`), which the model keeps. Decided by Johannes on 2026-10-27:
  `Release.release_datetime` keeps the time as printed, an aware datetime at `+00:00`;
  the four tasks about one release (`get_release`, `get_latest_release`,
  `list_release_files`, `download_release_file`) set `meta.published_at` to that time
  with the offset dropped (`.replace(tzinfo=None)`, the printed wall-clock time, never
  converted) and `published_at_naive=True` (ADR-0022, rule 2); the list tasks leave it
  empty. `meta.vintage` is the release id.
- **Tasks.** Nine: eight are the contract of `xippios-usda-wasde` (ADR-0021), and
  `list_publications` answers from the packaged table (next item). A paged task given
  `page` returns that page; without it, `tasks._Pages` walks the pages from 0 with core's
  `paginate_offset` (`page = offset // 25`), bounded by the last answer's
  `pager.total_pages`, an empty or a short page, and, for `list_releases`, the first
  page whose oldest release is dated before `since`; never by the echoed
  `current_page`. `list_releases` filters `since` and `until` on the printed date of
  `release_datetime`, never converted, and its `meta.total` is upstream's count before
  that filter. `get_latest_release` takes the latest `release_datetime` of page 0,
  never the highest id. `meta.request` omits what the caller left `None`. Every tool keeps
  the default cap (200 rows or 64 KB); `MCP_CAPS` gives `list_publications` a note of its
  own (next item). The default can cut two tools called without `page`: `list_releases`
  (703 rows for WASDE) and a broad `search_publications` (about 1.8 KB a publication, so
  after some 36 matches). Their docstrings tell an agent to page, `list_releases`'s also
  to bound the call with `since` and `until`.
- **The packaged tables.** `reference/publication.json` (2522 publications, each the
  eight columns of `PublicationRow`, a projection of `Publication`) and
  `reference/agency.json` (9 agencies, every field) are `PackagedList` files, written by
  `scripts/refresh_reference.py` with `PackagedList.write`, never by hand; `fetched` is
  the UTC time of each table's first request. `list_publications` answers from them
  without a request, `meta` from `PackagedList.meta` (`retrieved_at` the table's
  `fetched`, `endpoint` `esmis_api_publication_findAll`, ADR-0022), and refuses an
  `agency_acronym` the agency table lacks with core's `UnknownCode`; `list_agencies`
  stays live. Decided by Johannes on 2026-10-27: its MCP tool keeps the default cap, 200
  rows or 64 KB, with a note naming `search` and `agency_acronym` and that Python and
  HTTP callers get the whole table; unfiltered the result is 599,402 bytes of compact
  JSON, about 150k tokens, so an agent filters it, as with sdk-comtrade's HS list, and is
  never served it whole (ADR-0016). No enum is generated from the tables (`enums.py`
  holds none, the document's enums are hand-written in `models.py`) and
  `params.PACKAGED_LISTS` stays empty. The template's `/refresh-reference-data` command
  (v0.3.0) puts a table in the script's `TABLES` and its name in `PACKAGED_LISTS`;
  ESMIS's own script has neither, renders no enum and leaves `PACKAGED_LISTS` empty
  (queue row 101); its docstring is the recipe for this package. The refresh budget:
  102 keyless requests (the agencies, then
  `/publication/findAll` pages 0 to 100, bounded by `total_pages`) at 30 a minute, about
  four minutes, run once before each release and committed in a refresh PR of its own
  when a table changed, none when both are unchanged (Workflow rules; decided by
  Johannes on 2026-10-27); the script refuses to write a walk whose pages disagree.
  The nightly live tests compare the agency table with upstream and the publication
  count within a page.
- **A catalog, never a parser** (ADR-0020). This package lists publications, releases
  and their files, and downloads a file; it never parses one. Parser packages such as
  `xippios-usda-wasde` depend on its tasks and models, never on `api/` or `_client`
  (ADR-0021). `download_release_file` is its one bulk task, named in `BULK_TASKS`
  (written by hand, as the template renders it from v0.3.0) and skipped by core's
  `register_tasks` and `router_from_tasks` (ADR-0019): it streams one file with core's
  `download` to the path the caller names, `meta.endpoint` the file's name as upstream
  prints it; nothing is stored or cached. The download budget: one small file, the
  current WASDE `.txt` (about 120 KB), for the fixture
  (`download_release_file/wasde1026_txt.json`, recorded whole) and for the nightly live
  test, which writes it to a temporary directory.
- **Core.** The package depends on `xippios-core` 0.3.0 from PyPI (`core_version`
  0.3.0, `~=0.3.0`; template v0.3.0), which carries ADR-0019's `download` and
  `BULK_TASKS` skip and ADR-0022's `published_at_naive`.

## Layout

```
src/xippios/usda/esmis/
  __init__.py      public surface: __version__ and re-exported task functions
  py.typed         PEP 561 marker; consumers' mypy --strict needs it
  _version.py      __version__ from distribution metadata
  _client.py       the one configured AsyncClient (base URL, rate limit) and classify,
                   upstream's documented error shapes
  errors.py        the package's own error classes, where conventions §5 calls for one
  models.py        pydantic models mirroring upstream payloads (UpstreamModel)
  api/             endpoint wrappers, one module per upstream operation
  tasks.py         task functions; __all__ minus BULK_TASKS is what the adapters
                   register, MCP_CAPS any per-tool result caps
  mcp.py           xippios-usda-esmis-mcp entry point
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
docs/upstream/     documentation snapshot and FETCHED.md
.github/workflows/ ci.yml (the required ci check, with the CHANGELOG and fixture-size steps),
                   publish.yml (the release train: tag, build, PyPI), live.yml (nightly live
                   tests), gates.yml (the merge gates as jobs, off until GATES_CALLER is 1)
                   siblings.yml (the sibling proof of ADR-0006: this wheel beside the
                   siblings under xippios.usda, a visible check the ruleset does not require)
.github/scripts/   check-siblings.sh, which siblings.yml runs; the template's, as is the workflow
.claude/family.md  the family rules, the template's, imported above
.claude/commands/  add-endpoint, record-fixture, refresh-upstream, refresh-reference-data, release-prep,
                   adopt-release
```

`src/xippios/` has **no** `__init__.py`: it is a PEP 420 namespace package shared with
`xippios-core` and every other source package, and so is every level
between it and the package (`src/xippios/usda/`). The import path is
`xippios.usda.esmis` (ADR-0006).

## Commands

```bash
uv run pytest -m live --tb=short   # needs XIPPIOS_LIVE_TESTS=1

uv run xippios-usda-esmis-mcp   # stdio; add --http for streamable HTTP
```

`.github/workflows/live.yml` runs `uv run pytest -m live --tb=short` with
`XIPPIOS_LIVE_TESTS=1` nightly at 01:27 UTC, a time derived from the slug so that sources
sharing a key never start together, and on demand from the Actions tab; pull requests
never run live tests. The API needs no key, so the workflow uses no secret.
