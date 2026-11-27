- Every refusal of a call as given says `Nothing was sent.` after its first sentence, the
  MCP adapter's refusal of an argument among them: an empty `query`, a `since` after
  `until`, a walk from a `since` before 2025-09-12, an `agency_acronym` the packaged list
  lacks, now checked by core's `check`, and a bad `dest`, now checked by core's
  `check_dest`. `download_release_file` refuses a call with neither `format` nor `name`
  before it looks the release up, and a choice the release cannot serve says that the
  release was read and no file requested. The refusals' classes are unchanged.
  (https://github.com/xippios/sdk-core/issues/481, https://github.com/xippios/sdk-usda-esmis/issues/33)
