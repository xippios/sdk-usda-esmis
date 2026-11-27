- `list_releases` answers an identifier that ESMIS counts no release for with the empty list,
  `meta.total` 0 and a note in `meta.notes` that says so and names `search_publications`.
  A date filter that keeps no release writes no note, since upstream counted the releases.
  (sdk-core ADR-0061, https://github.com/xippios/sdk-usda-esmis/issues/59)
