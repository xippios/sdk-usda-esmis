- `xippios.usda.esmis.mcp.build()` returns the read-only tool set the entry point serves,
  core's `ToolSet` with the caps of `tasks.MCP_CAPS`, so a host serves the same tools beside
  other sources' in one server. `ENV_VARS`, beside `SOURCE`, names the variables the package
  reads: none, as the API is keyless. (https://github.com/xippios/sdk-core/issues/245,
  https://github.com/xippios/sdk-template/issues/81)
