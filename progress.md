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
exactly. The prose was wrong about which workloads existed — but Phase 6 found that the
*layout* of the YAML was what produced the second workload in the first place.

---

## Phase 6 — Consolidation onto the admin path · complete

Requested directly: keep the console deployment and everything it provides (React SPA,
JWT login, the encrypted proxy at `/private_{token}/mcp/`, the PVC, Permissions-page
gating with a child restart instead of a pod rollout, the SSE log stream) and remove the
older standalone MCP-server deployment completely — from the repository and from the
cluster.

**Root cause found first.** Phase 5 called FINDING-003 a prose defect. It was not. The
header of `k8s-deploy.yaml` claimed to document two mutually exclusive paths, but the
standalone Deployment inside it was the uncommented one, and the same file also carried
the `Namespace` and `Secret/litellm-mcp-secret` that the console depends on —
`k8s-admin-deploy.yaml` told the reader to apply it first for exactly that reason. The
documented install order could not produce a console-only cluster. Separately, the
commented-out template at the tail of that same file used `if not p.exists():` in its
seed-config, which proved FINDING-004's unconditional overwrite was drift rather than
design and closed the open question in OPEN-6.

### Repository

| Change | Detail |
|---|---|
| `k8s-base.yaml` | **New.** `Namespace/litellm-mcp` + `Secret/litellm-mcp-secret`, and **no workload** — that separation is the fix. Header warns that applying it over a live cluster overwrites the real master key with the placeholder, and gives the `kubectl create secret` form for a first install |
| `k8s-admin-deploy.yaml` | Header rewritten to "THIS IS THE ONLY DEPLOYMENT PATH", explains the FastMCP server is a child process rather than a workload, records that the second manifest was removed and says not to reintroduce it. Apply order is now `k8s-base.yaml` → this file |
| `k8s-admin-deploy.yaml` seed-config | `admin_password` and `mcp_auth_token` switched to `setdefault`; `connection` deliberately left as an assignment, with a comment explaining why the two forms differ. Closes OPEN-6 |
| `k8s-deploy.yaml` | **Deleted** |
| `k8s-secret.example.yaml` | **Deleted** — it duplicated the Namespace + Secret pair now in `k8s-base.yaml` and was a third source of truth for the same two objects. This went one step beyond the explicit request and is called out here for that reason |
| `docs/deployment.md` | Topology table down to two workloads; "the server is a child process, not a workload"; new "Removed: the standalone Deployment" section with cleanup commands; first-deploy and health-check blocks rewritten; the `seed-config` behaviour table now has a three-way split plus an upgrade warning; rotation step 3 relaxed with a note for pre-fix clusters |
| `docs/architecture.md` | §9 retitled "One deployment path, and why the second one was removed" and rewritten around the layout defect |
| `README.md` / `README_zh-TW.md` | Installation reduced from four options to three; the bare server is now labelled development-only and bound to `127.0.0.1`; package tables updated; upgrade-cleanup callout added to both |
| `CONTRIBUTING.md` | "Running the server" retitled development-only, `--host` changed to `127.0.0.1`, with a note that the deployed topology never runs it this way |
| `cloudflare/README.md` | Stale "36 LiteLLM tools" corrected to 40 |

### Cluster

Deleted with explicit approval, in namespace `litellm-mcp`:

- `Deployment/litellm-mcp-server`
- `Service/litellm-mcp`

Kept, because `seed-config` reads it: `Namespace/litellm-mcp` and
`Secret/litellm-mcp-secret`. The `litellm` namespace, the `litellm` Service and the
Cloudflare tunnel were not touched.

Post-delete verification: one Deployment (`litellm-mcp-admin`, `1/1`), one Service
(`litellm-mcp-admin:8080`), one pod (`litellm-mcp-admin-749b47fb6c-zm9zg`, `Running`,
**0 restarts** — the console was not disturbed by the deletion), both Secrets present.

---

## Phase 7 — Landing the FINDING-004 fix on the cluster · complete

Phase 6 left the `setdefault` fix in the manifest only; the running Deployment object
still embedded the old script that reverted console-side password and token changes on
every restart. That was recorded as OPEN-7 and deliberately not performed unprompted,
because `strategy: Recreate` takes the console and the public MCP endpoint down for a
2.5–3 minute cold start. The user authorised the downtime, and it was carried out on
5 August 2026.

Two hazards shaped the procedure. First, `k8s-admin-deploy.yaml` opens with
`Secret/litellm-mcp-admin-secret` holding **placeholder** credentials, so applying the
whole file would have reset the live admin password, JWT secret and proxy token to
placeholders at the same moment the pod restarted. Only the `Deployment` document was
applied — extracted to a standalone file and verified byte-identical to the repository
text before sending. Second, the *old* script was still the one running at apply time, so
the restart would rebuild the config from the Secret; had the Secret drifted from the PVC,
the live `mcp_auth_token` would have flipped and killed the connected client. The two were
proved equal beforehand using sha256 digests only — an ephemeral pod mounted both Secrets
and printed 12-character digests and lengths, never values, and was then deleted. All four
digests matched.

| Step | Result |
|---|---|
| Back up `/data/config.json` | `/data/config.json.pre-open7-20260805.bak` (added to OPEN-3) |
| Secret ⟷ PVC digest comparison | all four match — restart cannot change credentials |
| Diff live Deployment vs manifest | only the two `setdefault` lines and the comment block differ |
| Apply the single `Deployment` document | field manager `kubernetes-mcp-server`, no SSA conflict; generation 3 |
| Rollout | `…-749b47fb6c-zm9zg` → `…-59758cc76c-6hqbj`, `1/1`, **0 restarts**, ~4 minutes |
| Config after restart | byte-identical: sha256 prefix `266e6eab84873668`, 1044 bytes, mode `0600` |
| Public chain | `litellm_health_readiness` via Cloudflare → console → loopback child → LiteLLM returns `healthy` |
| Behavioural regression test | deployed script re-run over synthetic configs — all assertions pass |

The regression test is the part worth trusting: rather than reading the applied YAML back
and calling it done, the seed script was extracted *from the running object* and executed
against synthetic configs. It confirms that first boot seeds both credentials from the
Secret, that a restart after a GUI-side password change and token rotation leaves both GUI
values intact, that `connection` is still refreshed from the Secret every time, and that
the child's gating env, `token_history` and the legacy `tools.disabled` migration all
survive. OPEN-6 and OPEN-7 are both closed; FINDING-004 is fully fixed.

One rule came out of this and is now recorded in `findings.md`: `k8s-admin-deploy.yaml` is
a bootstrap manifest, not a reconciliation target. Apply the whole file only on first
install; against a live cluster, apply the `Deployment` document alone.

---

## Settings touched

No configuration value on the admin console was changed at any point across Phases 1–7;
every interaction with the console was a read or a navigation, so Constraint #5 has
nothing to restore there. Phase 7 restarted the pod but did not alter its configuration:
`/data/config.json` is byte-identical before and after, verified by sha256.

Two cluster objects were **deleted** in Phase 6 — `Deployment/litellm-mcp-server` and
`Service/litellm-mcp` — at the user's explicit instruction. These are intentionally not
restored; removing them was the point of the request. Everything needed to recreate them
is in the git history of the deleted `k8s-deploy.yaml`.
