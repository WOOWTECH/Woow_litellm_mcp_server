# Deployment runbook

Operational notes for running `Woow_litellm_mcp_server` on k3s, written against the
live deployment at `https://litellm-mcp.woowtech.io`.

---

## Topology

There are **three** workloads, not two. `litellm-mcp` runs two independent Deployments,
and only one of them is reachable from outside the cluster.

| Namespace | Deployment | Image | Service | Public |
|---|---|---|---|---|
| `litellm` | `litellm` | `ghcr.io/berriai/litellm:v1.83.14-stable` | `litellm:4000` | tunnel → `litellm.woowtech.io` |
| `litellm-mcp` | `litellm-mcp-admin` | `python:3.12-slim` + 3 init containers | `litellm-mcp-admin:8080` | tunnel → `litellm-mcp.woowtech.io` |
| `litellm-mcp` | `litellm-mcp-server` | `python:3.12-slim` + 1 init container | `litellm-mcp:8000` | **none — cluster-internal only** |

The MCP suite reaches the gateway at `litellm.litellm.svc.cluster.local:4000`. That
traffic is cluster-internal; the public tunnels exist for human access, not for
service-to-service calls.

### Two ways to run the MCP server, and which one is live

The server can be run in either of two modes, and this cluster currently has **both**
deployed at once.

**Mode A — standalone (`litellm-mcp-server`).** `k8s-deploy.yaml` runs the bare FastMCP
server with `--host 0.0.0.0 --port 8000`, fronted by Service `litellm-mcp:8000`. One
init container (`git-clone`), `emptyDir` volumes only, no PVC, `strategy: RollingUpdate`.
There is no console, no SPA, no proxy and no authentication in front of it — anything
that can reach the Service can call every registered tool. It is intended for
in-cluster consumers that already sit behind their own trust boundary.

**Mode B — console-embedded (`litellm-mcp-admin`).** `k8s-admin-deploy.yaml` runs the
admin console on `0.0.0.0:8080` and the console *spawns its own FastMCP child* as a
subprocess bound to `127.0.0.1:3000`. The child is written into `/data/config.json` by
the `seed-config` init container:

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
that child. **The console does not talk to `litellm-mcp:8000`** — Mode B is entirely
self-contained, which is why "the console contains the server" is an accurate
description of Mode B and a wrong description of the namespace as a whole.

**What is actually serving.** The Cloudflare tunnel in namespace `litellm` is a
remotely-managed (token) tunnel, so its ingress rules live in the Cloudflare dashboard
rather than in a ConfigMap. `cloudflared`'s own logs name the origin explicitly:

```
ingressRule=1 originService=http://litellm-mcp-admin.litellm-mcp.svc.cluster.local:8080
dest=https://litellm-mcp.woowtech.io/private_…/mcp
```

So public MCP traffic terminates on `litellm-mcp-admin:8080` → loopback `:3000`. No
ingress rule points at `litellm-mcp:8000`; the standalone Deployment's last inbound
request from anything other than its own pod was a manual in-cluster probe. **It is
running, healthy and idle.** Keep it if you want an unauthenticated in-cluster endpoint;
otherwise `kubectl delete -f k8s-deploy.yaml`'s Deployment and Service stanzas remove a
live, unauthenticated surface for zero loss of function.

```
                            ┌───────────────────────────────────────────┐
  Internet ──► Cloudflare ──►│ Service litellm-mcp-admin :8080           │
                            │   admin console (SPA + /api/*, JWT)       │
                            │   /private_{token}/mcp/  ── proxy ──┐      │
                            │                                     ▼      │
                            │        FastMCP child 127.0.0.1:3000        │
                            └──────────────────────┬────────────────────┘
                                                   │ cluster DNS
                            ┌──────────────────────▼────────────────────┐
       (no public route) ──►│ Service litellm-mcp :8000                 │──► litellm:4000
                            │   standalone FastMCP, no auth, idle       │
                            └───────────────────────────────────────────┘
```

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

It is **not** "seed only if absent". It runs on every pod start and splits the config
into keys it owns and keys it preserves:

| Behaviour | Keys |
|---|---|
| **Overwritten from the Secret, every start** | `admin_password`, `mcp_auth_token`, `connection.litellm_mcp_base_url`, `connection.litellm_mcp_master_key` |
| **Overwritten from the manifest, every start** | `mcp_server.command`, `mcp_server.args`, `mcp_server.port` |
| **Preserved across restarts** | `mcp_server.env` (the `LITELLM_MCP_*` gating switches), `tools.*`, `token_history`, `proxy` |

That distinction has a sharp operational edge: **a password change or a token rotation
made in the console survives only until the next pod restart.** The console writes the
new value to `/data/config.json`, and the next `seed-config` run puts the Secret's value
back. If you change either from the console, update
`Secret/litellm-mcp-admin-secret` (`ADMIN_PASSWORD`, `MCP_AUTH_TOKEN`) to match, or the
change will silently revert on the next rollout, node drain or eviction.

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

```bash
# 1. Secret — fill in the real values first. Never commit the filled file.
cp k8s-secret.example.yaml k8s-secret.yaml
$EDITOR k8s-secret.yaml
kubectl apply -f k8s-secret.yaml

# 2. Namespace + secret, and the standalone MCP server (Mode A).
#    Note: k8s-deploy.yaml also creates the namespace and litellm-mcp-secret that
#    step 3 depends on. If you only want the console (Mode B), apply this file but
#    delete Deployment/litellm-mcp-server and Service/litellm-mcp afterwards —
#    the console spawns its own child and never uses them.
kubectl apply -f k8s-deploy.yaml

# 3. Admin console + encrypted proxy + loopback MCP child (Mode B)
kubectl apply -f k8s-admin-deploy.yaml

# 4. Watch the init chain
kubectl get pods -n litellm-mcp -w
```

Once the pod is `Running`:

```bash
kubectl port-forward -n litellm-mcp deploy/litellm-mcp-admin 8080:8080
# open http://localhost:8080 — default password is `admin`
```

Change the admin password on first login, then set the gateway target on the Connection
page and probe it. On k3s, also change `ADMIN_PASSWORD` in
`Secret/litellm-mcp-admin-secret` to the same value — otherwise `seed-config` restores
the old password on the next pod start (see above).

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
3. **Write the new token into `Secret/litellm-mcp-admin-secret` key `MCP_AUTH_TOKEN`.**
   Skip this and `seed-config` reverts the token on the next pod start, silently
   breaking the clients you just repointed.
4. Repoint each client to the new URL.

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
# Both deployments in the namespace — expect litellm-mcp-admin and, if Mode A is
# still deployed, litellm-mcp-server
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
