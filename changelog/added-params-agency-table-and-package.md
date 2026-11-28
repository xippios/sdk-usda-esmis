- `xippios.usda.esmis.params` exports `AGENCIES`, the packaged agency table's acronyms with
  their titles, which `list_publications` checks an `agency_acronym` against and by which
  every answer that holds a release or a publication names its agencies in `meta.names`,
  and `PACKAGE`, the name of the package whose `reference/` holds the packaged tables.
  `PACKAGED_LISTS` names the two tables, `agency` and `publication`, where it named none.
  (https://github.com/xippios/sdk-usda-esmis/pull/64)
