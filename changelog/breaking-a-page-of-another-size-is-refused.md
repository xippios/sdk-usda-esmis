- `list_releases`, `list_recent_releases` and `search_publications` refuse a page whose
  pager states another size than 25 with `InvalidRequestError` and return nothing, where
  their walks counted offsets in pages of 25 whatever the pager said. The refusal names the
  request that was sent and `page`, which reads one page as upstream pages it.
  (https://github.com/xippios/sdk-usda-esmis/issues/27, https://github.com/xippios/sdk-usda-esmis/issues/74)
