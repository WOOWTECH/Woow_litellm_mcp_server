"""Health / readiness tools (category: health)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..deps import litellm_client
from ..gating import ToolGate
from ._common import prune_none, read_only


def register(mcp: Any, gate: ToolGate) -> None:
    if gate.is_tool_enabled("litellm_health"):

        @mcp.tool(
            name="litellm_health",
            annotations=read_only("Health"),
        )
        async def litellm_health(
            ctx: Context, model: str | None = None
        ) -> dict:
            """Per-deployment health check.

            Optionally restrict the check to a single ``model``. Returns the
            healthy/unhealthy endpoint lists.
            """
            params = prune_none({"model": model})
            return await litellm_client(ctx).get("/health", params=params)

    if gate.is_tool_enabled("litellm_health_readiness"):

        @mcp.tool(
            name="litellm_health_readiness",
            annotations=read_only("Health readiness"),
        )
        async def litellm_health_readiness(ctx: Context) -> dict:
            """Gateway readiness including DB and cache status.

            This is the endpoint the admin console's connection-test probe hits.
            """
            return await litellm_client(ctx).get("/health/readiness")
