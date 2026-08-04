"""The /api/tools GET/PUT contract the Web GUI drives, and apply_to_runtime."""

from __future__ import annotations

import json

from litellm_mcp_admin.routers import tools as tools_router
from litellm_mcp_admin.store import ToolConfigStore
from woow_litellm_mcp_server.registry import TOOL_REGISTRY


def _store(temp_config) -> ToolConfigStore:
    return ToolConfigStore(temp_config)


def test_get_tools_renders_full_registry(temp_config) -> None:
    view = tools_router.get_tools(_store(temp_config))

    # Flat list + grouped categories, both derived from the registry.
    assert len(view["tools"]) == len(TOOL_REGISTRY)
    assert view["total"] == len(TOOL_REGISTRY)
    assert view["enabled_count"] == len(TOOL_REGISTRY)  # nothing disabled yet

    names = {t["name"] for t in view["tools"]}
    assert names == {s.name for s in TOOL_REGISTRY}

    # Grouped view mirrors the flat one.
    grouped_names = {
        t["name"] for group in view["categories"] for t in group["tools"]
    }
    assert grouped_names == names

    # Each tool entry carries the fields the SPA renders.
    sample = view["tools"][0]
    assert {"name", "category", "description", "dangerous", "enabled", "operations"} <= set(sample)


async def test_put_tools_disables_a_tool_and_persists(temp_config) -> None:
    store = _store(temp_config)

    # The GUI PUTs the whole array with `enabled` flags.
    payload = tools_router.ToolSettings(
        tools=[{"name": "litellm_delete_key", "enabled": False}]
    )
    result = await tools_router.put_tools(payload, store)

    assert result["status"] == "ok"
    assert result["enabled_count"] == len(TOOL_REGISTRY) - 1
    disabled = {t["name"] for t in result["tools"] if not t["enabled"]}
    assert "litellm_delete_key" in disabled

    # Persisted to disk under the tools section.
    on_disk = json.loads(temp_config.read_text("utf-8"))
    assert "litellm_delete_key" in on_disk["tools"]["disabled_tools"]


async def test_put_tools_accepts_disabled_sets_directly(temp_config) -> None:
    store = _store(temp_config)
    payload = tools_router.ToolSettings(disabled_categories=["chat"])
    result = await tools_router.put_tools(payload, store)

    disabled = {t["name"] for t in result["tools"] if not t["enabled"]}
    chat_tools = {s.name for s in TOOL_REGISTRY if s.category.value == "chat"}
    assert chat_tools <= disabled


async def test_apply_to_runtime_writes_child_env(temp_config) -> None:
    """apply_to_runtime must push switches into mcp_server.env for the child."""
    status = await tools_router.apply_to_runtime(
        {"disabled_tools": ["litellm_delete_team"], "readonly": True}
    )
    assert status in {"ok", "partial"}

    on_disk = json.loads(temp_config.read_text("utf-8"))
    env = on_disk["mcp_server"]["env"]
    assert env["LITELLM_MCP_DISABLED_TOOLS"] == "litellm_delete_team"
    assert env["LITELLM_MCP_READONLY"] == "true"
