- `list_releases`, `list_recent_releases` and `search_publications` walk at most 24 pages
  without `page`, 24 requests and 96 attempts with the client's retries, in Python and over
  MCP alike, and a walk that needs more is refused with `InvalidRequestError` and returns
  nothing, naming upstream's count, the bound, the requests sent, the page reached and
  `page`. No walk sends a request at or past upstream's count. `list_releases("wasde")`
  without `since`, WASDE's 703 releases on 29 pages, is refused after its first request
  where it walked every page, and `list_recent_releases` without `since`, or with `until`
  alone, is refused after one request where it was refused before any. (sdk-core ADR-0034,
  https://github.com/xippios/sdk-core/issues/480, https://github.com/xippios/sdk-usda-esmis/issues/28)
