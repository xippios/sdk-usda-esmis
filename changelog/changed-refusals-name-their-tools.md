- A refusal that names another task names its MCP tool too: an unknown identifier in
  `get_publication` and `get_latest_release` points to `search_publications` (over MCP,
  the tool `usda_esmis_search_publications`), and `list_recent_releases`'s refusal of a
  `since` before 2025-09-12 to `list_releases` (`usda_esmis_list_releases`).
  (https://github.com/xippios/sdk-core/issues/111)
