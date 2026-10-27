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
from xippios.usda.esmis import tasks

# result = tasks.<task>(...)
# result.data, result.meta.retrieved_at, result.meta.request
```

Task functions are listed in the status table below as they are added.

## MCP

```json
{
  "mcpServers": {
    "usda-esmis": {
      "command": "uvx",
      "args": ["--from", "xippios-usda-esmis[mcp]", "xippios-usda-esmis-mcp"]    }
  }
}
```

Tools are read-only and named `usda_esmis_<verb>_<noun>`. Results are capped, at
200 rows or 64 KB unless a tool has a cap of its own, with a note on how to see the rest.
`--http` serves streamable HTTP instead of stdio.

## Status

<!-- Core's family check (tests/test_family.py) reads this table: keep the "## Status"
heading and the "Task function" column. Each row's Task function cell starts with the
task's name in backticks, alone or as its call (`get_data(code, year)`); several tasks in
one row are backticked names separated by commas; prose may follow. The tables list
exactly tasks.__all__ and tasks_write.__all__. -->

| Upstream operation | Task function | MCP tool | Status |
| --- | --- | --- | --- |
| (none yet) | | | |

## Where the live API deviates from its OpenAPI document (probed 2026-10-27)

The OpenAPI document in `docs/upstream/openapi/esmis_public_api.yaml` is the reference
for names and parameters; the live API answers differently in these points:

- every `id` is a JSON string, not an integer;
- `Publication.agency`, `.identifier` and `.agency_acronym` are arrays, not strings;
- `agency_acronym` is absent on some publications, which carry
  `publication_agency_export_1` instead;
- the list wrapper has `filters`, `sorters` and `system` (`{"page_key": "page"}`)
  beside `pager` and `results`;
- `/publication/search` without `query` answers 200 with `"pager": []`;
- `findById` of an unknown id answers 404 `{"message": ""}`, `findByIdentifier` of an
  unknown identifier answers 200 with empty results;
- `page` is 0-based with 25 items per page fixed, a page past the last answers empty
  results with `current_page` clamped;
- lists come newest first (by id, descending), undocumented;
- `release_datetime` is `YYYY-MM-DDTHH:MM:SS+0000` (a zone, no colon);
- `Release.files` are absolute URLs;
- `Publication.upcoming_releases` was `[]` on every sampled publication, and no
  release-calendar endpoint exists;
- the zone label of release times: the API prints `release_datetime` as
  `2026-10-09T12:00:00+0000` and the release page prints
  `datetime="2026-10-09T12:00:00Z"`, while the release calendar's settings say
  `timeZone: "America/New_York"`, with WASDE's calendar events at noon Eastern
  (`2025-09-12T12:00:00-04:00`, `2025-12-09T12:00:00-05:00`), and that release's own
  file answers `HEAD /sites/default/release-files/796099/wasde1026.txt` with
  `Last-Modified: Fri, 09 Oct 2026 16:01:00 GMT`, 12:01 Eastern. The `+0000`/`Z` label
  is contradicted by upstream's own calendar and file timestamps, which fit a noon
  Eastern wall-clock time; how `published_at` treats it is decided before the tasks PR
  (ADR-0022);
- the release calendar page (`docs/upstream/pages/release-calendar.md`) held 3776
  events, drawn from a `publication_upcoming_releases` field (each event's
  `startField`), while the API's `Publication.upcoming_releases` answered `[]` for
  every sampled publication; every calendar event is classed `fc-event-past`, future
  ones included, and WASDE's events stop at 2025-12-09.

## Upstream terms and attribution

Data comes from USDA ESMIS (https://esmis.nal.usda.gov); this package adds no rights to
it. The pages the documentation snapshot reads state no terms of use and no copyright
line (`docs/upstream/FETCHED.md`, Attribution). USDA's Policies and Links page
(https://www.usda.gov/policies-and-links), to which the site's footer links, answered
403 to the capture script, so what it states stays unverified. Documentation snapshot:
`docs/upstream/`.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
