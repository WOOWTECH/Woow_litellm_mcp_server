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

**Severity:** high · **Status:** RESOLVED — manifest deleted, cluster cleaned

*(Written while the defect was live; the state described below has since been cleaned up
— see "Fix — cluster".)*

`docs/deployment.md` listed one workload in namespace `litellm-mcp`. The cluster ran
two:

| Deployment | Port | Service | Auth | Public route |
|---|---|---|---|---|
| `litellm-mcp-admin` | 8080 | `litellm-mcp-admin:8080` | JWT console + path-token proxy | tunnel → `litellm-mcp.woowtech.io` |
| `litellm-mcp-server` | 8000 | `litellm-mcp:8000` | **none** | none |

Both were `Ready 1/1`. The admin console spawns its *own* FastMCP child on
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

**Root cause.** Not an oversight in the prose — a defect in the file layout. The header
of `k8s-deploy.yaml` announced "This file documents TWO deployment paths. Pick ONE
Deployment", but its standalone path was the one left uncommented, *and* the same file
carried the shared `Namespace` and `Secret/litellm-mcp-secret` that the console needs.
`k8s-admin-deploy.yaml`'s own header then instructed the reader to
`kubectl apply -f k8s-deploy.yaml   # namespace + litellm-mcp-secret` first. Following
the documented order therefore *always* produced the unauthenticated `:8000` endpoint.
Nobody chose it; the layout chose it for them.

**Fix — repository.** `k8s-deploy.yaml` is deleted. The namespace and gateway secret now
live alone in a new `k8s-base.yaml`, which contains **no workload at all**; that
separation is the point of the file and its header says so. `k8s-admin-deploy.yaml` is
now labelled "THIS IS THE ONLY DEPLOYMENT PATH" and carries an explicit "do not
reintroduce it" note. `k8s-secret.example.yaml` was folded into `k8s-base.yaml` and
deleted, since it duplicated the same Namespace + Secret pair and was a third source of
truth for the same two objects. `docs/deployment.md`, `docs/architecture.md` §9,
`README.md` and `README_zh-TW.md` were rewritten to describe one path, and each carries
an upgrade note with the cleanup commands.

**Fix — cluster.** `Deployment/litellm-mcp-server` and `Service/litellm-mcp` were deleted
from namespace `litellm-mcp` on 5 August 2026, with the user's explicit approval.
`Namespace/litellm-mcp` and `Secret/litellm-mcp-secret` were kept — the console's
`seed-config` init container reads the latter. Post-delete state: one Deployment
(`litellm-mcp-admin`, `1/1`), one Service (`litellm-mcp-admin:8080`), one pod
(`litellm-mcp-admin-749b47fb6c-zm9zg`, `Running`, **0 restarts** — i.e. the console was
not disturbed), both Secrets present. OPEN-5 is closed by this.

---

## FINDING-004 — `seed-config` reverts console-side password and token changes

**Severity:** high · **Status:** FIXED — in the manifest and, since 5 August 2026, on the
live Deployment object as well

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

**Evidence it was a regression, not a design choice.** The commented-out PATH A template
at the tail of the old `k8s-deploy.yaml` used `if not p.exists():` around its own
seed-config — the same repository, the same init container, the opposite behaviour. The
unconditional assignment in the live manifest was drift, not intent. That removed the
remaining ambiguity from OPEN-6.

**Fix.** `k8s-admin-deploy.yaml` now uses:

```python
cfg.setdefault("admin_password", os.environ["ADMIN_PASSWORD"])
cfg.setdefault("mcp_auth_token", os.environ["MCP_AUTH_TOKEN"])
cfg["connection"] = {...from the Secret...}    # still unconditional, on purpose
```

The split is principled rather than cosmetic: `admin_password` and `mcp_auth_token` are
the console's *own* credentials and the console mutates them at runtime, so the Secret
seeds first boot and `/data` is the truth afterwards. `connection` is infrastructure, not
user state, so rotating the LiteLLM master key in the Secret must still reach the console
on the next restart. The comment block in the manifest states this so the next person
does not "simplify" the two forms back into one. `docs/deployment.md` documents the
three-way split and both procedures were rewritten accordingly. OPEN-6 is closed.

**Landing it on the cluster (5 August 2026).** Editing the manifest does not change the
running object, so the fix was only half done until the Deployment was re-applied. That
was carried out deliberately, not blind, because two hazards sit in the way.

The first is the manifest itself. `k8s-admin-deploy.yaml` ships four documents and the
first is `Secret/litellm-mcp-admin-secret` carrying **placeholder** credentials. A plain
`kubectl apply -f k8s-admin-deploy.yaml` would therefore overwrite the live admin
password, JWT secret and proxy token with placeholder strings and lock everyone out of
the console at the same moment the pod restarts. **Only the `Deployment` document may be
applied to this cluster.** It was extracted into a standalone file, diffed against the
running object, and applied on its own.

The second is the interaction between the fix and the Secret. With `setdefault` in place
the pod now prefers `/data`, so a Secret that had drifted from the PVC would have been
ignored — but with the *old* script still running at the moment of the apply, the pod
would first have been rebuilt from the Secret. If the two had disagreed, the restart
would have flipped the live `mcp_auth_token` and killed the connected client. They were
proved equal beforehand by comparing sha256 digests only — an ephemeral pod mounted both
Secrets and printed 12-character digests and lengths, never values — and all four
matched, so the restart could not change anything.

Sequence actually performed: back up `/data/config.json` to
`/data/config.json.pre-open7-20260805.bak`; confirm Secret and PVC agree by digest; diff
the live Deployment against the manifest (verdict: the two `setdefault` lines and the
comment block, nothing else); apply the single Deployment document with field manager
`kubernetes-mcp-server`, the same manager that created the object, so server-side apply
raised no ownership conflict.

**Outcome.** Pod `…-749b47fb6c-zm9zg` terminated, `…-59758cc76c-6hqbj` came up `1/1`
with **0 restarts** in roughly four minutes — consistent with the 2.5–3 minute cold-start
estimate plus scheduling. `/data/config.json` came out byte-identical to the backup
(sha256 prefix `266e6eab84873668`, 1044 bytes, mode `0600`): password, token, master key,
the four `LITELLM_MCP_*` gating switches and `token_history` all preserved. The full
public chain — Cloudflare → console → loopback child → LiteLLM — was re-verified with
`litellm_health_readiness`, which returned `healthy` against gateway 1.83.14.

**Regression test.** The claim that matters is behavioural, not textual, so the *deployed*
seed script was extracted from the running object and executed against synthetic configs
in a sandbox. It asserts: first boot seeds both credentials from the Secret; a restart
after a GUI-side password change and a GUI-side token rotation leaves both GUI values
intact; `connection` is still refreshed from the Secret on every restart; the child's
gating env, `token_history` and the legacy `tools.disabled` → `disabled_tools` migration
all behave. All assertions passed. The manual workaround — updating
`Secret/litellm-mcp-admin-secret` by hand alongside every console-side change — is no
longer required.

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
part of this bug that went unfixed until August 2026. `admin_password` and
`mcp_auth_token` are now `setdefault`; `connection` remains unconditional by design.

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

**OPEN-3 — Stale backups on the config PVC.** Two now:
`/data/config.json.prefix-redeploy.bak` from an earlier migration, and
`/data/config.json.pre-open7-20260805.bak` taken immediately before the OPEN-7 re-apply.
The second is worth keeping until the fixed seed script has survived a few unattended
restarts; both are harmless but untracked, and each is a full copy of the config
including credentials, so they inherit its `0600` sensitivity. Delete when convenient.

**OPEN-4 — Credential rotation.** Two credentials were shared with a third-party
browser automation service to complete this work and should be rotated: the GitHub
personal access token (`ghp_uQYw…`) and the console admin password. Separately, the
LiteLLM master key (`sk-bcae…`) is a reasonable rotation candidate on general hygiene
grounds — but note that `LITELLM_SALT_KEY` must **not** be rotated with it, as that
would make every encrypted database column undecryptable.

**OPEN-5 — ~~Decide the fate of `Deployment/litellm-mcp-server`.~~ CLOSED.** Decided:
deleted. `k8s-deploy.yaml` was removed from the repository and the live Deployment and
`Service/litellm-mcp` were deleted from the cluster. See FINDING-003.

**OPEN-6 — ~~Make `seed-config` seed rather than overwrite.~~ CLOSED.**
`admin_password` and `mcp_auth_token` now use `setdefault`; `connection` stays an
assignment on purpose. See FINDING-004. The follow-up that kept this open — the running
Deployment still embedding the old script — was closed by OPEN-7 below.

**OPEN-7 — ~~Re-apply `k8s-admin-deploy.yaml` to land the FINDING-004 fix.~~ CLOSED.**
Done 5 August 2026. Only the `Deployment` document was applied, never the whole file:
the `Secret` document in that manifest holds placeholders and applying it would have
overwritten the live credentials. The Secret and the PVC were proved to agree by sha256
digest first, so the `Recreate` restart could not flip the live `mcp_auth_token`, and
`/data/config.json` was backed up before the apply. New pod reached `1/1` with 0 restarts
in about four minutes; the config came out byte-identical and the deployed seed script
passed a behavioural regression test. Full write-up under FINDING-004.

**A general rule this left behind.** `k8s-admin-deploy.yaml` is a bootstrap manifest, not
a reconciliation target. Its first document seeds credentials with placeholders, so
`kubectl apply -f k8s-admin-deploy.yaml` against a *live* cluster is destructive: it
resets the admin password, JWT secret and proxy token to placeholder strings. Apply the
whole file only on first install; afterwards apply the `Deployment` document alone.

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
| Exactly one Deployment and one Service in `litellm-mcp` | `kubectl get deploy,svc -n litellm-mcp` — expect `litellm-mcp-admin` only. Anything named `litellm-mcp-server` or `Service/litellm-mcp` is a pre-cleanup leftover (FINDING-003) |
| The namespace and gateway Secret survived the cleanup | `kubectl get ns litellm-mcp` and `kubectl get secret -n litellm-mcp` — expect `litellm-mcp-secret` and `litellm-mcp-admin-secret` |
| The console proxies to a loopback child | `kubectl exec -n litellm-mcp deploy/litellm-mcp-admin -c admin -- python -c "import json;print(json.load(open('/data/config.json'))['mcp_server'])"` — `--host 127.0.0.1 --port 3000` |
| The tunnel's origin is the admin Service | `kubectl logs -n litellm deploy/cloudflared --tail=200 \| grep originService` — grep `originService`, **not** `dest=`; the latter prints the live token (FINDING-006) |
| The repository ships exactly two manifests | `ls k8s-*.yaml` → `k8s-base.yaml`, `k8s-admin-deploy.yaml` |
| `k8s-base.yaml` contains no workload | `python -c "import yaml,sys;print([(d['kind'],d['metadata']['name']) for d in yaml.safe_load_all(open('k8s-base.yaml')) if d])"` → `Namespace`, `Secret` only |
| The live Deployment carries the FINDING-004 fix | `kubectl get deploy litellm-mcp-admin -n litellm-mcp -o jsonpath='{.spec.template.spec.initContainers[2].command[2]}' \| grep setdefault` — expect `setdefault` on both `admin_password` and `mcp_auth_token` |
| The fix does not clobber GUI-side changes | Extract that same script and run it over a synthetic `/data/config.json` whose password and token differ from the env vars; both must survive, `connection` must not |
