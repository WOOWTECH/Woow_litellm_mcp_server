# Contributing

Thanks for helping improve the Woow LiteLLM MCP server suite.

## Dev setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[admin,test]"
```

The three installable pieces:

- `woow_litellm_mcp_server` — the FastMCP server (component 1). Minimal deps.
- `litellm_mcp_admin` — the LiteLLM-specific admin layer (component 3).
- `mcp_admin_core` — the product-agnostic core (component 2). Ships separately via
  `mcp_admin_core.pyproject.toml`; keep it byte-compatible with upstream — only
  comments should differ from the EMQX reference.

## Running the server (development only)

Nothing authenticates this interface. In the deployed topology the server never runs
this way — the admin console spawns it as a child on `127.0.0.1:3000` and the only
public door is the console's token-gated proxy. Keep the dev instance on loopback too.

```bash
export LITELLM_MCP_BASE_URL=http://localhost:4000
export LITELLM_MCP_MASTER_KEY=sk-...          # never commit a real key

# stdio (local MCP clients)
python -m woow_litellm_mcp_server.server --transport stdio

# Streamable-HTTP, loopback
python -m woow_litellm_mcp_server.server --transport http --host 127.0.0.1 --port 8000 --path /mcp/
```

## Running the admin console

```bash
export MCP_ADMIN_CONFIG=./data/config.json
export JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
uvicorn litellm_mcp_admin.main:app --host 0.0.0.0 --port 8080
```

## Tests

```bash
pytest                 # unit tests; live probes excluded by default
pytest -m live         # opt-in live probes against a real LiteLLM gateway
```

## Test invariants (please keep these green)

1. **Registry ↔ tools** (`test_mcp_surface.py`) — every tool declared in
   `registry.py` must be registered by exactly one tool module, and vice-versa.
   Adding a tool means: declare a `ToolSpec` in `registry.py`, implement it in the
   matching `tools/<category>.py`, and (if it returns structured data) add/extend a
   model in `models.py`.
2. **Gating** (`test_gating.py`) — read-only mode must drop every `dangerous`
   tool; category/tool/operation gates must compose.
3. **Borrowed client** (`test_client_lifetime.py`) — the DI handle from
   `deps.litellm_client` must never be closeable and must survive across many tool
   calls. Do not add `close()`/`aclose()` to `LiteLLMHttp`.
4. **Connection wiring** (`test_connection_wiring.py`) — admin `connection` keys,
   upper-cased, must equal the `Settings` env names (`litellm_mcp_base_url` →
   `LITELLM_MCP_BASE_URL`). Rename both ends together.
5. **Admin tools API** (`test_admin_tools_api.py`) — `/api/tools` GET/PUT shapes
   and `apply_to_runtime` writing switches into `mcp_server.env`.

## Conventions

- Destructive tools carry a `[DESTRUCTIVE]` docstring prefix **and** the
  `destructive(...)` annotation.
- Never send `null` query params or body fields — use `prune_none`.
- Never hard-code the master key or any secret. Everything comes from the
  environment / config store / k8s Secret.
- The SPA catch-all route shadows late-added routers: product routers MUST be
  passed to `create_app(extra_routers=[...])`.

## Commit / PR

- Keep `mcp_admin_core` changes product-agnostic.
- Run `pytest` and `ruff check .` before opening a PR.
