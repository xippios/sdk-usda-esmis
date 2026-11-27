# xippios-usda-esmis

Typed Python client, MCP server and FastAPI routes for
[USDA ESMIS](https://esmis.nal.usda.gov), the Economics, Statistics, and Market
Information System of USDA's National Agricultural Library, part of the
[xippios SDK family](https://github.com/xippios). Names and semantics follow the
upstream documentation; every response carries its metadata (source, endpoint,
retrieved_at, request), and an answer about one release its release time and id as
published_at and vintage.

## Scope

Of ESMIS's API the package wraps seven of the twelve operations that its OpenAPI document
lists (`docs/upstream/`): the agencies, the publications found by keyword or by an
identifier, a publication's releases, the releases of every publication, and one release
with its files, which `download_release_file` downloads. Six are read live, and the
seventh, `esmis_api_publication_findAll`, the package ships as its table of every
publication, refreshed before each release, which `list_publications` answers from. The
tasks take every parameter that the document lists for an operation they read but one. A
documented choice that a caller cannot make yet, and each operation without a task, stand
here with their public issue (sdk-core ADR-0060, decision 8):

- `page` of `esmis_api_publication_findAll`: the package ships every page as its table, so
  no caller sets it, and a live list of every publication with all its fields waits for a
  task (https://github.com/xippios/sdk-usda-esmis/issues/23).
- `esmis_api_publication_findByAgency`, an agency's publications page by page, which
  `list_publications(agency_acronym=...)` answers from the packaged table meanwhile
  (https://github.com/xippios/sdk-usda-esmis/issues/23).
- `esmis_api_publication_findById` and `esmis_api_release_findByPubId`, a publication and
  its releases by the publication's id, where `get_publication` and `list_releases` take
  one of its identifiers; publication 654, whose one identifier holds a `/` that ESMIS's
  web server refuses, has no other way in
  (https://github.com/xippios/sdk-usda-esmis/issues/22).
- `esmis_api_agency_findByAcronym` and `esmis_api_agency_findById`, one agency by its
  acronym or its id, where `list_agencies` answers all of them in one request
  (https://github.com/xippios/sdk-usda-esmis/issues/24).

What the package adds is a walk of a list's pages under one bound, filters that keep the
releases of a list by their printed date, and filters that select rows of the packaged
table by text or by agency. It parses no released file (sdk-core ADR-0020) and picks no
latest release for the caller: ESMIS lists a publication's releases newest first page by
page, some older ones listed early and out of place, so the first row of
`list_releases(identifier, page=0)` is the publication's latest
(`docs/upstream/OBSERVED.md`).

## Install

```bash
uv add xippios-usda-esmis            # client only
uv add "xippios-usda-esmis[mcp]"     # + MCP server
uv add "xippios-usda-esmis[http]"    # + FastAPI router
```

No API key is needed.

## 30-second example

```python
from pathlib import Path

from xippios.usda.esmis import download_release_file, get_release, list_releases

latest = list_releases("wasde", page=0).data[0]  # row 0 of page 0: the latest WASDE release
latest.id, latest.release_datetime  # "796099", 2026-10-09 12:00:00+00:00, as printed

release = get_release(int(latest.id))  # with each file's URL
[file.format for file in release.data.release_files()]  # ["pdf", "txt", "xls", "xml"]
release.meta.vintage  # "796099": the release id
release.meta.published_at  # 2026-10-09 12:00:00, the printed time without its +0000
release.meta.published_at_naive  # True: upstream's text, no zone attached (sdk-core ADR-0041)
release.meta.names  # {"agency_acronym": {"WAOB": "World Agricultural Outlook Board"}}

# Python only, no MCP tool: streams the TXT to the path you name; nothing is cached
txt = download_release_file(796099, dest=Path("wasde1026.txt"), format="txt")
txt.data.path, txt.data.bytes, txt.data.content_type  # wasde1026.txt, 122378, "text/plain"
txt.meta.endpoint  # "wasde1026.txt": the file's name as upstream prints it
```

What identifies a record, a publication's identifier or a release's id, is passed by
position, and every other argument by name: `since`, `until` and `page` of the release
lists, `page` of `search_publications`, `search` and `agency_acronym` of
`list_publications`, and `dest`, `format` and `name` of `download_release_file`, whose
`dest` is required. `search_publications("wasde")` finds a publication's identifiers, and
`list_releases("wasde", since=date(2026, 1, 1))` its releases since a date, in ESMIS's
order, to the first page whose newest release is dated before it.
`list_recent_releases(since=date(2026, 10, 20))` lists what USDA released across every
publication since a date, latest catalogued first. A walk of pages sends at most 24
requests, in Python and over MCP alike, and one that needs more is refused and returns
nothing, naming `page`: after its first request where upstream's count shows it, as for
`list_releases("wasde")` without `since`, WASDE's 703 releases filling 29 pages, and
`list_recent_releases` without `since`, and after its 24th where a walk from `since`
reaches no page that ends it within them, as for WASDE's releases from a `since` before
1982-02-12 on its list of 2026-11-27. A walk from a
`since` before 2025-09-12, ESMIS's migration, is refused before any request, as the older
ids do not follow the release dates; `list_releases` or `page` serves older dates. A
second call within 300 seconds is answered from the client's cache, its
`meta.retrieved_at` the time the first answer was stored.

`list_publications()` answers from the table of 2522 publications packaged with this
version, fetched on 2026-10-27, without a request:

```python
from xippios.usda.esmis import list_publications

wheat = list_publications(search="wheat")  # id, identifier or title contains "wheat": 30
ers = list_publications(agency_acronym="ERS")  # as list_agencies() spells it: 121
ers.meta.retrieved_at  # 2026-10-27 17:24:48+00:00, when the table was fetched
ers.meta.endpoint  # "esmis_api_publication_findAll", the operation it came from
```

An acronym the packaged agency table lacks raises `UnknownCode`, an
`InvalidRequestError` naming the closest (`"ers"`: did you mean `ERS`?).

## MCP

```json
{
  "mcpServers": {
    "usda-esmis": {
      "command": "uvx",
      "args": ["--from", "xippios-usda-esmis[mcp]", "xippios-usda-esmis-mcp"]
    }
  }
}
```

Tools are read-only and named `usda_esmis_<verb>_<noun>`. Results are capped, at
200 rows or 64 KB unless a tool has a cap of its own, with a note on how to see the rest.
Four tools keep the default with a note naming their own parameters:
`usda_esmis_list_publications` takes `offset`, which its note names, and reads the rest of
its packaged table in further calls, beside its filters, while `list_publications()` in
Python and its HTTP route return the whole table; `usda_esmis_list_releases` and
`usda_esmis_list_recent_releases` name `since`, `until` and `page`, and
`usda_esmis_search_publications` names `page`.
`download_release_file` is no tool and no route: a bulk task, Python only
(sdk-core ADR-0040).
`--http` serves streamable HTTP instead of stdio.

## Status

<!-- Core's family check (tests/test_family.py) reads this table: keep the "## Status"
heading and the "Task function" column. Each row's Task function cell starts with the
task's name in backticks, alone or as its call (`get_data(code, year)`); several tasks in
one row are backticked names separated by commas; prose may follow. The tables list
exactly tasks.__all__, and tasks_write.__all__ where the package has write tasks. -->

| Upstream operation | Task function | MCP tool | Status |
| --- | --- | --- | --- |
| `esmis_api_agency_findAll` | `list_agencies()` | `usda_esmis_list_agencies` | alpha |
| `esmis_api_publication_findAll`, every page, packaged (fetched 2026-10-27; no request) | `list_publications(*, search=None, agency_acronym=None)` | `usda_esmis_list_publications` | alpha |
| `esmis_api_publication_search`, every page, at most 24, unless `page` is given | `search_publications(query, *, page=None)` | `usda_esmis_search_publications` | alpha |
| `esmis_api_publication_findByIdentifier` | `get_publication(publication_identifier)` | `usda_esmis_get_publication` | alpha |
| `esmis_api_release_findByIdentifier`, pages walked from 0 down to `since` (to the first page whose newest release is dated before it), at most 24, unless `page` is given | `list_releases(publication_identifier, *, since=None, until=None, page=None)` | `usda_esmis_list_releases` | alpha |
| `esmis_api_release_findAll`, every publication's releases, pages walked from 0 down to `since` (to the first page whose newest release is dated more than 14 days before it), at most 24, unless `page` is given | `list_recent_releases(*, since=None, until=None, page=None)`, refused past 24 pages, so without `since`, and for a walk from a `since` before 2025-09-12 | `usda_esmis_list_recent_releases` | alpha |
| `esmis_api_release_findById` | `get_release(release_id)`, each file's URL in its answer, `Release.release_files()` their names and formats | `usda_esmis_get_release` | alpha |
| `esmis_api_release_findById`, then the file | `download_release_file(release_id, *, dest, format=None, name=None)`, a bulk task: `dest` required, the file chosen by `format`, `name` or both | none, Python only | alpha |

## Upstream terms and attribution

Data comes from USDA ESMIS (https://esmis.nal.usda.gov) under its own terms of use;
this package adds no rights to it. The documentation and the release files are works of
the United States Government (USDA National Agricultural Library, ESMIS), in the public
domain in the United States (17 U.S.C. § 105); a suggested credit line is "Source:
USDA National Agricultural Library, ESMIS". The pages the snapshot reads print no
copyright line, and USDA's policy page is cited in `docs/upstream/FETCHED.md`.
Documentation snapshot: `docs/upstream/`.

## Workflows

`ci.yml` runs ruff, its format check, mypy, pytest and pre-commit on Python 3.12, 3.13 and
3.14, requires a changelog entry of every pull request but Dependabot's and refuses a
fixture file over 256 KiB that a pull request adds or changes. It runs on every pull request and,
called by `publish.yml`, once for a release, and its job `ci` is the check the
organization's ruleset requires. It is handed no secret, and no variable switches it off.

`publish.yml` is the release train (conventions §12): on a push to `main` whose
`pyproject.toml` names a version that has no tag yet and has its section in `CHANGELOG.md`,
it runs `ci.yml`, refuses a core pinned to git, tags the merge commit, builds the package
and, once a reviewer of the environment `pypi` approves the run, publishes it to PyPI by
trusted publishing. Every push to `main` and a dispatch start it, and a push that brings no
release ends quietly. It is handed no secret: the step that tells a release is handed the
job's token as `GH_TOKEN`, the tag goes with the job's token and PyPI trusts the workflow
itself. Its job `tag` holds the one checkout of the repository that keeps its credentials,
since it pushes the tag with the job's token; every other checkout sets
`persist-credentials: false` (conventions §13). No variable switches it off.

`live.yml` runs every `live` test against the upstream with `--tb=short --assert=plain`, so
its public log holds neither a failing test's arguments nor the values an assertion compared.
It runs every night at 01:27 UTC and on demand, never on a pull request.
Its pytest step alone is handed `XIPPIOS_LIVE_TESTS`, and no secret.
A variable `WORKFLOW_LIVE` of `off`, the repository's over the organization's, switches it off.

`conventions.yml` calls the organization's review of a pull request against the documents
listed under Documents below, the check `conventions / conventions`, when a pull request
opens, is pushed to, reopens or is edited, and on a push to `main` or a dispatch the review
of the range of commits, `range / range`. It hands the review the organization's
secret of the model's key, by name. A variable `WORKFLOW_CONVENTIONS` of `off`, the
repository's over the organization's, switches both off.

`adr-index.yml` calls the organization's check of the ADR index, `adr-index / adr-index`,
which runs `scripts/adr_index.py --check`, when a pull request opens, is pushed to or
reopens. It hands over nothing, and the called workflow reads its switch itself: a variable
`WORKFLOW_ADR_INDEX` of `off`, the repository's over the organization's, skips the check.

`siblings.yml` runs `.github/scripts/check-siblings.sh`, which installs the wheel beside
every sibling on PyPI under the same provider namespace that shares its core minor and
beside the source packages it depends on, and proves that the namespace levels stay portions
(sdk-core ADR-0006, sdk-core ADR-0021). It runs on every pull request and push to `main`, a
check the ruleset does not require, in a workflow of its own, since `ci.yml` is core's file,
which `publish.yml` calls for a release. It hands the script the job's read-only token as
`GITHUB_TOKEN`, for the listing of the organization's repositories, since GitHub limits the
calls of a runner without one. A variable `WORKFLOW_SIBLINGS` of `off`, the repository's
over the organization's, switches it off.

## Documents

- sdk-core: [docs/conventions.md](https://github.com/xippios/sdk-core/blob/main/docs/conventions.md) — the conventions every xippios source package follows: its layout, names, results, tests and releases.
- sdk-core: [docs/adr.md](https://github.com/xippios/sdk-core/blob/main/docs/adr.md) — the index of the family's architecture decisions, which the conventions cite.
- sdk-core: [docs/definition-of-done.md](https://github.com/xippios/sdk-core/blob/main/docs/definition-of-done.md) — what a change satisfies before its pull request is opened.
- sdk-core: [docs/review-checklist.md](https://github.com/xippios/sdk-core/blob/main/docs/review-checklist.md) — what the review of a pull request checks, in order.
- sdk-usda-esmis: [docs/adr.md](https://github.com/xippios/sdk-usda-esmis/blob/main/docs/adr.md) — the index of this package's own decisions, generated from the records in `docs/adr/`.
- sdk-usda-esmis: [docs/upstream/FETCHED.md](https://github.com/xippios/sdk-usda-esmis/blob/main/docs/upstream/FETCHED.md) — the snapshot of the upstream documentation, the reference for names, parameters and semantics.
- sdk-usda-esmis: [docs/upstream/OBSERVED.md](https://github.com/xippios/sdk-usda-esmis/blob/main/docs/upstream/OBSERVED.md) — what the live API does that its documentation does not state, where it answers otherwise above all, each note with the probe that showed it.

## Licence

Apache-2.0. See [LICENSE](https://github.com/xippios/sdk-usda-esmis/blob/main/LICENSE).
