# Verification harness

These scripts are the live verification harness for the LiteLLM MCP admin
server. They are archived here because they have already been lost once when a
pod restarted, and rebuilding them from scratch is expensive.

They are not unit tests and they do not run in CI. They run inside the
`litellm-mcp-admin` pod, driving the real admin API on `127.0.0.1:8080` and the
real MCP endpoint, so they need that pod's network namespace and filesystem to
mean anything at all.

They read their credentials at runtime from `/data/config.json`, taking the
admin console password and the MCP auth token from it. No secret is stored in
this directory and none should ever be added: a literal key here would be a
plaintext production credential living in the repository, and it would also make
the assertion that uses it silently vacuous the moment the key is rotated.

`mcpc.py` is the shared client. It loads that config, logs in to obtain a JWT,
wraps the admin REST API, and implements a small stateful streamable-HTTP MCP
session that can list and call tools. It is imported by every suite and is never
run on its own.

The `t_*.py` files are the five suites. `t_pages.py` checks that every admin
console page's backing API is reachable, authenticated and LiteLLM-shaped.
`t_settings.py` checks that every switch on the settings pages really changes
the live MCP surface. `t_logs.py` exercises the log page end to end, including
the SSE stream. `t_tools_ro.py` checks the read-only gating, so that a gated
tool explains itself rather than answering "Unknown tool". `t_tools_all.py`
exercises all 40 `litellm_*` tools over the live endpoint, creating only
`mcptest-` prefixed resources and tearing them down afterwards.

Run them with `python3 t_xxx.py` from a directory that also contains `mcpc.py`,
since each suite adds its own directory to `sys.path` in order to import it.
The suites that mutate configuration restore what they changed in a `finally`
block, so an interrupted run should not leave the connector crippled.
