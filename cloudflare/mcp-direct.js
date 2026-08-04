/**
 * Woow LiteLLM MCP — Cloudflare Worker (direct pass-through)
 * ==========================================================
 * Gives the MCP endpoint its OWN hostname at the Cloudflare edge and forwards
 * to the encrypted-proxy Service (the admin console's /private_{token}/ route).
 * TLS terminates here; the upstream path-token stays server-side.
 *
 * Routes:
 *   /private_{token}/mcp/*   -> pass straight through (caller supplies the token)
 *   /mcp   and  /mcp/*       -> convenience alias that injects UPSTREAM_TOKEN so
 *                               Claude's connector can use a clean /mcp URL
 *   /.well-known/*           -> clean JSON 404 so OAuth discovery fails fast and
 *                               the connector falls back to anonymous (no broken
 *                               OAuth handshake)
 *
 * Bindings (wrangler.toml [vars] / secrets):
 *   UPSTREAM_BASE   e.g. https://litellm-mcp-admin.internal  (the admin proxy)
 *   UPSTREAM_TOKEN  the mcp_auth_token used in /private_{token}/  (secret)
 *
 * Streaming: the Streamable-HTTP MCP flow uses SSE + Mcp-Session-Id /
 * MCP-Protocol-Version headers in both directions. A plain fetch() pass-through
 * preserves them; we only strip hop-by-hop headers.
 */

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function stripHopByHop(headers) {
  const out = new Headers(headers);
  for (const h of HOP_BY_HOP) out.delete(h);
  return out;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // OAuth-discovery: return a clean JSON 404 so the connector goes anonymous.
    if (path.startsWith("/.well-known/")) {
      return new Response(JSON.stringify({ error: "not_found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      });
    }

    let upstreamPath;
    if (path.startsWith("/private_")) {
      // Caller already supplied the token segment — forward verbatim.
      upstreamPath = path;
    } else if (path === "/mcp" || path.startsWith("/mcp/")) {
      // Clean alias — inject the upstream token.
      const rest = path.slice("/mcp".length); // "" or "/..."
      upstreamPath = `/private_${env.UPSTREAM_TOKEN}/mcp${rest || "/"}`;
    } else {
      return new Response(JSON.stringify({ error: "not_found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      });
    }

    const target = new URL(env.UPSTREAM_BASE);
    target.pathname = upstreamPath;
    target.search = url.search;

    const init = {
      method: request.method,
      headers: stripHopByHop(request.headers),
      redirect: "manual",
    };
    if (!["GET", "HEAD"].includes(request.method)) {
      init.body = request.body;
    }

    const resp = await fetch(target.toString(), init);

    // Pass the response (incl. SSE stream) through untouched, minus hop-by-hop.
    const headers = stripHopByHop(resp.headers);
    headers.set("x-accel-buffering", "no"); // never buffer SSE at the edge
    return new Response(resp.body, {
      status: resp.status,
      statusText: resp.statusText,
      headers,
    });
  },
};
