# The encrypted MCP proxy

The FastMCP server itself speaks plain Streamable-HTTP with no authentication —
which is fine on loopback and wrong on the public internet. The admin console
(`mcp_admin_core`) wraps it so exactly one public URL carries a secret, and
everything else stays unreachable.

## Shape

```
Internet ──TLS──► Cloudflare tunnel ──► Service litellm-mcp-admin:8080
                                             │
                                   /private_{token}/mcp/   ← the only MCP door
                                             │  token checked against
                                             │  /data/config.json
                                             ▼
                                   127.0.0.1:3000  FastMCP child
                                             │  (loopback bind, no listener
                                             │   on any routable interface)
                                             ▼
                              LiteLLM gateway (in-cluster Service :4000)
```

Three layers of isolation, in order:

1. **Transport encryption.** The public hostname is served by a Cloudflare
   tunnel, so the wire is TLS end to end and the cluster exposes no inbound
   port, no NodePort, no LoadBalancer.
2. **The URL-path token.** `mcp_admin_core.proxy` matches `{token}` against
   `mcp_auth_token` in the config store and returns `403` on any mismatch. The
   secret lives in the path rather than a header because MCP clients configure
   a URL and not always custom headers — a 32-byte `secrets.token_urlsafe`
   value has the same entropy either way.
3. **The loopback child.** The FastMCP server binds `127.0.0.1:3000`. Even from
   inside the pod's namespace there is nothing to reach without going through
   the proxy, and no Service points at it.

The admin console's own `/api/*` routes are JWT-gated separately
(`AuthMiddleware`); `/private_*` skips that middleware precisely because the
proxy does its own check.

## Streaming correctness

MCP's Streamable-HTTP flow is stateful: `initialize` returns an
`Mcp-Session-Id` that every later request must echo, and responses may arrive
as `text/event-stream`. The proxy therefore forwards all headers except the
hop-by-hop ones, relays `Mcp-Session-Id` and `MCP-Protocol-Version` in both
directions, strips `content-length`/`content-encoding` from the response, sets
`x-accel-buffering: no`, and streams the body through with
`httpx` + `StreamingResponse`. The client timeout defaults to 86400s so a long
tool call is never cut off mid-stream.

## Connecting a client

```jsonc
{
  "mcpServers": {
    "woow-litellm": {
      "type": "http",
      "url": "https://<your-host>/private_<token>/mcp/"
    }
  }
}
```

Verify by hand:

```bash
curl -sS https://<your-host>/private_<token>/mcp/ \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2025-06-18","capabilities":{},
                 "clientInfo":{"name":"probe","version":"1"}}}'
```

A `200` with `event: message` and an `mcp-session-id` response header means the
whole chain is live. Feed that session id back as `Mcp-Session-Id` on a
`tools/list` call and you should see all 38 `litellm_*` tools.

## Rotating the token

`POST /api/tokens/rotate` (admin JWT) generates a new token, persists it, and
restarts the child. The previous URL stops working immediately — only a masked
form of it is kept in `token_history`. `POST /api/tokens/generate` only
*previews* a candidate and changes nothing, so you can copy the new URL into
clients before committing to the rotation.

## Operational note — Cloudflare Bot Fight Mode

If the zone has Bot Fight Mode on, Cloudflare blocks requests whose
`User-Agent` matches a known-bot signature with **error 1010
(`browser_signature_banned`)** before the tunnel is ever reached. In practice
only literal library UAs are hit: `Python-urllib/3.x` gets a `403`, while
`node`, `curl/*`, `python-httpx/*` and real MCP clients pass. If a client is
blocked, either set a normal `User-Agent` on it, or add a WAF **skip** rule in
the Cloudflare dashboard scoped to that hostname and
`starts_with(http.request.uri.path, "/private_")` — narrow enough that the
admin console keeps its protection.
