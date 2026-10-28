# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [Unreleased]

### Added

- `download_release_file` takes `name=`, keyword only: the file of that name as
  `list_release_files` prints it, alone or with `format`, which it must then match. A
  release that keeps an original and a revised file of one format is reached this way:
  the WASDE of 2013-08-12 (release 95621) lists `ORIGwasde-08-12-2013.xml` before
  `wasde-08-12-2013.xml`, and `format="xml"` alone takes the first. Neither `format` nor
  `name`, or a name the release lacks, raises `InvalidRequestError` naming the release's
  files. Recorded: `tests/fixtures/release_find_by_id/95621.json`.
- `ReleaseFile.from_url(url)`, the name and format an item of `Release.files` prints,
  and `Release.release_files()`, a release's files in upstream order, read without a
  request: the reading `list_release_files` and `download_release_file` use, which the
  packages that depend on this one call rather than copy.
- `list_recent_releases(since=None, until=None, page=None)` and its MCP tool
  `usda_esmis_list_recent_releases`: what USDA released across every ESMIS publication
  since a date, from `esmis_api_release_findAll`, the one documented operation without
  a task until now. `page` given returns that page; `since` walks the pages from page 0
  and stops after the first page whose newest release is dated more than 14 days before
  `since`, the largest gap recorded between the catalogue order (highest id first) and
  the release dates. `since` and `until` keep the releases whose printed date lies
  between them. A call with neither `since` nor `page`, or with `until` alone, raises
  `InvalidRequestError` before any request: the whole list is 1,542,025 releases on
  61,681 pages (2026-10-27), about 34 hours at 30 requests a minute. The tool keeps the default
  cap with a note naming `since`, `until` and `page`. Recorded:
  `tests/fixtures/release_find_all/page1.json`.

### Changed

- Adopted sdk-template v0.3.0, with xippios-core 0.3.0 and conventions 1.22 (conventions §15).
- Moved the download's fixture to `tests/fixtures/download_release_file/`, the task's
  name (conventions 1.22 §10), the recording unchanged.
- Corrected the live tests' tolerance docstring, which now says the packaged tables'
  refresh opens a PR only when a table changed, and the README's status-table comment,
  which no longer names `tasks_write.__all__` (the template v0.3.0 wording for a
  read-only package).
- `download_release_file(release_id, format=None, dest=None, *, name=None)`: `format`
  and `dest` are optional in the signature, so the positional
  `(release_id, format, dest)` keeps working, and `dest` is required when called. A
  `dest` left `None`, a directory or a path in a missing directory raises
  `InvalidRequestError` before any request, where a bad `dest` raised core's
  `ValueError` after the release lookup. `meta.request` holds `name` when given.
- The MCP tools `usda_esmis_list_releases` and `usda_esmis_search_publications` keep the
  default cap, 200 rows or 64 KB, with a note of their own: `list_releases`'s names
  `since`, `until` and `page`, `search_publications`'s names `page`.
- The cap's prose left the docstrings of `list_publications`, `search_publications` and
  `list_releases`, which are the tool descriptions: the cap's notes carry it.

## [0.1.0] - 2026-10-27

### Added

- Scaffold from [sdk-template](https://github.com/xippios/sdk-template): configured
  client for USDA ESMIS, MCP server and FastAPI router wired to the task layer, test
  harness with core's family check, CI, the nightly live tests and the release train,
  in which a release PR's merge tags and publishes.
- Upstream documentation snapshot in `docs/upstream/`, fetched 2026-10-27, and its
  capture script `scripts/refresh_upstream.py`: the ESMIS OpenAPI document verbatim,
  the WASDE publication page and its newest release's page as Markdown, and an excerpt
  of the release calendar, with `FETCHED.md` recording every fetch.
- README and CLAUDE.md name ESMIS in full; the README lists where the live API deviates
  from its OpenAPI document, as probed on 2026-10-27.
- Attribution: the README and `docs/upstream/FETCHED.md` state that the ESMIS
  documentation and release files are works of the United States Government, in the
  public domain in the United States (17 U.S.C. § 105), and cite USDA's policy page.
- Endpoint wrappers for the twelve operations of the ESMIS catalog (agencies,
  publications, releases) under `xippios.usda.esmis.api`, the models `Agency`, `Pager`,
  `Publication`, `Release`, `PublicationResults` and `ReleaseResults` typed as the wire
  sends them, with the `StrEnum`s `Status`, `Subscribable` and `ResourceType` that a walk
  of every publication page confirmed, and the client's `classify`: an unknown id, which
  the four lookups by id answer with HTTP 404, is `NotFoundError`, and an identifier
  carrying `/`, which ESMIS refuses, `InvalidRequestError`; the lookups by acronym or
  identifier answer an unknown one with an empty HTTP 200, returned as such. Recorded
  fixtures and replay tests in `tests/test_api.py`; CLAUDE.md gains the ESMIS specifics.
- Seven catalog tasks, each an MCP tool and an HTTP route: `list_agencies`,
  `search_publications` and `get_publication`, `list_releases` (newest first, with
  `since`, `until` and `page`), `get_release`, `get_latest_release` and
  `list_release_files` (each file's URL, name and format, the model `ReleaseFile`).
  `meta.endpoint` names the operationId, `meta.total` upstream's count for the paged
  lists, `meta.vintage` the release id; `meta.published_at` of a task about one release
  is its `release_datetime` as printed, the `+0000` dropped, with `published_at_naive`
  set (ADR-0022). An unknown identifier raises `NotFoundError` where one record is asked
  for and gives the empty list from `list_releases`.
- `download_release_file(release_id, format, dest)`, a bulk task in `BULK_TASKS`,
  Python only: it streams one file of a release to the path the caller names with
  core's `download`, nothing cached, `meta.endpoint` the file's name as upstream prints
  it (`wasde1026.txt`), `meta.published_at` the release's printed time with the flag.
  Replay tests for every task, the tools called end to end, the October 2026 WASDE
  `.txt` recorded whole for the download's replay, and live tests for every task and
  for the release order the release tasks rely on.
- Two packaged reference tables, written by `scripts/refresh_reference.py` with core's
  `PackagedList.write` on 2026-10-27: `reference/publication.json`, the 2522
  publications of every page of `/publication/findAll`, each the eight columns of the
  new projection `PublicationRow`, and `reference/agency.json`, the 9 agencies with every
  field.
- `list_publications(search=None, agency_acronym=None)`, an MCP tool and an HTTP route
  answered from the packaged publication table without a request: `search` matches the
  id, an identifier or the title (core's `matches`), `agency_acronym` an acronym the row
  lists, and an acronym the packaged agency table lacks is refused with core's
  `UnknownCode`, naming the closest. `meta.retrieved_at` is the table's fetch time and
  `meta.endpoint` `esmis_api_publication_findAll` (ADR-0022). Its MCP tool keeps the
  default cap, 200 rows or 64 KB, with a note naming the two filters, since the whole
  table is 599,402 bytes; Python and HTTP callers get the whole table (ADR-0016). Live
  tests compare the packaged agencies and the publication count with upstream.

### Changed

- `xippios-core` 0.3.0 from PyPI (`core_version` 0.3.0, `~=0.3.0`; template v0.2.2),
  which brings the api.data.gov gateway module (C14, unused by this keyless source),
  `AsyncClient.download` for bulk files (C15, ADR-0019) and ADR-0022's
  `ResultMeta.published_at_naive`, which the release tasks need.
- `scripts/refresh_reference.py` refreshes the two packaged tables through `api/` (102
  requests: the agencies and the 101 publication pages, bounded by `total_pages`) and
  rewrites the provenance rows of `reference/README.md`; it generates no `enums.py`, and
  `params.PACKAGED_LISTS` is empty, since the tables are `PackagedList` files that
  `tasks.py` reads directly.
