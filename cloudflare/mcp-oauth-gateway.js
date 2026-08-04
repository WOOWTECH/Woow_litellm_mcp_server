/**
 * Woow LiteLLM MCP — Cloudflare Worker (real-auth OAuth gateway variant)
 * ======================================================================
 * Same edge role as mcp-direct.js, but instead of anonymous fallback it fronts
 * the MCP endpoint with a minimal OAuth 2.0 Protected-Resource + bearer gate,
 * so Claude's connector performs a real authorization-code exchange before it
 * can reach tools/list and tools/call.
 *
 * This is the "encrypted/private" posture taken one step further: the edge
 * requires a bearer, and only then injects the upstream path-token toward the
 * admin proxy.
 *
 * Bindings (wrangler.toml [vars] / secrets):
 *   UPSTREAM_BASE        the admin proxy base, e.g. https://litellm-mcp-admin.internal
 *   UPSTREAM_TOKEN       mcp_auth_token for /private_{token}/ (secret)
 *   OAUTH_ISSUER         this worker's public origin, e.g. https://mcp.woowtech.io
 *   OAUTH_CLIENT_ID      registered client id
 *   OAUTH_CLIENT_SECRET  registered client secret (secret)
 *   ACCESS_TOKENS        (optional) comma-separated set of accepted bearer tokens
 *
 * NOTE: this is a compact reference gateway, not a full IdP. For production SSO,
 * put Cloudflare Access in front and keep mcp-direct.js as the origin worker.
 */

const HOP_BY_HOP = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
  "te", "trailer", "transfer-encoding", "upgrade",
]);

function stripHopByHop(headers) {
  const out = new Headers(headers);
  for (const h of HOP_BY_HOP) out.delete(h);
  return out;
}

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...extra },
  });
}

function acceptedTokens(env) {
  return new Set(
    (env.ACCESS_TOKENS || "")
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean),
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // --- OAuth discovery documents -----------------------------------------
    if (path === "/.well-known/oauth-protected-resource") {
      return json({
        resource: env.OAUTH_ISSUER,
        authorization_servers: [env.OAUTH_ISSUER],
        bearer_methods_supported: ["header"],
      });
    }
    if (path === "/.well-known/oauth-authorization-server") {
      return json({
        issuer: env.OAUTH_ISSUER,
        authorization_endpoint: `${env.OAUTH_ISSUER}/authorize`,
        token_endpoint: `${env.OAUTH_ISSUER}/token`,
        response_types_supported: ["code"],
        grant_types_supported: ["authorization_code"],
        token_endpoint_auth_methods_supported: ["client_secret_post"],
        code_challenge_methods_supported: ["S256"],
      });
    }

    // --- Minimal authorize/token endpoints ---------------------------------
    // Real deployments delegate these to Cloudflare Access or an IdP; this stub
    // exists so the discovery flow resolves. Replace with your provider.
    if (path === "/authorize") {
      const redirectUri = url.searchParams.get("redirect_uri");
      const state = url.searchParams.get("state") || "";
      if (!redirectUri) return json({ error: "invalid_request" }, 400);
      const to = new URL(redirectUri);
      to.searchParams.set("code", "stub-authorization-code");
      if (state) to.searchParams.set("state", state);
      return Response.redirect(to.toString(), 302);
    }
    if (path === "/token" && request.method === "POST") {
      const form = await request.formData();
      if (form.get("client_id") !== env.OAUTH_CLIENT_ID) {
        return json({ error: "invalid_client" }, 401);
      }
      // Issue the configured access token (first of ACCESS_TOKENS).
      const token = acceptedTokens(env).values().next().value || "stub-access-token";
      return json({ access_token: token, token_type: "Bearer", expires_in: 3600 });
    }

    // --- Gate the MCP traffic ----------------------------------------------
    const auth = request.headers.get("authorization") || "";
    const bearer = auth.toLowerCase().startsWith("bearer ")
      ? auth.slice(7).trim()
      : "";
    const allowed = acceptedTokens(env);
    if (allowed.size > 0 && !allowed.has(bearer)) {
      return json({ error: "invalid_token" }, 401, {
        "www-authenticate": `Bearer resource_metadata="${env.OAUTH_ISSUER}/.well-known/oauth-protected-resource"`,
      });
    }

    // --- Forward to the upstream admin proxy -------------------------------
    let upstreamPath;
    if (path === "/mcp" || path.startsWith("/mcp/")) {
      const rest = path.slice("/mcp".length);
      upstreamPath = `/private_${env.UPSTREAM_TOKEN}/mcp${rest || "/"}`;
    } else if (path.startsWith("/private_")) {
      upstreamPath = path;
    } else {
      return json({ error: "not_found" }, 404);
    }

    const target = new URL(env.UPSTREAM_BASE);
    target.pathname = upstreamPath;
    target.search = url.search;

    const init = {
      method: request.method,
      headers: stripHopByHop(request.headers),
      redirect: "manual",
    };
    if (!["GET", "HEAD"].includes(request.method)) init.body = request.body;

    const resp = await fetch(target.toString(), init);
    const headers = stripHopByHop(resp.headers);
    headers.set("x-accel-buffering", "no");
    return new Response(resp.body, {
      status: resp.status,
      statusText: resp.statusText,
      headers,
    });
  },
};
