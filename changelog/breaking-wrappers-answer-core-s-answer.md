- The endpoint wrappers under `xippios.usda.esmis.api` return core's `Answer`, the parsed
  model as its `payload` beside `retrieved_at`, the time the client retrieved it, in place
  of the bare model, so a caller of a wrapper reads `.payload`. The tasks' answers keep
  their shape. (https://github.com/xippios/sdk-core/issues/479)
