- `list_release_files` and its tool `usda_esmis_list_release_files` are removed: `get_release`
  answers the same release from the same request, its `files` holding each file's URL, and
  `Release.release_files()` reads their names and formats in Python. An unknown release id
  raises `NotFoundError` as before. (sdk-core ADR-0061, https://github.com/xippios/sdk-usda-esmis/issues/57)
