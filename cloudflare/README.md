# Cloudflare edge for Woow LiteLLM MCP

Optional. Gives the MCP endpoint its own hostname at the Cloudflare edge and
forwards to the admin console's encrypted proxy (`/private_{token}/mcp/`). TLS
terminates at the edge; the upstream path-token never leaves the server side.

## Files

| File | Purpose |
| --- | --- |
| `mcp-direct.js` | Direct pass-through worker. `/mcp` alias injects `UPSTREAM_TOKEN`; `/.well-known/*` returns a clean JSON 404 so Claude's connector falls back to anonymous (no broken OAuth handshake). |
| `mcp-oauth-gateway.js` | Real-auth variant: fronts the endpoint with an OAuth 2.0 protected-resource + bearer gate before forwarding. |
| `wrangler.toml` | Worker name, `main` entry, `UPSTREAM_BASE` var, and route placeholder. |

## Deploy

```bash
cd cloudflare
npx wrangler secret put UPSTREAM_TOKEN     # = the admin mcp_auth_token
npx wrangler deploy                        # deploys mcp-direct.js by default
```

For the OAuth variant, point `main` at `mcp-oauth-gateway.js` (or use
`--name`), then also set `OAUTH_CLIENT_SECRET` and `ACCESS_TOKENS`.

## How it fits

```
Claude connector
      │  https://mcp.woowtech.io/mcp/
      ▼
Cloudflare Worker (this dir)     ── injects /private_{token}/ ──►
      ▼
litellm-mcp-admin :8080  (encrypted proxy, JWT-gated GUI)
      ▼  127.0.0.1:3000 loopback
FastMCP child (woow_litellm_mcp_server) — 40 LiteLLM tools
```

The worker is a plain `fetch()` pass-through, so the Streamable-HTTP flow
(SSE + `Mcp-Session-Id` + `MCP-Protocol-Version` in both directions) is
preserved; only hop-by-hop headers are stripped and `x-accel-buffering: no` is
set so SSE is never buffered at the edge.

A Cloudflare **Tunnel** is a simpler alternative to a public origin: run
`cloudflared` next to the `litellm-mcp-admin` Service and map the hostname to
`http://litellm-mcp-admin.litellm-mcp.svc.cluster.local:8080`, then point
`UPSTREAM_BASE` at that tunnel hostname (or skip the worker entirely and expose
`/private_{token}/mcp/` directly).
