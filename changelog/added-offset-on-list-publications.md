- `usda_esmis_list_publications` takes `offset`, the rows of a cut answer already shown,
  and answers the rows after them from the packaged table. The note of every page but the
  last names the `offset` to continue with, so a caller reads the whole table, or the
  2,008 publications of `AMS`, in further calls. (https://github.com/xippios/sdk-usda-esmis/issues/34)
