# xippios-usda-esmis

Typed Python client, MCP server and FastAPI routes for
[USDA ESMIS](https://esmis.nal.usda.gov), the Economics, Statistics, and Market
Information System of USDA's National Agricultural Library, part of the
[xippios SDK family](https://github.com/xippios). Names and semantics follow the
upstream documentation; every response carries its metadata (source, endpoint,
retrieved_at, request), and an answer about one release its release time and id as
published_at and vintage.

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

from xippios.usda.esmis import download_release_file, list_release_files, list_releases

latest = list_releases("wasde", page=0).data[0]  # newest first: the latest WASDE release
latest.id, latest.release_datetime  # "796099", 2026-10-09 12:00:00+00:00, as printed

files = list_release_files(int(latest.id))
[file.format for file in files.data]  # ["pdf", "txt", "xls", "xml"]
files.meta.vintage  # "796099": the release id
files.meta.published_at  # 2026-10-09 12:00:00, the printed time without its +0000
files.meta.published_at_naive  # True: upstream's text, no zone attached (sdk-core ADR-0041)
files.meta.names  # {"agency_acronym": {"WAOB": "World Agricultural Outlook Board"}}

# Python only, no MCP tool: streams the TXT to the path you name; nothing is cached
txt = download_release_file(796099, "txt", Path("wasde1026.txt"))
txt.data.path, txt.data.bytes, txt.data.content_type  # wasde1026.txt, 122378, "text/plain"
txt.meta.endpoint  # "wasde1026.txt": the file's name as upstream prints it
```

`search_publications("wasde")` finds a publication's identifiers, and
`list_releases("wasde", since=date(2026, 1, 1))` its releases since a date, newest first.
`list_recent_releases(since=date(2026, 10, 20))` lists what USDA released across every
publication since a date, latest catalogued first. A walk of pages sends at most 24
requests, in Python and over MCP alike, and one that needs more is refused after its first
request, naming `page`: `list_releases("wasde")` without `since` among them, WASDE's 703
releases filling 29 pages, and `list_recent_releases` without `since`. A walk from a
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
| `esmis_api_publication_findAll`, every page, packaged (fetched 2026-10-27; no request) | `list_publications(search=None, agency_acronym=None)` | `usda_esmis_list_publications` | alpha |
| `esmis_api_publication_search`, every page, at most 24, unless `page` is given | `search_publications(query, page=None)` | `usda_esmis_search_publications` | alpha |
| `esmis_api_publication_findByIdentifier` | `get_publication(publication_identifier)` | `usda_esmis_get_publication` | alpha |
| `esmis_api_release_findByIdentifier`, pages walked newest first, at most 24, unless `page` is given | `list_releases(publication_identifier, since=None, until=None, page=None)` | `usda_esmis_list_releases` | alpha |
| `esmis_api_release_findAll`, every publication's releases, pages walked from 0 down to `since` (to the first page whose newest release is dated more than 14 days before it), at most 24, unless `page` is given | `list_recent_releases(since=None, until=None, page=None)`, refused past 24 pages, so without `since`, and for a walk from a `since` before 2025-09-12 | `usda_esmis_list_recent_releases` | alpha |
| `esmis_api_release_findById` | `get_release(release_id)` | `usda_esmis_get_release` | alpha |
| `esmis_api_release_findById` | `list_release_files(release_id)` | `usda_esmis_list_release_files` | alpha |
| `esmis_api_release_findById`, then the file | `download_release_file(release_id, format=None, dest=None, *, name=None)`, a bulk task: `dest` required, the file chosen by `format`, `name` or both | none, Python only | alpha |

## Upstream terms and attribution

Data comes from USDA ESMIS (https://esmis.nal.usda.gov) under its own terms of use;
this package adds no rights to it. The documentation and the release files are works of
the United States Government (USDA National Agricultural Library, ESMIS), in the public
domain in the United States (17 U.S.C. § 105); a suggested credit line is "Source:
USDA National Agricultural Library, ESMIS". The pages the snapshot reads print no
copyright line, and USDA's policy page is cited in `docs/upstream/FETCHED.md`.
Documentation snapshot: `docs/upstream/`.

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
