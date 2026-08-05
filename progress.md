# Progress log

Execution record for the plan in [`task_plan.md`](./task_plan.md). Newest phase last.

---

## Phase 1 — Ground truth · complete

Everything below was read from source or from a running service. Nothing was recalled.

**Tool registry.** Imported `woow_litellm_mcp_server.registry` and enumerated
`TOOL_REGISTRY`: **40 tools across 8 categories** — models 6, chat 2, keys 8, teams 7,
users 5, spend 3, health 2, plugins 7. **18** have `operations == ("read",)`. **8**
carry `dangerous=True`. The `ToolSpec` field order is
`name, category, description, method, path, operations, dangerous`.

Confirmed `litellm_mcp_admin/tool_registry.py` is a pure re-export adding only
`get_tool_by_name` and `get_all_tool_names` — the invariant behind
`tests/test_mcp_surface.py` holds.

**Gateway.** LiteLLM `v1.83.14-stable`, community edition, no `LITELLM_LICENSE`.
Internal `http://litellm.litellm.svc.cluster.local:4000`; public
`https://litellm.woowtech.io`. Health: `healthy_count: 5, unhealthy_count: 0`.

**Models.** Five deployments, all via OpenRouter:

| Name | Upstream | Context | In $/tok | Out $/tok |
|---|---|---|---|---|
| `claude-sonnet-4.5` | `openrouter/anthropic/claude-sonnet-4.5` | 1,000,000 | 3.0e-6 | 1.5e-5 |
| `glm-4.6` | `openrouter/z-ai/glm-4.6` | 202,800 | 4.0e-7 | 1.75e-6 |
| `minimax-m2` | `openrouter/minimax/minimax-m2` | 204,800 | 2.55e-7 | 1.02e-6 |
| `gpt-4o-mini` | `openrouter/openai/gpt-4o-mini` | — | 0 | 0 |
| `llama-3.3-70b` | `openrouter/meta-llama/llama-3.3-70b-instruct` | — | 0 | 0 |

`claude-sonnet-4.5` also reports cache write 3.75e-6 / cache read 3.0e-7, vision and
computer use; `glm-4.6` reports function calling, reasoning and prompt caching with
`max_tokens` 131,000.

**Live usage, 29 Jul – 5 Aug 2026.** Spend **$0.0111**, requests **174**, successful
**141**, failed **33**, tokens **7,467**, average **$0.0001** per request. Single
provider: `openrouter`.

**Process state.** `PID: 93 · Restarts: 14 · running`. Proxy timeout `86400` s. Log
buffer `Live · 1504 shown · 1504 buffered`.

**Frontend.** React Router 7 routes: `/login`, `/`, `/tools`, `/config`, `/tokens`,
`/logs`, `/permissions`, `/settings`, `*` → `/`. Auth is a JWT in `localStorage` under
`mcp-admin-token` **plus** an httpOnly cookie of the same name set by
`POST /api/auth/login` (body `{ password }`, `credentials: 'same-origin'`). The SSE
stream uses `EventSource` with `withCredentials: true` to keep the JWT out of the query
string.

**Deployment.** Namespaces `litellm` and `litellm-mcp`. Deployment
`litellm-mcp-admin`, `strategy: Recreate`, init chain `git-clone` (alpine/git) →
`spa-build` (node:20-alpine, ends `exit 0`) → `seed-config` (python:3.12-slim, seeds
`/data/config.json` on PVC `litellm-mcp-data`). `/repo` is an emptyDir. Cold start
≈ 2.5–3 min. `Dockerfile`: `node:20-alpine` → `python:3.12-slim`, `EXPOSE 8080`.

**Tests.** `133 passed, 2 deselected, 1 warning in 0.98s` — 135 collected across 13
modules.

**Size.** Python 7,206 lines; frontend JSX/JS 3,507 lines.

---

## Phase 2 — Screenshots · complete

Fifteen binaries captured and published, all confirmed with HTTP 201 and byte sizes
matching the source buffers exactly.

| File | Bytes |
|---|---|
| `icon_base.png` | 151,571 |
| `admin_console_login.png` | 21,620 |
| `admin_console_dashboard.png` | 77,963 |
| `admin_console_tools.png` | 404,067 |
| `admin_console_connection.png` | 71,440 |
| `admin_console_tokens.png` | 61,075 |
| `admin_console_logs.png` | 183,592 |
| `admin_console_permissions.png` | 106,897 |
| `admin_console_settings.png` | 183,832 |
| `litellm_proxy_ui_login.png` | 37,539 |
| `litellm_proxy_ui_dashboard.png` | 103,466 |
| `litellm_proxy_models.png` | 174,626 |
| `litellm_proxy_mcp_servers.png` | 103,028 |
| `litellm_proxy_usage.png` | 207,523 |
| `litellm_proxy_logs.png` | 643,603 |

The repository previously had no icon asset, so one was generated in-browser at
480×480 with a transparent background and published as `icon_base.png` to support the
reference repository's centred-icon front matter.

Three obstacles were hit and solved in sequence; they are recorded in
[`findings.md`](./findings.md) as OBS-1 through OBS-4 so the next person does not
rediscover them.

A probe artefact (`docs/.probe-binary.png`) used while diagnosing the encoding problem
was removed; a follow-up read of the contents API returned 404, confirming it is gone
from `main`.

---

## Phase 3 — Authoring · complete

| File | Content |
|---|---|
| `README.md` | English landing page. Centred icon, inline nav, five shields, `Overview` → `License`. Four architecture diagrams, each as ASCII **and** Mermaid with a written explanation. All fourteen screenshots with captions quoting on-screen text. Generated 40-row tool catalogue with totals row. 13-row test table. Newest-first changelog citing FINDING-001/002 and BUG-1..4. |
| `README_zh-TW.md` | Full Traditional Chinese mirror with the family's deliberate divergences: Chinese anchors, no separate API Reference section, an extra fixed-issues table under Testing, footer without the heart. |
| `docs/architecture.md` | Eight sections of design reasoning: registry vs decorators, the four gating axes, why registration-time gating beats call-time refusal, why the token lives in the path, process supervision, `Recreate` and `exit 0`, dual authentication, cross-namespace routing. |
| `docs/tool-catalog.md` | All 40 tools by category with purpose and danger notes, plus the explicit read-only 18 and dangerous 8 subsets and an add-a-tool procedure. |
| `docs/deployment.md` | Runbook: topology, init chain, first deploy, obtaining and rotating the public URL, applying a permission change, health checks, seven troubleshooting scenarios, upgrade and backup. |
| `docs/screenshots/README.md` | Image index with source route and what each shows, plus recapture guidance. |
| `task_plan.md` · `progress.md` · `findings.md` | This working-memory triad. |

The tool table in `README.md` and `docs/tool-catalog.md` was generated from
`TOOL_REGISTRY` rather than typed, which is the direct remedy for FINDING-001.

---

## Phase 4 — Publish and verify · complete

- [x] Screenshots and icon published (Phase 2).
- [x] Text files pushed to `main`, in five commits:

| Commit | Contents |
|---|---|
| `735422e` | `README.md` |
| `2829b2e` | `README_zh-TW.md` |
| `23e2821` | `docs/architecture.md`, `docs/tool-catalog.md`, `docs/deployment.md`, `docs/screenshots/README.md` |
| `4823d68` | `task_plan.md`, `findings.md` |
| `5972c18` | `progress.md` |

- [x] Tree verified against `origin/main`. All fifteen binaries carry byte sizes
  identical to the Phase 2 capture table above; the four supplementary documents and
  the working-memory triad are present at their expected paths.
- [x] Rendered-page check. Both `README.md` and `README_zh-TW.md` were loaded in a
  headless browser and inspected after a full scroll: **20 images each, 0 broken, 0
  still pending**, of which 15 resolve out of `docs/screenshots/`. Four Mermaid
  diagrams render to SVG on each page.
- [x] Two independent secret scans over the pushed tree. GitHub code search for
  `sk-or-v1` / `ghp_` / `sk-bcae` across the repository returned zero results; an
  independent regex sweep for OpenAI-style keys, GitHub PATs, fine-grained PATs,
  OpenRouter keys and JWTs matched only the documented placeholder
  `sk-local-dev-master-key` in `docker-compose.yml` and the `sk-placeholder-value-1234`
  fixture in `tests/test_admin_tools_api.py`. No live credential is in the tree.
- [x] Credential-rotation advisory delivered — recorded as OPEN-4 in
  [`findings.md`](./findings.md).

---

## Phase 5 — Topology audit against the live cluster · complete

Prompted by a challenge to the published claim that the suite is a single Deployment
with the server inside the console. Every step below is a read; nothing was modified.

| # | Query | Result |
|---|---|---|
| 1 | Deployments in `litellm-mcp` | **Two** — `litellm-mcp-admin` (12 h, container `admin`) and `litellm-mcp-server` (19 h, container `mcp-server`), both `python:3.12-slim`, both `1/1` |
| 2 | Pods in `litellm-mcp` | `litellm-mcp-admin-749b47fb6c-zm9zg` and `litellm-mcp-server-5bbb4d67d-zwbbm`, 0 restarts each, same node |
| 3 | Services in `litellm-mcp` | **Two** — `litellm-mcp` → `10.43.212.98:8000`, selector `app=litellm-mcp-server`; `litellm-mcp-admin` → `10.43.111.31:8080`, selector `app=litellm-mcp-admin` |
| 4 | `Deployment/litellm-mcp-server` spec | `RollingUpdate`, one `git-clone` init container, `--host 0.0.0.0 --port 8000`, `emptyDir` only, no PVC, no SPA |
| 5 | `Deployment/litellm-mcp-admin` spec | `Recreate`, three init containers, PVC `litellm-mcp-data`, uvicorn on `0.0.0.0:8080`; `seed-config` writes `mcp_server` pointing at `127.0.0.1:3000` |
| 6 | `/data/config.json` on the admin pod | `mcp_server.args` = `--host 127.0.0.1 --port 3000`; `proxy.timeout` 86400; all four gates empty |
| 7 | `cloudflared` logs in `litellm` | `ingressRule=1 originService=http://litellm-mcp-admin.litellm-mcp.svc.cluster.local:8080` for `litellm-mcp.woowtech.io` |
| 8 | In-cluster probes | `litellm-mcp:8000/mcp/` → 406, `127.0.0.1:3000/mcp/` → 406, `127.0.0.1:8080/healthz` → 200. All three live |
| 9 | `Deployment/litellm-mcp-server` logs | Last inbound request before the deliberate probe: 2026-08-04 17:04 from `127.0.0.1`. No external traffic |

**Verdict.** "Console contains the server" is true of `litellm-mcp-admin` and true of
the entire public path. "Single Deployment" is false: a second, standalone,
unauthenticated MCP server is running alongside it and carrying no traffic.

Four documentation defects fell out of this and are recorded in
[`findings.md`](./findings.md) as FINDING-003 through FINDING-006, with OPEN-5 and
OPEN-6 as the two decisions left to the operator. Corrections pushed to
`docs/deployment.md`, `docs/architecture.md` (new §9 and a narrowed §4 claim),
`findings.md` and this file.

The repository manifests themselves were checked against the live specs and match
exactly — `k8s-deploy.yaml` and `k8s-admin-deploy.yaml` are accurate. The defect was in
the prose, not the YAML.

---

## Settings touched

None. No configuration value on either deployment was changed at any point in this
pass; every interaction with the console was a read or a navigation. Constraint #5
therefore has nothing to restore.
