# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [Unreleased]

### Added

- Scaffold from [sdk-template](https://github.com/xippios/sdk-template): configured
  client for USDA ESMIS, empty task layer, MCP server and FastAPI router
  wired to it, test harness with core's family check, CI, the nightly live tests and
  the release train, in which a release PR's merge tags and publishes.
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
  of every publication page confirmed, and the client's `classify`: an unknown id, which the four lookups by id
  answer with HTTP 404, is `NotFoundError`, and an identifier carrying `/`, which ESMIS
  refuses, `InvalidRequestError`; the lookups by acronym or identifier answer an unknown
  one with an empty HTTP 200, returned as such. Recorded fixtures
  and replay tests in `tests/test_api.py`; CLAUDE.md gains the ESMIS specifics.
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

### Changed

- `xippios-core` 0.3.0 from PyPI (`core_version` 0.3.0, `~=0.3.0`; template v0.2.2),
  which brings the api.data.gov gateway module (C14, unused by this keyless source),
  `AsyncClient.download` for bulk files (C15, ADR-0019) and ADR-0022's
  `ResultMeta.published_at_naive`, which the release tasks need. Until core released
  0.3.0 on 2026-10-27, this branch carried a git pin to sdk-core `main` (`787b60c`,
  then `cb8ecdf`) by the pin rule of the family roadmap §3; the pin is gone. The
  adoption of template v0.3.0 follows as a PR of its own.
- `scripts/refresh_reference.py` calls core's `render_enums`, since core 0.3.0 removed
  `render_str_enums` and `render_int_enums`: a hand-port ahead of template v0.3.0, which
  renders it. `enums.py` is not regenerated here.
