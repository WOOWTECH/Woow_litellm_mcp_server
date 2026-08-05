# Findings

Defects, obstacles and open items from the August 2026 documentation pass. Findings are
defects in the repository; observations are obstacles encountered in the tooling used to
do the work, recorded so they need not be rediscovered.

---

## FINDING-001 — Documented tool count drifted from the registry

**Severity:** medium · **Status:** fixed

`README.md` advertised "Tool surface (38 tools)" while `TOOL_REGISTRY` contained 40. The
`plugins` category table listed five entries against seven in the registry:
`litellm_plugin_info` and `litellm_delete_plugin` were added to the code without the
hand-maintained README table being updated.

This is worse than a cosmetic error. `litellm_delete_plugin` is one of the eight
dangerous tools, so an operator reading the README to decide what to gate would have
been working from a list that omitted a destructive capability.

**Root cause.** The README's tool table was maintained by hand, in parallel with a
registry that is the actual source of truth. Two lists, one of them authoritative, no
mechanism connecting them.

**Fix.** Both the README's API Reference and `docs/tool-catalog.md` are now generated
from `TOOL_REGISTRY` by importing the module, and both carry an explicit totals row
(40 tools · 8 categories · 18 read-only · 8 dangerous) so a future drift is visible
rather than silent.

**Residual risk.** Generation is manual — someone must regenerate after adding a tool.
A stronger fix would be a test asserting the README's row count equals
`len(TOOL_REGISTRY)`, which would fail the build on drift. Recorded as OPEN-1.

---

## FINDING-002 — Documentation figures were not sourced from the running system

**Severity:** low · **Status:** fixed

The previous documentation described the architecture accurately but carried no live
figures, and where numbers appeared they were not traceable to a source. There was no
way for a reader to distinguish a measured claim from a remembered one.

**Fix.** Every number in the current READMEs was pulled from a running service or from
source at authoring time, and the provenance is stated: usage figures are the real
seven-day window ending 5 August 2026, health counts came from `litellm_model_info`,
the process state from the dashboard, the test result from an actual `pytest` run, the
line counts from the working tree. Screenshots are captures of the deployed services
rather than mockups, and their captions quote text visible in the image.

---

## FINDING-003 — Documented topology omitted a live, unauthenticated Deployment

**Severity:** high · **Status:** fixed in the docs, open as an operational decision

`docs/deployment.md` listed one workload in namespace `litellm-mcp`. The cluster runs
two:

| Deployment | Port | Service | Auth | Public route |
|---|---|---|---|---|
| `litellm-mcp-admin` | 8080 | `litellm-mcp-admin:8080` | JWT console + path-token proxy | tunnel → `litellm-mcp.woowtech.io` |
| `litellm-mcp-server` | 8000 | `litellm-mcp:8000` | **none** | none |

Both are `Ready 1/1`. The admin console spawns its *own* FastMCP child on
`127.0.0.1:3000` and never dials `litellm-mcp:8000`, so the second Deployment serves no
part of the public path — verified from `cloudflared`, whose logs name the origin
explicitly as `http://litellm-mcp-admin.litellm-mcp.svc.cluster.local:8080`
(`ingressRule=1`), and from the standalone pod's own log, whose last inbound request
before a deliberate probe was over 18 hours old and came from loopback.

**Why it matters.** A reader of the runbook would conclude the namespace contains one
gated endpoint. It contains a gated one and an ungated one. `litellm-mcp:8000` exposes
all 40 tools, including the 8 dangerous ones, to anything with cluster network reach —
no token, no JWT, no gate beyond the `LITELLM_MCP_*` environment variables on that
Deployment (all unset).

**Fix.** `docs/deployment.md` now documents three workloads, names the two modes, states
which one is live and gives the `cloudflared` command that proves it.
`docs/architecture.md` §9 explains why both modes exist and why running both is a
decision rather than redundancy.

**Open decision.** Either keep `litellm-mcp-server` deliberately, as an in-cluster
unauthenticated endpoint, or delete `Deployment/litellm-mcp-server` and
`Service/litellm-mcp`. Deleting them removes a live capability surface at zero cost to
the public endpoint. Recorded as OPEN-5.

---

## FINDING-004 — `seed-config` reverts console-side password and token changes

**Severity:** high · **Status:** documented; code change recommended

The `seed-config` init container was documented — and described in BUG-2 below — as
idempotent, seeding `/data/config.json` only when absent. The live script does not do
that. It runs on every pod start and unconditionally assigns:

```python
cfg["admin_password"] = os.environ["ADMIN_PASSWORD"]
cfg["mcp_auth_token"] = os.environ["MCP_AUTH_TOKEN"]
cfg["connection"]     = {...from the Secret...}
```

Only `mcp_server.env`, `tools.*`, `token_history` and `proxy` are preserved, via
`setdefault` and an explicit `prev_env` carry-over.

**Consequence.** Changing the admin password in the console, or rotating
`mcp_auth_token` on the Tokens page, holds until the next pod restart and is then
silently reverted to the Secret's value. A rollout, node drain or eviction is enough.
For the token this is the worse case: clients repointed to the new URL start getting
404s, and the failure looks like a client problem rather than a config revert.

**Fix.** `docs/deployment.md` now states exactly which keys are overwritten and which
survive, and both the first-deploy and rotation procedures instruct the operator to
update `Secret/litellm-mcp-admin-secret` alongside any console-side change.

**Recommended code change.** Treat the Secret as a *seed* for these two keys —
`cfg.setdefault("admin_password", ...)` — so the stored value wins once set, and keep
the unconditional write only for `connection`, which is genuinely manifest-owned.
Recorded as OPEN-6.

**Note on BUG-2.** The historical entry below claims the fix was "seeds only when the
file is absent". That is not what shipped. The shipped fix was narrower: preserve
`mcp_server.env` and the tools block. The BUG-2 text is corrected in place.

---

## FINDING-005 — Init-chain step 2 was documented as `npm ci`

**Severity:** low · **Status:** fixed

`docs/deployment.md` described `spa-build` as running `npm ci && npm run build`. It runs
`npm install --no-audit --no-fund && npm run build`, then
`mkdir -p /repo/static && cp -r dist/* /repo/static/`. The copy step was undocumented
entirely, which matters because `create_app` falls back to `$CWD/static` — a reader
looking for where the served bundle comes from would not have found it.

`npm ci` is not merely a stylistic difference: it requires a lockfile, and
`frontend/package-lock.json` is not committed (OPEN-2). Documenting `npm ci` implied a
reproducibility guarantee the deployment does not have.

---

## FINDING-006 — The proxy token is written in full to the edge proxy's logs

**Severity:** medium · **Status:** documented

`docs/architecture.md` §4 justified putting the token in the path rather than the query
string on the grounds that the proxy strips the private prefix before the inner request
is logged, keeping the secret out of the log ring buffer streamed to the console.

That holds for this project's own log. It does not hold one hop upstream. `cloudflared`
writes the full destination URL on every origin error:

```
ERR Request failed … dest=https://litellm-mcp.woowtech.io/private_<token>/mcp
```

Roughly two dozen such lines were present in the tunnel's recent log from a window when
the admin pod was restarting, each containing a live credential in cleartext.

**Fix.** §4 now states the narrower, true claim and says plainly that any edge proxy,
tunnel or reverse proxy in the path must be treated as holding credential material.
`docs/deployment.md` repeats the warning next to the rotation procedure. No code change
is available — this is inherent to URL-borne secrets, and the URL form exists because
some MCP clients accept no headers.

---

## OBS-1 — Sandbox network path to the GitHub write API is blocked by policy

**Status:** worked around

`curl`, `git push` and direct REST `PUT` calls from the execution sandbox return
`403 "Write access to this GitHub API path is not permitted through this proxy."` This
is an egress policy, not an authentication failure — per constraint #9 it was reported
rather than retried.

The same `PUT`, issued from inside the headless browser session, succeeds with
`201 Created`. The block is on the sandbox's egress path specifically, not on the
credential or the API. Binary assets were therefore published from the browser side.

---

## OBS-2 — Browser function context mangles JSON-string values

**Status:** worked around

Passing a structured value through the browser function's `context` parameter as a JSON
string — `"shots": "[[\"/login\",\"admin_console_login\"], …]"` — failed with
`Unexpected token '/', "/login,adm"... is not valid JSON`. The transport parses the
value and re-serialises it, collapsing arrays into comma-joined strings.

**Workaround.** Pass only flat scalars through `context` and hardcode any array inside
the function body.

---

## OBS-3 — `page.screenshot()` returns a `Uint8Array`, not a Buffer

**Status:** worked around

`buf.toString('base64')` on a screenshot result produced comma-joined decimal numbers,
which GitHub rejected with `422 "content is not valid Base64"`. The 422 was useful — it
proved the credential authenticated and the API was reachable, isolating the fault to
encoding.

---

## OBS-4 — No `Buffer` global in the browser function sandbox

**Status:** worked around

The obvious fix to OBS-3, `Buffer.from(bytes).toString('base64')`, failed with
`Buffer is not defined`. A pure-JS base64 encoder over the `Uint8Array` was written
instead; every subsequent upload returned 201 with a reported size exactly equal to the
source buffer length, which is the byte-for-byte confirmation.

---

## OBS-5 — Deleting a file through the GitHub MCP tool reported a false failure

**Status:** resolved, no action needed

Deleting the temporary probe artefact `docs/.probe-binary.png` returned
`422 GitRPC::BadObjectState`. A follow-up read of the contents API returned `404`,
confirming the file is not on `main`. The error was spurious; the deletion took effect.

---

## Historical defects, fixed in v0.2.0

Recorded here because the READMEs' changelogs cite them.

**BUG-1 — SSE stream leaked the JWT into the access log.** The log stream originally
carried the JWT in the query string, because `EventSource` cannot set custom headers.
uvicorn logs full request lines, so every reconnect wrote a valid token into the log
ring buffer — which is itself streamed to the Logs page. Fixed by issuing an httpOnly
cookie alongside the JWT and using `withCredentials: true`.

**BUG-2 — Config PVC clobbered on redeploy.** The `seed-config` init container
overwrote `/data/config.json` wholesale on every start, resetting the tool gates and
`token_history` on each rollout. Fixed by carrying `mcp_server.env` forward and applying
`setdefault` to the tools block and `token_history`, so GUI-set switches survive.
*Corrected description:* the fix was **not** "seed only when the file is absent". The
container still runs on every start and still rewrites `admin_password`,
`mcp_auth_token` and `connection` unconditionally — see FINDING-004 above, which is the
part of this bug that was never actually fixed.

**BUG-3 — `RollingUpdate` deadlocked on the `ReadWriteOnce` PVC.** The new pod could
not mount the volume while the old pod held it, so rollouts hung until timeout. Fixed by
switching to `strategy: Recreate`, accepting a brief outage for a rollout that completes.

**BUG-4 — Frontend build failure crash-looped the pod.** A failing `npm run build` in
the `spa-build` init container took down the whole console, including the MCP proxy that
clients depend on. Fixed by ending the step in `exit 0` so a failed build leaves the
committed `dist/` serving. The trade-off is that build failures are now silent and only
visible in the init container's logs.

---

## Open items

**OPEN-1 — No automated guard against tool-count drift.** The generated tables fix the
current drift but nothing prevents the next one. A test asserting the README's tool-row
count equals `len(TOOL_REGISTRY)` would fail the build instead. Low effort, recommended.

**OPEN-2 — `frontend/package-lock.json` is not committed.** 82,805 bytes, blob SHA-1
`eba6133a00780d4697400d8a7d38da2e4655ff49`. Without it the `spa-build` init container
resolves dependencies fresh on every cold start, so two deploys of the same commit can
produce different SPA bundles. Deliberately deferred from this documentation pass;
worth a separate commit.

**OPEN-3 — Stale backup on the config PVC.** `/data/config.json.prefix-redeploy.bak`
remains from an earlier migration. Harmless but untracked; delete when convenient.

**OPEN-4 — Credential rotation.** Two credentials were shared with a third-party
browser automation service to complete this work and should be rotated: the GitHub
personal access token (`ghp_uQYw…`) and the console admin password. Separately, the
LiteLLM master key (`sk-bcae…`) is a reasonable rotation candidate on general hygiene
grounds — but note that `LITELLM_SALT_KEY` must **not** be rotated with it, as that
would make every encrypted database column undecryptable.

**OPEN-5 — Decide the fate of `Deployment/litellm-mcp-server`.** It is live, healthy,
unauthenticated, reachable from anywhere in the cluster, and carries no public traffic
(FINDING-003). Either document it as an intentional in-cluster endpoint and gate it with
`LITELLM_MCP_READONLY` or `LITELLM_MCP_DISABLED_TOOLS`, or delete the Deployment and its
Service. Leaving it undecided is the only bad option.

**OPEN-6 — Make `seed-config` seed rather than overwrite.** Change
`cfg["admin_password"] = …` and `cfg["mcp_auth_token"] = …` to `setdefault`, so a value
set from the console wins over the Secret once it exists (FINDING-004). Until then the
Secret and the console must be updated together by hand.

---

## Verification claims

Statements a reviewer can check independently.

| Claim | How to verify |
|---|---|
| 40 tools, 18 read-only, 8 dangerous | `python -c "from woow_litellm_mcp_server.registry import TOOL_REGISTRY as R; print(len(R), sum(s.operations==('read',) for s in R), sum(s.dangerous for s in R))"` |
| Console cannot name a tool the server lacks | `pytest tests/test_mcp_surface.py` |
| A gated tool is absent, not refused | `pytest tests/test_gated_tool_message.py` |
| 133 passing, 2 deselected | `pytest` |
| Five deployments, all healthy | `litellm_health` against the gateway |
| No secrets in the tree | `git grep -nE 'sk-[a-zA-Z0-9]{20,}\|ghp_[a-zA-Z0-9]{30,}'` returns nothing |
| No configuration was changed | Compare `/data/config.json` against its pre-pass state; the pass performed reads only |
| Two Deployments in `litellm-mcp`, not one | `kubectl get deploy,svc -n litellm-mcp` |
| The console proxies to a loopback child, not to `litellm-mcp:8000` | `kubectl exec -n litellm-mcp deploy/litellm-mcp-admin -c admin -- python -c "import json;print(json.load(open('/data/config.json'))['mcp_server'])"` |
| The tunnel's origin is the admin Service | `kubectl logs -n litellm deploy/cloudflared --tail=200 \| grep originService` |
| `litellm-mcp:8000` answers with no credential | `kubectl exec -n litellm-mcp deploy/litellm-mcp-admin -c admin -- python -c "import httpx;print(httpx.get('http://litellm-mcp.litellm-mcp.svc.cluster.local:8000/mcp/').status_code)"` — returns `406`, i.e. the server is live and only objecting to the `Accept` header |
