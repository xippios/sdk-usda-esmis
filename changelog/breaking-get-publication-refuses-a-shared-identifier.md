- `get_publication` refuses an identifier that two publications share with
  `InvalidRequestError`, naming both ids and `search_publications`, where it returned the
  first that ESMIS answered and dropped the other. 94 identifiers of the packaged table
  belong to two publications each, `AMS_1045` among them.
  (https://github.com/xippios/sdk-usda-esmis/issues/25)
