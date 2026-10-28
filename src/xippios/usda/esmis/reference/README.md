# Reference data for USDA ESMIS

Two tables of the ESMIS catalog ship here as packaged lists, versioned with the package,
each the records of one upstream operation as `scripts/refresh_reference.py` fetched
them, in the file shape of core's `PackagedList` (`param`, `endpoint`, `fetched`, `note`,
`records`; conventions §3, ADR-0022):

- `publication.json`: every publication `esmis_api_publication_findAll` lists, a walk of
  all its pages, each record the eight columns of `models.PublicationRow` (`id`,
  `identifier`, `title`, `agency_acronym`, `publication_agency_export_1`, `frequency`,
  `status`, `resource_type`), a projection of `Publication`; `list_publications` answers
  from it.
- `agency.json`: every agency `esmis_api_agency_findAll` lists, every field of `Agency`;
  `list_publications` checks its `agency_acronym` against it. `list_agencies` stays
  live: it asks upstream.

They load through `xippios.core.PackagedList`, which also builds the answer's `meta`
(`retrieved_at` the file's `fetched`, `endpoint` the operationId):

```python
from xippios.core import PackagedList

from xippios.usda.esmis.models import PublicationRow

table = PackagedList.load("xippios.usda.esmis", "publication")
rows = table.parse(PublicationRow, source="usda-esmis")
```

Each file holds `{"param", "endpoint", "fetched", "records"}` and an optional
`"note"`, upstream's records under upstream's field names (`UpstreamModel.dump_upstream`),
a field upstream leaves out as `null`, written by `scripts/refresh_reference.py`
(`/refresh-reference-data`) with `PackagedList.write`, never by hand, and read with
`PackagedList.load`; the script rewrites the table below. No enum is generated from them:
the three enumerations of `Publication` (`Status`, `Subscribable`, `ResourceType`) are the
OpenAPI document's, hand-written in `models.py`, and neither table is a value list. The
agents' lookup tasks are `list_publications` (`usda_esmis_list_publications`) for the
publications and `list_agencies` (`usda_esmis_list_agencies`), which asks upstream, for
the agencies. One row per file: Origin is the endpoint it was fetched from, none being
rebuilt from a `docs/upstream/` file; Fetched is the UTC time of that fetch's first
request.

| File | Origin | Fetched |
| --- | --- | --- |
| `agency.json` | `esmis_api_agency_findAll`, `GET /api/v1/agency/findAll`, one request (9 records) | 2026-10-27T17:24:45Z |
| `publication.json` | `esmis_api_publication_findAll`, `GET /api/v1/publication/findAll`, every page, 0 to 100 (2522 records) | 2026-10-27T17:24:48Z |
