# Woow LiteLLM MCP Server

An MCP-server **suite** for administering a [LiteLLM](https://github.com/BerriAI/litellm)
gateway. It ports the architecture of
[`WOOWTECH/Woow_emqx_mcp_server`](https://github.com/WOOWTECH/Woow_emqx_mcp_server)
to LiteLLM: a FastMCP server that exposes LiteLLM's admin API as MCP tools, a Web
admin console, and an encrypted reverse-proxy / admin-core that lets Claude (or any
MCP client) reach the tools over a single hardened endpoint.

繁體中文說明請見 [README_zh-TW.md](./README_zh-TW.md)。

---

## What's in the box

| Component | Package | Role |
|-----------|---------|------|
| **1. MCP server** | `woow_litellm_mcp_server` | FastMCP server exposing 38 LiteLLM tools (stdio or Streamable-HTTP). |
| **2. Admin console** | `litellm_mcp_admin` | FastAPI + React GUI to configure connection, toggle tools, rotate the proxy token, tail logs. |
| **3. Admin core / encrypted proxy** | `mcp_admin_core` | Product-agnostic core: JWT auth, file-backed config store, MCP subprocess manager, and the reverse proxy that fronts the MCP child. |
| **4. Frontend SPA** | `frontend/` | Vite + React admin UI shared with the reference, with LiteLLM overrides. |

### Architecture

```
                       ┌───────────────────── single container ──────────────────┐
  Claude / MCP client  │                                                                     │
        │              │  uvicorn  litellm_mcp_admin.main:app   (0.0.0.0:8080)               │
        │  HTTPS        │    ├─ AuthMiddleware (JWT)  ── /api/*  admin GUI + API              │
        ▼              │    ├─ proxy  /private_{token}/mcp/  ──┐                              │
  Cloudflare edge ─────┼──► └─ SPA (React)                     │ reverse proxy (nginx-free)   │
                       │                                       ▼                              │
                       │             McpProcessManager ► woow_litellm_mcp_server (127.0.0.1)  │
                       │                                       │  transport=http  /mcp/       │
                       └─────────────────────────────────┼────────────────────────────┘
                                                                ▼
                                        LiteLLM gateway  (Bearer master key, port 4000)
```

The MCP child binds to loopback only. The single path in is the proxy route
`/private_{token}/…`, whose `{token}` must equal the stored `mcp_auth_token`.
"Encrypted/private" here means **path-token isolation + JWT-gated GUI + TLS at the
edge** — there is no at-rest payload crypto; the config JSON is plaintext protected
by file perms (`chmod 600`) and secret-masking in the API.

---

## Tool surface (38 tools)

Every tool is prefixed `litellm_`. The registry
(`woow_litellm_mcp_server/registry.py`) is the single source of truth; the gate and
the admin GUI both read it.

| Category | Tools |
|----------|-------|
| **models** | `list_models`, `model_info`, `model_group_info`, `add_model`, `update_model`, `delete_model` ⚠ |
| **chat** | `chat_completion`, `token_counter` |
| **keys** | `generate_key`, `list_keys`, `key_info`, `update_key`, `delete_key` ⚠, `block_key` ⚠, `unblock_key`, `regenerate_key` |
| **teams** | `create_team`, `list_teams`, `team_info`, `update_team`, `delete_team` ⚠, `team_member_add`, `team_member_delete` ⚠ |
| **users** | `create_user`, `list_users`, `user_info`, `update_user`, `delete_user` ⚠ |
| **spend** | `spend_logs`, `global_spend_report`, `spend_calculate` |
| **health** | `health`, `health_readiness` |
| **plugins** (Claude-Code skill hub) | `list_plugins`, `register_plugin`, `enable_plugin`, `disable_plugin`, `skill_hub` |

⚠ = destructive (`[DESTRUCTIVE]` docstring prefix). Read-only mode
(`LITELLM_MCP_READONLY=true`) drops every destructive tool at registration time.

### Gating

Three levels plus read-only, all env-driven (or set from the GUI):

- `LITELLM_MCP_DISABLED_CATEGORIES` — drop whole families (`keys,teams`).
- `LITELLM_MCP_DISABLED_TOOLS` — drop individual tools (`litellm_delete_key`).
- `LITELLM_MCP_DISABLED_OPERATIONS` — drop CRUD operations (`tool:op` or bare `op`).
- `LITELLM_MCP_READONLY` — drop everything mutating.

---

## Quickstart

### 1. Bare MCP server (local, stdio or HTTP)

```bash
pip install .                      # installs component 1 only
export LITELLM_MCP_BASE_URL=http://localhost:4000
export LITELLM_MCP_MASTER_KEY=sk-...      # never commit this

# Streamable-HTTP (the deployed default):
python -m woow_litellm_mcp_server.server --transport http --host 0.0.0.0 --port 8000 --path /mcp/

# or stdio for a local MCP client:
python -m woow_litellm_mcp_server.server --transport stdio
```

Config is read from the environment (`LITELLM_MCP_` prefix) — see
[`.env.example`](./.env.example).

### 2. Admin console via Docker Compose

```bash
cp .env.example .env               # set JWT_SECRET, LITELLM_MCP_* etc.
docker compose up --build          # serves the GUI on http://localhost:8080
```

The compose service builds the SPA (stage 1) and the Python image (stage 2), then
serves `litellm_mcp_admin.main:app` on `:8080`. Log in with the `admin_password`
from the config store (default `admin` — change it on first login), point the
**Connection** page at your LiteLLM gateway, and toggle tools on the **Tools** page.

### 3. Kubernetes (k3s, git-clone pattern — no image build)

The live deployment uses an `initContainer` that clones this **public** repo into
an `emptyDir`; the main `python:3.12-slim` container `pip install`s it and launches
the server on Streamable-HTTP. No private registry required. See
[`k8s-deploy.yaml`](./k8s-deploy.yaml) (it also documents the image-based path).

```bash
# 1) namespace + secret (the master key lives ONLY in the Secret, never in the repo)
kubectl apply -f k8s-secret.example.yaml       # after filling in the real key
# 2) the deployment + service
kubectl apply -f k8s-deploy.yaml
```

In-cluster consumers then reach it at
`http://litellm-mcp.litellm-mcp.svc.cluster.local:8000/mcp/`.

### 4. Kubernetes — admin console + encrypted proxy (registryless)

`k8s-deploy.yaml` alone gives you a bare, unauthenticated MCP server that is
safe only because it never leaves the cluster. To publish it, deploy
[`k8s-admin-deploy.yaml`](./k8s-admin-deploy.yaml) as well: same git-clone
trick, but it builds the SPA, seeds `/data/config.json` on a PVC, and runs the
admin console on `:8080` with the FastMCP child spawned on `127.0.0.1:3000`.

```bash
kubectl apply -f k8s-deploy.yaml         # namespace + litellm-mcp-secret
kubectl apply -f k8s-admin-deploy.yaml   # console + encrypted proxy + child
```

Point a Cloudflare tunnel (or any ingress) at
`http://litellm-mcp-admin.litellm-mcp.svc.cluster.local:8080` and the only
public MCP door is `/private_<mcp_auth_token>/mcp/`. Full design notes,
verification commands and the Bot Fight Mode caveat live in
[`docs/encrypted-proxy.md`](./docs/encrypted-proxy.md).

---

## Connecting Claude

Add the MCP endpoint as a custom connector. Through the admin proxy the URL is:

```
https://<your-admin-hostname>/private_<mcp_auth_token>/mcp/
```

Rotate `mcp_auth_token` from the **Tokens** page (or
`POST /api/tokens/rotate`) — the previous URL dies immediately. Optionally
front it with the Cloudflare Worker in [`cloudflare/`](./cloudflare/) to give
the MCP endpoint its own hostname and a clean anonymous fallback for OAuth
discovery.

---

## Configuration reference

All server settings use the `LITELLM_MCP_` prefix (`woow_litellm_mcp_server/settings.py`):

| Env var | Default | Meaning |
|---------|---------|---------|
| `LITELLM_MCP_BASE_URL` | `http://localhost:4000` | LiteLLM gateway base URL (no `/api/v5`). |
| `LITELLM_MCP_MASTER_KEY` | _(empty)_ | Bearer master/admin key. |
| `LITELLM_MCP_READONLY` | `false` | Drop every destructive tool. |
| `LITELLM_MCP_DISABLED_CATEGORIES` | _(empty)_ | CSV of categories to disable. |
| `LITELLM_MCP_DISABLED_TOOLS` | _(empty)_ | CSV of tool names to disable. |
| `LITELLM_MCP_DISABLED_OPERATIONS` | _(empty)_ | CSV of `tool:op` / `op` gates. |
| `LITELLM_MCP_DEFAULT_LIMIT` | `50` | Default page size. |
| `LITELLM_MCP_MAX_LIMIT` | `500` | Max page size. |
| `LITELLM_MCP_REQUEST_TIMEOUT` | `60` | Per-request HTTP timeout (s). |

Admin-console settings: `MCP_ADMIN_CONFIG` (config path), `JWT_SECRET`,
`JWT_EXPIRY_HOURS`.

---

## Development & tests

```bash
pip install -e ".[admin,test]"
pytest                     # unit tests (live probes are excluded by default)
pytest -m live             # opt-in: needs a reachable LiteLLM gateway
```

The suite mocks LiteLLM's HTTP API and asserts each tool builds the right request
and parses the response; the registry↔tools invariant keeps the surface honest.
See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

[MIT](./LICENSE)
