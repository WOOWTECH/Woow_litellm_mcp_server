# Deployment runbook

Operational notes for running `Woow_litellm_mcp_server` on k3s, written against the
live deployment at `https://litellm-mcp.woowtech.io`.

The objects are packaged as the Helm chart
[`../charts/litellm-mcp`](../charts/litellm-mcp); the values the live release runs with
are [`../deploy/woow-k3s/litellm-mcp.yaml`](../deploy/woow-k3s/litellm-mcp.yaml). The
hand-written `k8s-base.yaml` / `k8s-admin-deploy.yaml` have been removed — every
`kubectl apply` recipe below is superseded by `helm upgrade --install`, and the reason
each rule existed is noted where it still applies to the chart.

On woow-k3s these objects are, at the time of writing, still owned by the `litellm`
release of [`Woow_k3s_litellm`](https://github.com/WOOWTECH/Woow_k3s_litellm)
(`templates/mcp.yaml`); [Taking over an existing install](#taking-over-an-existing-install)
is the move to this chart.

---

## Topology

Two workloads, in two namespaces. There is exactly **one** way to run the MCP server.

| Namespace | Deployment | Image | Service | Public |
|---|---|---|---|---|
| `litellm` | `litellm` | `ghcr.io/berriai/litellm:v1.83.14-stable` | `litellm:4000` | tunnel → `litellm.woowtech.io` |
| `litellm-mcp` | `litellm-mcp-admin` | `python:3.12-slim` + 3 init containers | `litellm-mcp-admin:8080` | tunnel → `litellm-mcp.woowtech.io` |

The MCP suite reaches the gateway at `litellm.litellm.svc.cluster.local:4000`. That
traffic is cluster-internal; the public tunnels exist for human access, not for
service-to-service calls.

### The server is a child process, not a workload

The chart's `Deployment` runs the admin console on `0.0.0.0:8080`, and the console
*spawns its own FastMCP child* as a subprocess bound to `127.0.0.1:3000`. There is no
second pod, no second Service and nothing to scale independently. The child's command
line is written into `/data/config.json` by the `seed-config` init container:

```json
"mcp_server": {
  "command": "python",
  "args": ["-m", "woow_litellm_mcp_server.server",
           "--transport", "http", "--host", "127.0.0.1",
           "--port", "3000", "--path", "/mcp/"],
  "port": 3000
}
```

The console's encrypted proxy at `/private_{mcp_auth_token}/mcp/` is the only path to
that child. Because the child binds loopback, that is true by construction rather than
by policy: there is no Service, no ClusterIP and no NetworkPolicy that could expose it,
because nothing outside the pod's own network namespace can reach `127.0.0.1:3000` at
all.

**Verifying what actually serves the public hostname.** The Cloudflare tunnel in
namespace `litellm` is a remotely-managed (token) tunnel, so its ingress rules live in
the Cloudflare dashboard rather than in a ConfigMap. `cloudflared`'s own logs name the
origin explicitly:

```
ingressRule=1 originService=http://litellm-mcp-admin.litellm-mcp.svc.cluster.local:8080
```

Public MCP traffic therefore terminates on `litellm-mcp-admin:8080` and is proxied to
loopback `:3000`. (Do not grep tunnel logs for `dest=` and paste the result into a
ticket — that field contains the full private URL, token included. See
[the token is visible at the edge](#the-token-is-visible-at-the-edge).)

```
                            ┌───────────────────────────────────────────┐
  Internet ──► Cloudflare ──►│ Service litellm-mcp-admin :8080           │
                            │   admin console (SPA + /api/*, JWT)       │
                            │   /private_{token}/mcp/  ── proxy ──┐      │
                            │                                     ▼      │
                            │        FastMCP child 127.0.0.1:3000        │──► litellm:4000
                            └───────────────────────────────────────────┘
                                                                            cluster DNS
```

### Removed: the standalone Deployment

Earlier revisions of this repository shipped a second manifest, `k8s-deploy.yaml`, that
ran the same FastMCP server bare on `0.0.0.0:8000` behind `Service/litellm-mcp`, with no
authentication of any kind in front of it. It has been deleted.

The reason it had to go is not that a second workload is wasteful — it is that the file
also carried the shared `Namespace` and `Secret/litellm-mcp-secret` that the console
depends on, and the bare Deployment inside it was active by default. Anyone following
the documented apply order got the unauthenticated endpoint whether they wanted it or
not. That is FINDING-003 in [`findings.md`](../findings.md). In the chart the equivalent
guarantee is structural: `secrets.create` is `false` by default, so a normal install
renders no `Secret` at all, and there is no second workload template to enable.

If you are upgrading a cluster that still runs it:

```bash
kubectl delete deployment litellm-mcp-server -n litellm-mcp
kubectl delete service    litellm-mcp        -n litellm-mcp
# Keep the namespace and Secret/litellm-mcp-secret — the console needs both.
```

Nothing is lost. The console never dialled `litellm-mcp:8000`; it spawns its own child.

---

## The init chain

`litellm-mcp-admin` runs three init containers in order before the main container
starts.

| # | Name | Image | Does |
|---|---|---|---|
| 1 | `git-clone` | `alpine/git` | `rm -rf /repo/*` then `git clone --depth 1` this public repo into the `/repo` emptyDir. |
| 2 | `spa-build` | `node:20-alpine` | `npm install --no-audit --no-fund && npm run build` in `frontend/`, then `cp -r dist/* /repo/static/`. **Ends in `exit 0`.** |
| 3 | `seed-config` | `python:3.12-slim` | Rewrites the keys it owns in `/data/config.json` on the PVC, `chmod 600`. **Runs on every start — see below.** |

`spa-build` uses `npm install`, not `npm ci`, because `frontend/package-lock.json` is
not committed (OPEN-2 in [`findings.md`](../findings.md)). Two cold starts of the same
commit can therefore resolve different dependency versions.

### What `seed-config` actually does

It is **not** "seed only if absent", and it is not "overwrite everything" either. It runs
on every pod start and splits the config into three groups:

| Behaviour | Keys |
|---|---|
| **Seeded from the Secret on FIRST boot only** (`setdefault`) | `admin_password`, `mcp_auth_token` |
| **Overwritten from the Secret, every start** | `connection.litellm_mcp_base_url`, `connection.litellm_mcp_master_key` |
| **Overwritten from the manifest, every start** | `mcp_server.command`, `mcp_server.args`, `mcp_server.port` |
| **Preserved across restarts** | `mcp_server.env` (the `LITELLM_MCP_*` gating switches), `tools.*`, `token_history`, `proxy` |

The split is deliberate. `admin_password` and `mcp_auth_token` are the console's *own*
credentials and the console can change them at runtime — the Settings page changes the
password, the Tokens page rotates the token — so the Secret seeds them on first boot and
`/data/config.json` is the source of truth from then on. The upstream `connection` block
is the opposite: it is infrastructure, not user state, so rotating the LiteLLM master key
in the Secret must reach the console on the next restart.

> **Upgrading from an older revision?** This used to be an unconditional assignment for
> all four keys, which meant a password change or token rotation made in the console
> silently reverted on the next pod restart — a rotated token kept working until an
> eviction and then died with nothing to blame. That is FINDING-004 in
> [`findings.md`](../findings.md). A cluster running the old manifest keeps the old
> behaviour until the `Deployment` object is replaced; see
> [Upgrading a running install](#upgrading-a-running-install) below — step 2 of that
> checklist exists for exactly this case.

The one legacy migration it performs is folding a pre-existing `tools.disabled` list
into `tools.disabled_tools` and dropping the old key, so a reader never sees both.

The main `admin` container then `pip install`s from `/repo` and launches
`uvicorn litellm_mcp_admin.main:app --host 0.0.0.0 --port 8080`.

**Cold start is 2.5–3 minutes.** Most of it is the pip install and the npm build. Do not
interpret a pod sitting in `Init:2/3` for two minutes as a failure.

**`/repo` is an emptyDir**, repopulated on every restart. This means a pod restart
always picks up the current `main` branch — deployment is `git push` followed by
`kubectl rollout restart deployment/litellm-mcp-admin -n litellm-mcp`. It also means
there is no way to pin a commit without pointing `admin.gitRepo` at a fork or a tarball.

**`strategy: Recreate`** is required, not stylistic. See
[`architecture.md` §6](./architecture.md#6-why-recreate-and-why-exit-0).

---

## First deploy

Two steps: create the Secrets once, outside Helm, then install the chart. This section is
for an **empty cluster**; for a cluster that already runs the console see
[Taking over an existing install](#taking-over-an-existing-install).

```bash
# 1. Namespace + the two Secrets. Create them from the command line rather than
#    editing a file, so no key ever touches the working tree.
kubectl create namespace litellm-mcp --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic litellm-mcp-secret -n litellm-mcp \
  --from-literal=LITELLM_BASE_URL='http://litellm.litellm.svc.cluster.local:4000' \
  --from-literal=LITELLM_MASTER_KEY='sk-…' \
  --from-literal=JWT_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')" \
  --dry-run=client -o yaml | kubectl apply -f -

#      ADMIN_PASSWORD   console login
#      MCP_AUTH_TOKEN   the ONLY credential on /private_{token}/mcp/ — generate it
#      JWT_SECRET       signs console sessions
kubectl create secret generic litellm-mcp-admin-secret -n litellm-mcp \
  --from-literal=ADMIN_PASSWORD='…' \
  --from-literal=MCP_AUTH_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')" \
  --from-literal=JWT_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')" \
  --dry-run=client -o yaml | kubectl apply -f -

# 2. The console: PVC + Deployment + Service (+ the Namespace object itself).
helm upgrade --install litellm-mcp charts/litellm-mcp \
  -n litellm --create-namespace \
  -f deploy/woow-k3s/litellm-mcp.yaml

# 3. Watch the init chain, then run the read-only smoke test.
kubectl get pods -n litellm-mcp -w
kubectl -n litellm-mcp rollout status deploy/litellm-mcp-admin --timeout=10m
helm test litellm-mcp -n litellm
# The smoke pod runs in litellm-mcp, the release in litellm, so `--logs` looks in
# the wrong namespace - read them directly:
kubectl -n litellm-mcp logs litellm-mcp-smoke
```

The release lives in namespace `litellm` on purpose: a `Namespace` equal to the release
namespace is never rendered, so putting the release next to the gateway lets the chart own
the `litellm-mcp` Namespace object while keeping `helm uninstall` unable to delete it.

`secrets.create=true` is the alternative to step 1 — every value is `required()`, so a
missing one fails the render instead of installing a placeholder. Keep that values file
**outside** the repository.

Once the pod is `Running`:

```bash
kubectl port-forward -n litellm-mcp deploy/litellm-mcp-admin 8080:8080
# open http://localhost:8080 — log in with the ADMIN_PASSWORD you seeded
```

Set the gateway target on the Connection page and probe it. Changing the admin password
from the Settings page is now safe on its own: `seed-config` uses `setdefault` for
`admin_password`, so `/data/config.json` wins from the first boot onward and the Secret
is not consulted again. Updating the Secret to match is still good hygiene — it is what a
freshly provisioned PVC would seed from.

---

## Upgrading a running install

`helm upgrade` is now the reconciliation path, and the two ways the old manifests could
destroy a live install are gone by construction: the chart renders no Secret unless you
ask it to, and it has no "apply the whole file" mode that could reset `ADMIN_PASSWORD`,
`MCP_AUTH_TOKEN` or `JWT_SECRET` to a placeholder.

```bash
helm diff upgrade litellm-mcp charts/litellm-mcp -n litellm \
  -f deploy/woow-k3s/litellm-mcp.yaml            # if the diff plugin is installed
CONTEXT=woow-k3s scripts/check-drift.sh          # or compare repo / release / cluster
helm upgrade litellm-mcp charts/litellm-mcp -n litellm \
  -f deploy/woow-k3s/litellm-mcp.yaml
```

Before an upgrade that changes the pod template, run through this:

1. **Back up the config.** `kubectl exec -n litellm-mcp deploy/litellm-mcp-admin -c admin
   -- cp /data/config.json /data/config.json.pre-upgrade.bak`. Prune old backups
   afterwards — each one is a full copy of the credentials.
2. **Check the Secret against the PVC.** This matters only when the *current* pod predates
   FINDING-004, because that version rebuilds the config from the Secret on every start:
   if the two have drifted, the restart flips the live `mcp_auth_token` and kills connected
   clients. Compare by digest, never by printing values — mount both secrets into a
   throwaway pod and `sha256sum` each, then diff against the same digests taken from
   `/data/config.json`. If they disagree, update the Secret to the live values first.
3. **Know what will change.** `scripts/check-drift.sh` prints the exact field-level
   difference between the chart, the release manifest and the live objects. A render that
   matches the live objects field for field rolls nothing.
4. **Expect downtime whenever the pod template changes.** `strategy: Recreate` plus a
   2.5–3 minute cold start means the console *and* the public MCP endpoint are unavailable
   for roughly three to four minutes. There is no zero-downtime path while the config PVC
   is `ReadWriteOnce`. Every `hardening.*` switch is such a change — that is why they are
   off by default.

Afterwards, verify rather than assume: the new pod should be `1/1` with **0 restarts**,
`/data/config.json` should be unchanged (compare the sha256 against the backup), and an
end-to-end call through the public URL should succeed. If the change touched
`seed-config`, extract the script from the *running* object and exercise it against a
synthetic config — reading the YAML back only proves the apply landed, not that the script
behaves.

If all you need is to pick up new code from `main`, you do not need an upgrade at all:
`/repo` is an emptyDir re-cloned on every start, so
`kubectl rollout restart deployment/litellm-mcp-admin -n litellm-mcp` is enough.

---

## Taking over an existing install

The objects may already exist — created by the old manifests, or owned by the `litellm`
release of `Woow_k3s_litellm`. Because the chart renders them field-identically, the
takeover is metadata-only and **restarts nothing**.

From the old `kubectl apply` manifests, or any unmanaged objects:

```bash
helm upgrade --install litellm-mcp charts/litellm-mcp -n litellm \
  -f deploy/woow-k3s/litellm-mcp.yaml --take-ownership
```

From the `litellm` release of `Woow_k3s_litellm`, which still renders these four objects
in its `templates/mcp.yaml`. Its `Namespace` and `PVC` already carry
`helm.sh/resource-policy: keep`; the `Deployment` and `Service` do not, and an upgrade that
stops rendering them would delete them, so annotate those two first:

```bash
# 1. Protect the two objects that have no keep policy yet.
kubectl -n litellm-mcp annotate deployment/litellm-mcp-admin service/litellm-mcp-admin \
  helm.sh/resource-policy=keep --overwrite

# 2. Record what must not change.
kubectl -n litellm-mcp get pod -l app=litellm-mcp-admin \
  -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,\
RESTARTS:.status.containerStatuses[0].restartCount
kubectl -n litellm-mcp get rs -l app=litellm-mcp-admin -o name

# 3. Drop the MCP objects out of the gateway release (they stay in the cluster).
helm upgrade litellm <Woow_k3s_litellm checkout> -n litellm --reuse-values \
  --set mcp.enabled=false

# 4. Adopt them here.
helm upgrade --install litellm-mcp charts/litellm-mcp -n litellm \
  -f deploy/woow-k3s/litellm-mcp.yaml --take-ownership

# 5. Prove nothing moved: same pod name, same UID, same restart count, same ReplicaSet.
kubectl -n litellm-mcp get pod -l app=litellm-mcp-admin \
  -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,\
RESTARTS:.status.containerStatuses[0].restartCount
helm test litellm-mcp -n litellm
# The smoke pod runs in litellm-mcp, the release in litellm, so `--logs` looks in
# the wrong namespace - read them directly:
kubectl -n litellm-mcp logs litellm-mcp-smoke
```

Step 1 leaves a `helm.sh/resource-policy: keep` annotation on the `Deployment` and
`Service` that the chart itself does not render. It is harmless — it only makes
`helm uninstall` leave them behind — but remove it afterwards if you want uninstall to
clean up the workload:

```bash
kubectl -n litellm-mcp annotate deployment/litellm-mcp-admin service/litellm-mcp-admin \
  helm.sh/resource-policy- --overwrite
```

---

## Uninstalling

```bash
helm uninstall litellm-mcp -n litellm
```

With `keepOnUninstall: true` (the default) the `Namespace`, the `PVC litellm-mcp-data` and
any chart-created `Secret` carry `helm.sh/resource-policy: keep`, so this removes the
`Deployment` and `Service` only. `/data/config.json` — admin password, MCP token, tool
toggles, token history — survives, and a re-install picks it up. Deleting the data is a
deliberate, separate act:

```bash
kubectl -n litellm-mcp delete pvc litellm-mcp-data   # irreversible
```

## Getting the public MCP URL

1. Log in to the console.
2. Go to **Tokens**.
3. The live `mcp_auth_token` is shown masked; the full public URL is
   `https://<admin-hostname>/private_<mcp_auth_token>/mcp/`.

Add that URL to an MCP client as a custom connector. There is no other public MCP
endpoint — the child binds loopback.

### Rotation

Rotating is instantaneous and breaks every connected client. The procedure:

1. Note which clients are connected.
2. Rotate on the Tokens page.
3. Repoint each client to the new URL.
4. Optionally update `Secret/litellm-mcp-admin-secret` key `MCP_AUTH_TOKEN` to match.
   This is no longer required for correctness — `seed-config` seeds the token with
   `setdefault`, so the rotated value in `/data/config.json` survives pod restarts. It
   matters only if the PVC is ever recreated from scratch, in which case the Secret is
   what the new config seeds from.

On a cluster still running a pre-FINDING-004 manifest, step 4 is **mandatory** and must
happen before the next restart, or the rotation reverts silently.

`POST /api/tokens/generate` previews a candidate without committing it; only
`POST /api/tokens/rotate` writes. Keep that distinction in mind when scripting.

### The token is visible at the edge

The token is part of the URL path, so anything that logs a request line logs the token.
The proxy strips the private prefix before the inner request is logged, which keeps it
out of the console's own log ring buffer — but `cloudflared` logs the full destination
URL, including the token, on every origin error:

```
ERR Request failed … dest=https://litellm-mcp.woowtech.io/private_<token>/mcp
```

Treat tunnel logs, edge analytics and any reverse-proxy access log in the path as
containing a live credential. This is a property of putting the secret in the URL at all
and is discussed in [`architecture.md` §4](./architecture.md#4-why-the-token-lives-in-the-path).

---

## Applying a permission change

Gating is evaluated at tool-registration time, so a change on the Permissions page does
not take effect until the MCP child restarts.

1. Edit on **Permissions** and save. The change is written to `/data/config.json`.
2. Go to **Settings** and restart the MCP child.
3. Confirm on **Dashboard** — the restart counter increments and the PID changes.
4. Re-list tools from a client to confirm the surface changed.

Restarting the child does not restart the pod, so the proxy stays up and the console
stays logged in.

---

## Health checks

```bash
# The namespace should contain exactly one Deployment: litellm-mcp-admin.
# If litellm-mcp-server or Service/litellm-mcp is still there, it is a leftover —
# see "Removed: the standalone Deployment" above.
kubectl get deploy,svc,pods -n litellm-mcp

# Pod and container state
kubectl logs -n litellm-mcp deploy/litellm-mcp-admin -c admin --tail=100

# Which origin the tunnel is actually dialling
kubectl logs -n litellm deploy/cloudflared --tail=200 | grep originService

# Init container logs — this is the only place an SPA build failure appears
kubectl logs -n litellm-mcp deploy/litellm-mcp-admin -c spa-build

# Gateway reachability from inside the MCP pod
kubectl exec -n litellm-mcp deploy/litellm-mcp-admin -c admin -- \
  python -c "import httpx;print(httpx.get('http://litellm.litellm.svc.cluster.local:4000/health/readiness').status_code)"
```

From the console: **Dashboard** shows the child's PID and restart count; **Connection**
has a probe button that calls `/health/readiness` against the configured base URL;
**Logs** streams the ring buffer live.

---

## Troubleshooting

**Pod stuck in `Init:CrashLoopBackOff`.** Not the SPA build — that cannot fail the pod.
Check `git-clone` (network or repo access) and `seed-config` (PVC not bound).

**Console loads but looks stale after a deploy.** The SPA build failed silently and the
committed `dist/` is being served. Check the `spa-build` init container logs.

**Rollout hangs forever.** Confirm `strategy: Recreate` is still set. Under
`RollingUpdate` the new pod cannot mount the `ReadWriteOnce` PVC while the old pod
holds it.

**MCP client gets 404 on the private URL.** The path token does not match the stored
`mcp_auth_token`. A wrong token and a wrong path return the same response by design, so
re-read the token from the Tokens page rather than guessing.

**MCP client connects but sees fewer tools than expected.** A gate is active. Check the
Permissions page and the `LITELLM_MCP_DISABLED_*` environment variables — environment
gates and stored gates both apply.

**Tool calls fail with upstream errors.** The MCP layer surfaces LiteLLM's error body
intact (`tests/test_errors.py` pins this), so read the message: it is the gateway
talking, not this project.

**Cloudflare tunnel returns a challenge page to the MCP client.** Bot Fight Mode
intercepts non-browser clients. See
[`encrypted-proxy.md`](./encrypted-proxy.md) for the exemption rule.

---

## Upgrading LiteLLM

The gateway is pinned to `v1.83.14-stable`. Before moving it:

1. Check whether any registry `path` changed upstream — `/v2/team/list` already
   replaced a v1 endpoint once.
2. Run `pytest -m live` against a staging gateway on the new version.
3. **Do not touch `LITELLM_SALT_KEY`.** It encrypts database columns; rotating it makes
   every previously encrypted value undecryptable. This is irreversible.

Upgrading the MCP suite itself is `git push` plus a rollout restart, since `/repo` is
re-cloned each start.

---

## Backup

The only stateful item on the MCP side is `/data/config.json` on PVC
`litellm-mcp-data`. It holds the connection settings, per-tool enablement, gates, the
hashed admin password and `mcp_auth_token`.

```bash
kubectl exec -n litellm-mcp deploy/litellm-mcp-admin -c admin -- \
  cat /data/config.json > config-backup.json
```

The backup contains secrets. Store it accordingly and do not commit it.

The gateway's own state lives in its Postgres database and is backed up separately.
