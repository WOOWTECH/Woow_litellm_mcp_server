# Deployment runbook

Operational notes for running `Woow_litellm_mcp_server` on k3s, written against the
live deployment at `https://litellm-mcp.woowtech.io`.

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

`k8s-admin-deploy.yaml` runs the admin console on `0.0.0.0:8080`, and the console
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
                            ┌───────────────────────────────────────┐
  Internet ──► Cloudflare ──►│ Service litellm-mcp-admin :8080           │
                            │   admin console (SPA + /api/*, JWT)       │
                            │   /private_{token}/mcp/  ── proxy ──┐      │
                            │                                     ▼      │
                            │        FastMCP child 127.0.0.1:3000        │──► litellm:4000
                            └───────────────────────────────────────┘
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
not. That is FINDING-003 in [`findings.md`](../findings.md). The namespace and secret now
live alone in `k8s-base.yaml`, which contains no workload at all.

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
> [`findings.md`](../findings.md), fixed in `k8s-admin-deploy.yaml`. A cluster running the
> old manifest keeps the old behaviour until the manifest is re-applied, and under
> `strategy: Recreate` re-applying means a short console outage — schedule it.

The one legacy migration it performs is folding a pre-existing `tools.disabled` list
into `tools.disabled_tools` and dropping the old key, so a reader never sees both.

The main `admin` container then `pip install`s from `/repo` and launches
`uvicorn litellm_mcp_admin.main:app --host 0.0.0.0 --port 8080`.

**Cold start is 2.5–3 minutes.** Most of it is the pip install and the npm build. Do not
interpret a pod sitting in `Init:2/3` for two minutes as a failure.

**`/repo` is an emptyDir**, repopulated on every restart. This means a pod restart
always picks up the current `main` branch — deployment is `git push` followed by
`kubectl rollout restart deployment/litellm-mcp-admin -n litellm-mcp`. It also means
there is no way to pin a commit without editing the manifest.

**`strategy: Recreate`** is required, not stylistic. See
[`architecture.md` §6](./architecture.md#6-why-recreate-and-why-exit-0).

---

## First deploy

Two manifests, applied in order. `k8s-base.yaml` carries the namespace and the gateway
credentials and **no workload**; `k8s-admin-deploy.yaml` carries the entire console
stack.

```bash
# 1. Namespace + Secret/litellm-mcp-secret.
#    Do NOT commit real keys. Create the secret from the command line instead of
#    editing the file, so the master key never touches the working tree:
kubectl apply -f k8s-base.yaml            # namespace (secret has placeholders)
kubectl create secret generic litellm-mcp-secret -n litellm-mcp \
  --from-literal=LITELLM_BASE_URL='http://litellm.litellm.svc.cluster.local:4000' \
  --from-literal=LITELLM_MASTER_KEY='sk-…' \
  --dry-run=client -o yaml | kubectl apply -f -

# 2. Console credentials. Same rule — replace the placeholders in
#    Secret/litellm-mcp-admin-secret before or immediately after applying.
#      ADMIN_PASSWORD   console login
#      MCP_AUTH_TOKEN   python -c "import secrets;print(secrets.token_urlsafe(32))"
#      JWT_SECRET       python -c "import secrets;print(secrets.token_hex(32))"
#
# 3. Admin console + encrypted proxy + loopback MCP child + PVC
kubectl apply -f k8s-admin-deploy.yaml

# 4. Watch the init chain
kubectl get pods -n litellm-mcp -w
```

On a cluster that already has the namespace and a real `litellm-mcp-secret`, **skip step
1 entirely** — applying `k8s-base.yaml` over it would overwrite the live master key with
the placeholder.

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
