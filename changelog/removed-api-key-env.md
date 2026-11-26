- `xippios.usda.esmis._client` no longer declares `API_KEY_ENV`, a key variable that no
  code read: the API is keyless, and `ENV_VARS` names what a host sets, nothing.
  (https://github.com/xippios/sdk-template/issues/300)
