- `get_latest_release` and its tool `usda_esmis_get_latest_release` are removed, by the
  boundary of a source package: a task that picks the latest release for its caller leaves.
  The same release is the first row of `list_releases(publication_identifier, page=0)`,
  a page that ESMIS lists latest first, one request as before. (sdk-core ADR-0060,
  https://github.com/xippios/sdk-core/issues/474)
