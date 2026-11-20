- Requires `xippios-core~=0.4.0`, from `~=0.3.0`. A `dest` that core's own download
  refuses, one whose directory went away after the task's check, raises
  `InvalidRequestError`, as the task's check before the release lookup does, where core
  0.3 raised `ValueError`. (https://github.com/xippios/sdk-core/releases/tag/v0.4.0,
  https://github.com/xippios/sdk-core/issues/152)
