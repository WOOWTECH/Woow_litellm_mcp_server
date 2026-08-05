# Deployment runbook

Operational notes for running `Woow_litellm_mcp_server` on k3s, written against the
live deployment at `https://litellm-mcp.woowtech.io`.

---

## Topology

| Namespace | Workload | Image | Exposure |
|---|---|---|---|
| `litellm` | Deployment `litellm` | `ghcr.io/berriai/litellm:v1.83.14-stable` | Service `:4000`, tunnel → `litellm.woowtech.io` |
| `litellm-mcp` | Deployment `litellm-mcp-admin` | `python:3.12-slim` + init chain | Service `:8080`, tunnel → `litellm-mcp.woowtech.io` |

The MCP suite reaches the gateway at `litellm.litellm.svc.cluster.local:4000`. That
traffic is cluster-internal; the public tunnels exist for human access, not for
service-to-service calls.

---

## The init chain

`litellm-mcp-admin` runs three init containers in order before the main container
starts.

| # | Name | Image | Does |
|---|---|---|---|
| 1 | `git-clone` | `alpine/git` | Clones this public repo into the `/repo` emptyDir. |
| 2 | `spa-build` | `node:20-alpine` | `npm ci && npm run build` in `frontend/`. **Ends in `exit 0`.** |
| 3 | `seed-config` | `python:3.12-slim` | Seeds `/data/config.json` on the PVC if absent. Idempotent. |

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

# 2. Bare MCP server (namespace + deployment + service)
kubectl apply -f k8s-deploy.yaml

# 3. Admin console + encrypted proxy
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
page and probe it.

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

`POST /api/tokens/generate` previews a candidate without committing it; only
`POST /api/tokens/rotate` writes. Keep that distinction in mind when scripting.

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
# Pod and container state
kubectl get pods -n litellm-mcp
kubectl logs -n litellm-mcp deploy/litellm-mcp-admin -c admin --tail=100

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
