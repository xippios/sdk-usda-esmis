- What identifies a record stays positional and every other argument is keyword-only:
  `list_publications(*, search=None, agency_acronym=None)`, `search_publications(query, *,
  page=None)`, `list_releases(publication_identifier, *, since=None, until=None, page=None)`,
  `list_recent_releases(*, since=None, until=None, page=None)` and
  `download_release_file(release_id, *, dest, format=None, name=None)`, whose `dest` is
  required. A call that passes one of them by position raises `TypeError` before any request,
  and over MCP and HTTP nothing changes. (sdk-core ADR-0061, https://github.com/xippios/sdk-usda-esmis/issues/59)
