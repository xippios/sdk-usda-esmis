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
