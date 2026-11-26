- The nightly live run compares the packaged agency table with the list ESMIS serves now
  by core's comparison, and sends no probe of the base URL. The publication table, 101
  requests a fetch, is held by the reference refresh before each release. Both refresh
  scripts run on core's frames, the snapshot fetched through core's client, and the
  reference refresh sends each of its requests once.
  (https://github.com/xippios/sdk-usda-esmis/issues/36, https://github.com/xippios/sdk-usda-esmis/issues/37, https://github.com/xippios/sdk-usda-esmis/issues/38)
