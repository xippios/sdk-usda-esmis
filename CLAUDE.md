# sdk-usda-esmis — instructions for Claude Code

`xippios-usda-esmis` wraps USDA ESMIS, the Economics, Statistics, and Market Information
System of USDA's National Agricultural Library, as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file is the contract for every session
that works here; the family rules it points to apply as well.

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
If it is empty or stale, run `/refresh-upstream` first and review the diff. Never write a
wrapper from memory of the API.

## ESMIS specifics

- **Reference.** `docs/upstream/openapi/esmis_public_api.yaml` (OpenAPI 3.0.0, twelve
  GET operations) is the reference for operation names, paths, parameters and schema
  names. Where the live API answers differently, the wire wins for types; README's
  section "Where the live API deviates from its OpenAPI document" lists the differences,
  and `models.py` and `tests/fixtures/` show them.
- **Wrappers.** Every operation sits under `/api/v1/` on `https://esmis.nal.usda.gov`. A
  module and its function are the operationId snake_cased without the constant
  `esmis_api_` prefix (`esmis_api_release_findByPubId` is `api.release_find_by_pub_id`),
  since `xippios.usda.esmis.api` already is that namespace; the tasks will name the full
  operationId in `meta.endpoint`. Path parameters are quoted whole (`safe=""`); the id
  parameters are integers, as the document types them, while every `id` in an answer is
  a string. Release `files` are absolute URLs on the same host.
- **Pagination.** `page` is 0-based with 25 items a page, a size no parameter changes;
  `pager.total_results` is upstream's count, the value for `meta.total` (ADR-0012). A
  page past the last answers empty `results` with `current_page` clamped to the last
  page. Order is observed, not documented: all releases by id, highest first; a
  publication's releases by `release_datetime`, latest first; the publication list in
  neither order. `publication_search` with an empty `query` answers `"pager": []`, which
  `PublicationResults.pager` takes as `()`.
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
  return those as such; how the tasks report them is decided in the tasks round. An
  identifier carrying `/` (`Market and Trade Economics Division/FDS`) cannot be looked
  up: ESMIS's web server refuses `%2F` with an HTML 404, raised as
  `InvalidRequestError`, and a raw slash is no route; the publications recorded with one
  carry another identifier without it (`FDS`).
- **Release times.** The API prints `release_datetime` with `+0000`, but upstream's own
  calendar and file times put the release at noon Eastern (README, the zone-label item),
  and `Publication.upcoming_releases` print Eastern offsets (`2026-10-28T15:00:00-0400`,
  `2026-11-04T15:00:00-0500`), which the model keeps. Decided by Johannes on 2026-10-27:
  `Release.release_datetime` keeps the time as printed, an aware datetime at `+00:00`; a
  task's `meta.published_at` carries the wall-clock time with the offset dropped and
  `published_at_naive=True` once the core pin carries ADR-0022's flag, and stays empty
  before; `meta.vintage` is the release id.
- **A catalog, never a parser** (ADR-0020). This package lists publications, releases
  and their files, and is to download a file; it never parses one. Parser packages such
  as `xippios-usda-wasde` depend on its tasks and models, never on `api/` or `_client`
  (ADR-0021). `download_release_file` is to be its one bulk task, named in `BULK_TASKS`
  and skipped by the adapters (ADR-0019); it comes with the core re-pin.
- **The core pin.** The package builds on `xippios-core~=0.2.1` from PyPI so far. The
  tasks build on a git pin of core 0.3.0 that carries ADR-0019's `download`, set in
  `[tool.uv.sources]` by the re-pin; a PR of its own replaces the pin with
  `xippios-core~=0.3.0` from PyPI before the release (conventions §12).

## Read first, in this order

1. `docs/upstream/FETCHED.md` and the files it lists: what the upstream actually offers
2. The family conventions: `../sdk-core/docs/conventions.md` and `../sdk-core/docs/adr/`
   (also at https://github.com/xippios/sdk-core/tree/main/docs)
3. `../sdk-core/docs/definition-of-done.md`: what a PR must satisfy, and
   `../sdk-core/docs/review-checklist.md`: what the reviewer checks it against
4. The family file `../CLAUDE.md`
5. When a new core minor or template release comes: conventions §15, the adoption
   checklist, which `/adopt-release` walks

## The one rule: three layers (ADR-0001)

```
api/<operation>.py   one async function per upstream operation, upstream names, returns models
tasks.py             the public API: composes wrappers, returns Result[T], sync facade via sync()
mcp.py  http.py      adapters: register tasks.__all__, nothing else. Never edited to add an endpoint.
```

Adapters call only task functions. Tasks call only endpoint wrappers and reference
data. If logic appears in `mcp.py` or `http.py`, it belongs in `tasks.py`.

## Layout

```
src/xippios/usda/esmis/
  __init__.py      public surface: __version__ and re-exported task functions
  py.typed         PEP 561 marker; consumers' mypy --strict needs it
  _version.py      __version__ from distribution metadata
  _client.py       the one configured AsyncClient (base URL, key, rate limit)
  models.py        pydantic models mirroring upstream payloads (UpstreamModel)
  api/             endpoint wrappers, one module per upstream operation
  tasks.py         task functions; __all__ is what the adapters register, MCP_CAPS any
                   per-tool result caps
  mcp.py           xippios-usda-esmis-mcp entry point
  http.py          FastAPI router
  params.py        packaged value lists: PACKAGED_LISTS, packaged_values()
  enums.py         StrEnums (IntEnums for integer ids) generated from the packaged lists;
                   never edited by hand
  reference/       packaged code lists (CSV/JSON) plus README with provenance
scripts/
  refresh_reference.py   fetches the packaged lists through api/ and regenerates enums.py
tests/
  conftest.py      enables xippios.core.testing.plugin, which keeps the run offline
  fixtures/        recorded responses, <endpoint>/<case>.json, never hand-written
  test_family.py   core's family check, one line: namespace levels, py.typed, __version__,
                   the adapters serving exactly the tasks, task shapes and docstrings, the
                   README status table, the template tag, the core bound
  test_api.py      replay tests for the endpoint wrappers, one or more per operation
  test_tasks.py    per-task replay tests
  test_live.py     @pytest.mark.live smoke tests, one per task
docs/upstream/     documentation snapshot and FETCHED.md
.github/workflows/ ci.yml (the required ci check, with the CHANGELOG and fixture-size steps),
                   publish.yml (the release train: tag, build, PyPI), live.yml (nightly live
                   tests), gates.yml (the merge gates as jobs, off until GATES_CALLER is 1)
.claude/commands/  add-endpoint, record-fixture, refresh-upstream, refresh-reference-data, release-prep,
                   adopt-release
```

`src/xippios/` has **no** `__init__.py`: it is a PEP 420 namespace package shared with
`xippios-core` and every other source package, and so is every level
between it and the package (`src/xippios/usda/`).
Never add one; `tests/test_family.py` fails if it appears. The import path is
`xippios.usda.esmis` (ADR-0006).

## How to add an endpoint

Run `/add-endpoint <upstream operation>`. In short:

1. Read the operation in `docs/upstream/`. Names, parameters and semantics come from
   there, snake_cased, nothing renamed, nothing normalised across sources.
2. `models.py`: an `UpstreamModel` per payload object; dates, numbers and enums typed.
3. `api/<operation>.py`: one async wrapper that calls `_client.client` and returns
   models through `xippios.core.parse`.
4. `tasks.py`: an async task that composes wrappers and returns `Result[T]` with full
   `ResultMeta` (source, endpoint, request parameters, `published_at`/`vintage` when the
   upstream gives them). Derive the sync one with `sync()`, add its name to `__all__`,
   re-export it from `__init__.py`. What it returns leaves out documented personal
   identifiers (`ssn`, `iban` and their like) unless it fetches them deliberately and
   says so, and a write task does not echo one in `meta.request` (ADR-0017).
5. Docstring for agents: one sentence, then `Args:` with examples of valid values for
   every parameter. The MCP tool description and the OpenAPI summary come from it.
6. `/record-fixture` for at least one case, a replay test in `test_tasks.py` that also
   calls the tool end to end with `xippios.core.testing.mcp_call` (and compares what was
   sent through `sent_urls(route)`, never a request from `route.calls`), a live smoke test
   in `test_live.py`.
7. `CHANGELOG.md` under Unreleased, README status table (the task's name first in its
   cell, in backticks, as the comment above the table says), then the full check suite.

Reference lookups (commodities, countries, attributes) are tasks too, named
`list_<thing>`, so agents can form valid calls; one whose whole list an agent needs and
the default result cap (200 rows or 64 KB) would cut gets a cap of its own in `MCP_CAPS`
in `tasks.py`, which `mcp.py` passes through (ADR-0016). A task-shaped function that returns a
subset of an upstream record builds its model with `UpstreamModel.project`; nothing is
renamed or computed, parsing a value (`parse_decimal`) is the only override. Upstream's
documented error shapes go into `ClientConfig.classify` in `_client.py`, once; wrappers
use `client.get_json` and never inspect status codes. An upstream that reports an hourly
or daily quota gets one `QuotaPolicy` installed on `config` there
(`config = QuotaPolicy(window=..., limit_header=..., remaining_header=...,
source=SOURCE).install(config)`, with the headers and window the upstream documents; a
repository generated from template v0.2.0 on carries it as a commented block), and
`classify` maps its answer to a spent quota to `RateLimitError` with `retry_after`
(ADR-0010, ADR-0015).

## How to record a fixture

Run `/record-fixture <endpoint> <case> <parameters>`. It performs one live request
through the real client with `xippios.core.testing.record_sync` and writes
`tests/fixtures/<endpoint>/<case>.json` with credentials scrubbed. Grep the file for
key patterns, and for the personal identifiers the package keeps out of its projections
(ADR-0017), before committing. Fixtures are never typed in by hand.

## Commands

```bash
uv sync --all-extras
uv run pytest                      # offline, replays fixtures
uv run pytest -m live              # needs XIPPIOS_LIVE_TESTS=1
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit run --all-files
uv run xippios-usda-esmis-mcp   # stdio; add --http for streamable HTTP
```

The offline run is core's plugin's (ADR-0013): in every test not marked `live` it refuses
the network and skips the rate limiter's waits.
A test that asserts a limiter wait or a quota pause is marked `rate_limited`, one that
must reach the network `network`.

`.github/workflows/live.yml` runs `uv run pytest -m live` with `XIPPIOS_LIVE_TESTS=1`
nightly at 01:27 UTC, a time derived from the slug so that sources sharing a key never
start together, and on demand from the Actions tab; pull requests never run live tests.
The API needs no key, so the workflow uses no secret.

## Workflow rules

- Branch from `main` as `feature/<topic>`, `fix/<topic>`, `chore/<topic>` or `docs/<topic>`.
  Never commit to `main`.
- Commit small, with Conventional Commits messages (`feat(tasks): add get_balance_sheet`).
- Open the PR with `gh pr create`; the body is the definition-of-done checklist from
  `.github/PULL_REQUEST_TEMPLATE.md`, ticked honestly, with assumptions and open
  questions listed, the live calls the PR spent counted (keyed calls by number; `none`
  is a count), and, after the checklist, a `## Decisions taken` block: one line per
  decision the session made, each backed by a convention, an ADR, a coordination rule, a
  dated decision of Johannes's or `gap, row N`. The reviewer judges the PR against
  sdk-core's `docs/review-checklist.md`.
- Every PR but a release, an adoption or Dependabot's adds an entry under Unreleased in
  `CHANGELOG.md`; `ci.yml` fails without one (conventions §12).
- Releases follow the release train (conventions §12): `/release-prep` opens a release
  PR that changes only `pyproject.toml`, `uv.lock`, `CHANGELOG.md`, `README.md`,
  `CLAUDE.md` and `docs/handover.md` (and `scripts/check-siblings.sh` where the source
  has one); its merge runs `publish.yml`, which tags the version on the merge commit,
  and Johannes approves the `pypi` run. A reference-data refresh or a core pin's removal
  is a PR of its own before it.
- `ruff` leaves `docs/` alone; never reformat the upstream snapshot.
- Template and core updates: a new sdk-template release, and the core minor it carries,
  arrive in one adoption PR, `chore/template-update-<tag>`, before the next release
  (conventions §15); `/adopt-release <tag>` walks it, and when its merge class is `auto`
  the session enables auto-merge after the reviewer's `ready` (ADR-0018, amendment (e)).
  `uvx copier update` re-renders the files the template owns (`tests/conftest.py` and
  `tests/test_family.py` among them; answers are in `.copier-answers.yml`) and never
  overwrites the files this package fills:
  `__init__.py`, `_client.py`, `models.py`, `api/`, `tasks.py`, `tasks_write.py`,
  `params.py`, `enums.py`, `reference/`, `scripts/`, `tests/test_tasks.py`,
  `tests/test_tasks_write.py`, `tests/test_live.py`, `tests/fixtures/`, `docs/upstream/`,
  `README.md` and `CHANGELOG.md`. Template changes to those are listed per release under
  "Hand-apply" in sdk-template's
  [CHANGELOG](https://github.com/xippios/sdk-template/blob/main/CHANGELOG.md); port them
  by hand in the same PR.
- If a convention seems wrong, say so in the PR and follow it anyway; changing it is a
  PR against `sdk-core/docs/conventions.md` plus an ADR.

## Never

- Never hand-write a fixture, and never commit one without grepping for key patterns.
- Never read or print `.envrc`, `.env`, or any variable ending in `_API_KEY`.
- Never write a key into a file or a commit.
- Never put logic in `mcp.py` or `http.py`; never add a route or tool by hand.
- Never rename or re-map an upstream concept to another source's (ADR-0003).
- Never return a documented personal identifier in a task's projection, echo one in
  `meta.request`, or commit one in a fixture (ADR-0017).
- Never edit `docs/upstream/` by hand; `/refresh-upstream` fetches, a PR reviews.
- Never add `src/xippios/__init__.py` or `src/xippios/usda/__init__.py`, the provider level.
- Never tag, merge, release, force-push, or touch `gh secret`: a release PR's merge tags
  through `publish.yml`, and Johannes approves the `pypi` run. The one exception is
  enabling auto-merge on a `chore/template-update*` or `chore/release-*` PR whose merge
  class is `auto`, after the reviewer's `ready` (ADR-0018, amendment (e)).

## When something is unclear

Prefer the smallest change that satisfies the documents above, state the assumption in
the PR description, and stop rather than guess at upstream semantics or public API shape.
