# xippios-usda-esmis

Typed Python client, MCP server and FastAPI routes for
[USDA ESMIS](https://esmis.nal.usda.gov), the Economics, Statistics, and Market
Information System of USDA's National Agricultural Library, part of the
[xippios SDK family](https://github.com/xippios). Names and semantics follow the
upstream documentation; every response carries release metadata (source, endpoint,
retrieved_at, published_at, vintage).

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

from xippios.usda.esmis import download_release_file, get_latest_release, list_release_files

latest = get_latest_release("wasde")  # the newest WASDE release
latest.data.id, latest.data.release_datetime  # "796099", 2026-10-09 12:00:00+00:00, as printed
latest.meta.vintage  # "796099": the release id
latest.meta.published_at  # 2026-10-09 12:00:00, the printed time without its +0000
latest.meta.published_at_naive  # True: upstream's text, no zone attached (ADR-0022)

files = list_release_files(int(latest.data.id))
[file.format for file in files.data]  # ["pdf", "txt", "xls", "xml"]

# Python only, no MCP tool: streams the TXT to the path you name; nothing is cached
txt = download_release_file(796099, "txt", Path("wasde1026.txt"))
txt.data.path, txt.data.bytes, txt.data.content_type  # wasde1026.txt, 122378, "text/plain"
txt.meta.endpoint  # "wasde1026.txt": the file's name as upstream prints it
```

`search_publications("wasde")` finds a publication's identifiers, and
`list_releases("wasde", since=date(2026, 1, 1))` its releases since a date, newest first.
`list_recent_releases(since=date(2026, 10, 20))` lists what USDA released across every
publication since a date, latest catalogued first; it needs `since` or `page`: every
release of every publication is 61,681 pages, about 34 hours at 30 requests a minute.
A walk from a `since` before 2025-09-12, ESMIS's migration, is refused, as the older
ids do not follow the release dates; `list_releases` or `page` serves older dates.

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
`usda_esmis_list_publications` says how to filter (unfiltered, its packaged table is
about 600 KB, so the tool returns its first 200 rows, while `list_publications()` in
Python and its HTTP route return the whole table), `usda_esmis_list_releases` and
`usda_esmis_list_recent_releases` name `since`, `until` and `page`, and
`usda_esmis_search_publications` names `page`.
`download_release_file` is no tool and no route: a bulk task, Python only (ADR-0019).
`--http` serves streamable HTTP instead of stdio.

## Status

<!-- Core's family check (tests/test_family.py) reads this table: keep the "## Status"
heading and the "Task function" column. Each row's Task function cell starts with the
task's name in backticks, alone or as its call (`get_data(code, year)`); several tasks in
one row are backticked names separated by commas; prose may follow. The tables list
exactly tasks.__all__. -->

| Upstream operation | Task function | MCP tool | Status |
| --- | --- | --- | --- |
| `esmis_api_agency_findAll` | `list_agencies()` | `usda_esmis_list_agencies` | alpha |
| `esmis_api_publication_findAll`, every page, packaged (fetched 2026-10-27; no request) | `list_publications(search=None, agency_acronym=None)` | `usda_esmis_list_publications` | alpha |
| `esmis_api_publication_search`, every page unless `page` is given | `search_publications(query, page=None)` | `usda_esmis_search_publications` | alpha |
| `esmis_api_publication_findByIdentifier` | `get_publication(publication_identifier)` | `usda_esmis_get_publication` | alpha |
| `esmis_api_release_findByIdentifier`, pages walked newest first unless `page` is given | `list_releases(publication_identifier, since=None, until=None, page=None)` | `usda_esmis_list_releases` | alpha |
| `esmis_api_release_findAll`, every publication's releases, pages walked from 0 down to `since` (to the first page whose newest release is dated more than 14 days before it) unless `page` is given | `list_recent_releases(since=None, until=None, page=None)`, refused without `since` or `page`, and for a walk from a `since` before 2025-09-12 | `usda_esmis_list_recent_releases` | alpha |
| `esmis_api_release_findById` | `get_release(release_id)` | `usda_esmis_get_release` | alpha |
| `esmis_api_release_findByIdentifier`, page 0 | `get_latest_release(publication_identifier)` | `usda_esmis_get_latest_release` | alpha |
| `esmis_api_release_findById` | `list_release_files(release_id)` | `usda_esmis_list_release_files` | alpha |
| `esmis_api_release_findById`, then the file | `download_release_file(release_id, format=None, dest=None, *, name=None)`, a bulk task: `dest` required, the file chosen by `format`, `name` or both | none, Python only | alpha |

## Where the live API deviates from its OpenAPI document (probed 2026-10-27)

The OpenAPI document in `docs/upstream/openapi/esmis_public_api.yaml` is the reference
for names and parameters; the live API answers differently in these points:

- every `id` is a JSON string, not an integer; the walk of every `/publication/findAll`
  page on 2026-10-27 (pages 0 to 100) found 2522 publications with distinct ids, each a
  string of digits;
- `Publication.agency`, `.identifier` and `.agency_acronym` are arrays, not strings;
- `agency_acronym` is absent on the publications the four other publication operations
  answer, which carry `publication_agency_export_1` instead; `/publication/findAll`
  carried `agency_acronym` on all 2522 publications of the walk and
  `publication_agency_export_1` on none;
- `Publication.frequency` printed `""` on one publication of the walk (1172), a value
  the document's enumeration does not list; `status`, `subscribable` and
  `resource_type` held only the document's values;
- the list wrapper has `filters`, `sorters` and `system` (`{"page_key": "page"}`)
  beside `pager` and `results`;
- `/publication/search` without `query`, or with an empty one, answers 200 with
  `"pager": []` and empty results, although the document makes `query` required;
- absence answers differ per lookup, as recorded: an unknown id answers 404
  `{"message": ""}` at `/agency/findById`, `/publication/findById`, `/release/findById`
  and `/release/findByPubId`; an unknown name answers 200 with nothing,
  `/agency/findByAcronym` an empty array, `/publication/findByAgency`,
  `/publication/findByIdentifier` and `/release/findByIdentifier` empty results with
  every pager count 0;
- an identifier carrying `/` (`Market and Trade Economics Division/FDS`) cannot be
  looked up: the web server answers `%2F` in a path with its own HTML 404, and a raw
  slash is no route; every publication recorded with such an identifier has another
  without it (`FDS`);
- `page` is 0-based and a page holds 25 items, as the YAML's defaults say; undocumented
  are that the page size is fixed and that a page past the last answers empty results
  with `current_page` clamped;
- the orders are undocumented: `/release/findAll` comes highest id first, the newest
  created, for the releases catalogued since ESMIS's migration, whose first WASDE
  release is 791996 of 2025-09-12, with `release_datetime` only mostly in that order
  (page 0 of 2026-10-27 runs 2026-10-26, 2026-10-09, 2026-10-23, and page 1 of
  2026-10-28 runs 2026-10-09, 2026-09-28, 2026-10-07; 14 days, release 796123 against
  796122, is the largest gap on those two pages, which `list_recent_releases` takes as
  its walk's tolerance); below the migration the ids do not follow the dates (WASDE's
  96165 to 96171 run May, April, March, February, August, July and June 2025, and 95511
  of 2022-08-12 and 95621 of 2013-08-12 sit above 95482 of 2025-01-10), so
  `list_recent_releases` refuses a walk from a `since` before 2025-09-12; a
  publication's releases (`/release/findByIdentifier`) come latest `release_datetime`
  first whatever their ids, as recorded on WASDE's pages 0 and 1 (50 releases,
  2026-10-09 back to 2022-08-12); publication lists follow no id order
  (`/publication/findAll` page 0: ids 2425, 1801, 1861, 1922;
  `/publication/search?query=wasde`: 1762, 1831, 1154);
- `release_datetime` is `YYYY-MM-DDTHH:MM:SS+0000` (a zone, no colon);
- `Release.files` paths take two shapes: recent releases use
  `/sites/default/release-files/{release id}/{name}.{ext}`
  (`/sites/default/release-files/796099/wasde1026.txt`), older ones the hashed
  three-segment path the YAML's example shows
  (`/sites/default/release-files/8336h188j/2514qk05k/j0991c960/prog3925.pdf`);
- `Publication.upcoming_releases` is `[]` on most publications: the walk found items on
  24 of 2522, 67 in all, each printed with an Eastern offset
  (`2026-10-28T15:00:00-0400` and `2026-11-04T15:00:00-0500` for publication 1863),
  where `release_datetime` prints `+0000`; the YAML lists no release-calendar operation;
- the zone label of release times: the API prints `release_datetime` with `+0000` and
  the release page its `datetime` with `Z` (`2026-10-09T12:00:00+0000` and
  `datetime="2026-10-09T12:00:00Z"` for the October 2026 WASDE), while the release
  calendar, whose settings say `timeZone: "America/New_York"`, puts the WASDE releases
  that `/release/findByIdentifier/wasde` (page 0) prints as `2025-09-12T12:00:00+0000`
  and `2025-12-09T12:00:00+0000` at `2025-09-12T12:00:00-04:00` and
  `2025-12-09T12:00:00-05:00`, and the October release's own file answers
  `HEAD /sites/default/release-files/796099/wasde1026.txt` with
  `Last-Modified: Fri, 09 Oct 2026 16:01:00 GMT`, 12:01 Eastern. The `+0000`/`Z` label
  is contradicted by upstream's own calendar and file timestamps, which fit a noon
  Eastern wall-clock time (the recorded download of `wasde1026.txt` answers the same
  `Last-Modified`); the tasks keep `release_datetime` as printed, and those about one
  release put its wall-clock time, the `+0000` dropped, into `meta.published_at` with
  `published_at_naive` set (ADR-0022; CLAUDE.md, release times);
- the release calendar page (`docs/upstream/pages/release-calendar.md`) held 3776
  events, drawn from a `publication_upcoming_releases` field (each event's
  `startField`), while the API's `Publication.upcoming_releases` lists 67 upcoming
  releases on 24 publications; every calendar event is classed `fc-event-past`, future
  ones included, and WASDE's events stop at 2025-12-09.

## Upstream terms and attribution

Data comes from USDA ESMIS (https://esmis.nal.usda.gov) under its own terms of use;
this package adds no rights to it. The documentation and the release files are works of
the United States Government (USDA National Agricultural Library, ESMIS), in the public
domain in the United States (17 U.S.C. § 105); a suggested credit line is "Source:
USDA National Agricultural Library, ESMIS". The pages the snapshot reads print no
copyright line, and USDA's policy page is cited in `docs/upstream/FETCHED.md`,
Attribution. Documentation snapshot: `docs/upstream/`.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
