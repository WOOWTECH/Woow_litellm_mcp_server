"""LiteLLM MCP Admin — GUI, Admin API and MCP proxy on a single port.

Mirrors ``emqx_mcp_admin.main`` / ``n8n_mcp_admin.main``: ``mcp_admin_core``
supplies the FastAPI factory, JWT middleware, config store, subprocess manager
and MCP reverse proxy; this module only contributes the LiteLLM-specific
routers.

``extra_routers`` MUST be passed to the factory — routers added after
``create_app()`` returns are shadowed by the SPA catch-all route (the
load-bearing gotcha preserved from the reference).
"""

from __future__ import annotations

from mcp_admin_core.app import create_app

from .routers import config, health, logs, tokens, tools

app = create_app(
    title="LiteLLM MCP Admin",
    extra_routers=[
        config.router,
        tools.router,
        tokens.router,
        health.router,
        logs.router,
    ],
)


@app.middleware("http")
async def no_store(request, call_next):
    """Keep the admin UI out of every cache in front of it.

    Behind Cloudflare a single 404 from before the tunnel route existed got
    cached at the edge and kept serving long after the origin was healthy.
    Nothing here is cacheable anyway: the SPA shell is tiny and every API
    response is live state.
    """
    response = await call_next(request)
    if not request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response
