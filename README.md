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
  release-calendar endpoint exists.

## Upstream terms and attribution

Data comes from USDA ESMIS (https://esmis.nal.usda.gov) under its own terms of use;
this package adds no rights to it. Documentation snapshot: `docs/upstream/`.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
