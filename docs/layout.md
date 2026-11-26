# Layout

The files that every source of the family holds are laid out once, in the tree of
sdk-template's README,
[What gets generated](https://github.com/xippios/sdk-template/blob/main/README.md#what-gets-generated).
This file holds what `xippios-usda-esmis` adds to that tree, a module, a task file, a
script or a test of its own, each with what it holds, and the change that adds one updates it.

The import path is `xippios.usda.esmis` (sdk-core ADR-0006); `src/xippios/` is a
namespace package, and so is `src/xippios/usda/`, the provider level.
Where the API's operation ids repeat across its services, `api/` keeps one module per service
instead, named after the service, and this file says so (conventions §2).

```
src/xippios/usda/esmis/
  _client.py       also classify, the catalog's 404 for an unknown id and the web server's
                   HTML 404 for an encoded slash, and the client's response cache
  models.py        also ReleaseFile, a release's file read from its URL, PublicationRow,
                   the packaged publication table's projection of Publication, and the
                   document's enumerations Status, Subscribable and ResourceType, written by
                   hand; the package holds no errors.py and no enums.py, since it refuses
                   with core's errors and no table makes an enum
  api/             one module per operation of the OpenAPI document, its operationId snake
                   cased without esmis_api_: agency_find_all, agency_find_by_acronym,
                   agency_find_by_id, publication_find_all, publication_find_by_agency,
                   publication_find_by_id, publication_find_by_identifier,
                   publication_search, release_find_all, release_find_by_id,
                   release_find_by_identifier and release_find_by_pub_id
  params.py        also AGENCIES, the agency table's acronyms and titles, which
                   list_publications checks and the models' NamedBy reads
  reference/       agency.json, every agency, and publication.json, every publication of
                   publication/findAll in PublicationRow's eight columns
tests/
  fixtures/        recorded exchanges, one directory per wrapper, and download_release_file/,
                   the WASDE .txt recorded through its task
  test_api.py      the endpoint wrappers on their recordings, and classify
  test_observed.py docs/upstream/OBSERVED.md as committed: the fixtures its notes cite
  test_refresh_reference.py  the reference script's declaration and its fetches, offline
  test_refresh_upstream.py   the capture script's declaration and its hooks, offline
docs/upstream/
  openapi/         esmis_public_api.yaml, the OpenAPI document, byte for byte
  pages/           the WASDE publication page, its newest release and the release calendar's
                   excerpt, as Markdown
  OBSERVED.md      the notes written by hand on what upstream does but never documents
```
