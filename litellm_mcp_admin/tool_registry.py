"""Re-export of the tool registry for the Admin layer.

The MCP server owns the canonical list (``woow_litellm_mcp_server.registry``)
so the switches in the GUI can never reference a tool that does not exist — an
invariant enforced by ``tests/test_mcp_surface.py``.
"""

from __future__ import annotations

from woow_litellm_mcp_server.registry import (  # noqa: F401
    TOOL_REGISTRY,
    TOOLS_BY_NAME,
    ToolCategory,
    ToolSpec,
    categorized,
)


def get_tool_by_name(name: str) -> ToolSpec | None:
    return TOOLS_BY_NAME.get(name)


def get_all_tool_names() -> list[str]:
    return [spec.name for spec in TOOL_REGISTRY]
