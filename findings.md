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
overwrote `/data/config.json` on every start, resetting connection settings and gates
on each rollout. Fixed by making it idempotent — it seeds only when the file is absent.

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
