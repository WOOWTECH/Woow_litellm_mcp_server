"""Claude-Code skill-hub plugin tools (category: plugins)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..deps import litellm_client
from ..gating import ToolGate
from ._common import prune_none, read_only, writing


def register(mcp: Any, gate: ToolGate) -> None:
    if gate.is_tool_enabled("litellm_list_plugins"):

        @mcp.tool(
            name="litellm_list_plugins",
            annotations=read_only("List plugins"),
        )
        async def litellm_list_plugins(
            ctx: Context, enabled_only: bool = False
        ) -> Any:
            """List Claude-Code skill-hub plugins.

            Set ``enabled_only`` to hide disabled plugins.
            """
            params = prune_none(
                {"enabled_only": enabled_only if enabled_only else None}
            )
            return await litellm_client(ctx).get(
                "/claude-code/plugins", params=params
            )

    if gate.is_tool_enabled("litellm_register_plugin"):

        @mcp.tool(
            name="litellm_register_plugin",
            annotations=writing("Register plugin"),
        )
        async def litellm_register_plugin(
            ctx: Context,
            name: str,
            source: str,
            version: str | None = None,
            description: str | None = None,
            category: str | None = None,
            domain: str | None = None,
            namespace: str | None = None,
        ) -> dict:
            """Register a skill-hub plugin.

            ``source`` is the plugin's origin (repo/URL); the rest is metadata.
            """
            body = prune_none(
                {
                    "name": name,
                    "source": source,
                    "version": version,
                    "description": description,
                    "category": category,
                    "domain": domain,
                    "namespace": namespace,
                }
            )
            return await litellm_client(ctx).post(
                "/claude-code/plugins", json_data=body
            )

    if gate.is_tool_enabled("litellm_enable_plugin"):

        @mcp.tool(
            name="litellm_enable_plugin",
            annotations=writing("Enable plugin"),
        )
        async def litellm_enable_plugin(ctx: Context, plugin_name: str) -> dict:
            """Enable a registered skill-hub plugin."""
            return await litellm_client(ctx).post(
                f"/claude-code/plugins/{plugin_name}/enable"
            )

    if gate.is_tool_enabled("litellm_disable_plugin"):

        @mcp.tool(
            name="litellm_disable_plugin",
            annotations=writing("Disable plugin"),
        )
        async def litellm_disable_plugin(ctx: Context, plugin_name: str) -> dict:
            """Disable a registered skill-hub plugin."""
            return await litellm_client(ctx).post(
                f"/claude-code/plugins/{plugin_name}/disable"
            )

    if gate.is_tool_enabled("litellm_skill_hub"):

        @mcp.tool(
            name="litellm_skill_hub",
            annotations=read_only("Skill hub"),
        )
        async def litellm_skill_hub(ctx: Context) -> Any:
            """Fetch the public skill-hub / marketplace catalog of skills."""
            return await litellm_client(ctx).get("/public/skill_hub")
