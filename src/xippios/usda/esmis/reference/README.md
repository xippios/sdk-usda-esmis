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

Rules:

- Files come from the upstream through `scripts/refresh_reference.py`
  (`/refresh-reference-data`), written with `PackagedList.write`, never typed in by hand.
  The template's script also regenerates `enums.py` with one
  `xippios.core.reference.render_enums` call; this package generates no enum from them
  (0.1.0): the three enumerations of `Publication` (`Status`, `Subscribable`,
  `ResourceType`) are the OpenAPI document's, hand-written in `models.py`, and neither
  table is a value list.
- Files keep upstream's names: records under upstream's field names
  (`UpstreamModel.dump_upstream`), a field upstream leaves out as `null`.
- Every file has a row below naming the endpoint it came from and the UTC time of its
  first request; the script rewrites the rows.
- Agents get a lookup task for every packaged list so they can form valid calls:
  `list_publications` (`usda_esmis_list_publications`) for the publications, and
  `list_agencies` (`usda_esmis_list_agencies`), which asks upstream, for the agencies.
- A multi-tenant source packages no tenant data (ADR-0014), only lists that are the same
  for every tenant; ESMIS has no tenants.

| File | Origin | Fetched |
| --- | --- | --- |
| (none yet) | | |
