"""Tool on/off switches — the endpoints the Web GUI drives."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from woow_litellm_mcp_server.gating import ToolGate
from woow_litellm_mcp_server.registry import TOOL_REGISTRY, ToolCategory

from ..store import ToolConfigStore, env_from_tool_settings

router = APIRouter(prefix="/api/tools", tags=["tools"])


async def apply_to_runtime(settings: dict[str, Any]) -> str:
    """Push the switches into the MCP subprocess and restart it.

    ``mcp_admin_core.process`` only forwards the ``connection`` section and
    ``mcp_server.env``, so the switches have to be written into the latter —
    otherwise the GUI toggles while the server keeps serving every tool.

    Returns "ok", "partial" (saved but not yet live) or "detached" (no core).
    """
    try:
        from mcp_admin_core.config import get_config_store
        from mcp_admin_core.process import get_process_manager
    except Exception:  # noqa: BLE001 — unit tests run without the core
        return "detached"

    store = get_config_store()
    # The core store caches the whole file in memory; our own writer just
    # touched it, so drop the cache before patching or the tools section
    # gets clobbered by a stale copy.
    await store.reload()
    mcp_server = await store.get("mcp_server", {}) or {}
    env = {**(mcp_server.get("env") or {}), **env_from_tool_settings(settings)}
    await store.patch("mcp_server", {**mcp_server, "env": env})

    manager = get_process_manager()
    if manager.is_running and not await manager.restart():
        return "partial"
    return "ok"


def get_store() -> ToolConfigStore:
    return ToolConfigStore(os.environ.get("MCP_ADMIN_CONFIG", "/data/config.json"))


class ToolSettings(BaseModel):
    """Accepts both payload shapes.

    The vendored React GUI (``ToolManager.jsx``) PUTs the whole tool array back
    with ``enabled`` flags; scripts and tests prefer naming the disabled sets
    directly. Supporting both keeps the shared frontend usable unchanged.
    """

    tools: list[dict] | dict[str, bool] | None = Field(None)
    disabled_categories: list[str] | None = Field(None)
    disabled_tools: list[str] | None = Field(None)
    disabled_operations: dict[str, list[str]] | None = Field(None)
    readonly: bool | None = Field(None)

    def to_patch(self) -> dict[str, Any]:
        patch = self.model_dump(exclude_none=True)
        tools = patch.pop("tools", None)
        if tools is None:
            return patch

        if isinstance(tools, dict):
            disabled = [name for name, enabled in tools.items() if not enabled]
        else:
            disabled = [
                entry["name"]
                for entry in tools
                if isinstance(entry, dict)
                and "name" in entry
                and not entry.get("enabled", True)
            ]
        # The GUI always posts the complete array, so this is authoritative.
        patch["disabled_tools"] = disabled
        return patch


def _gate_from(settings: dict[str, Any]) -> ToolGate:
    return ToolGate(
        disabled_categories=settings.get("disabled_categories", []),
        disabled_tools=settings.get("disabled_tools", []),
        disabled_operations=settings.get("disabled_operations", {}),
        readonly=settings.get("readonly", False),
    )


def _view(settings: dict[str, Any]) -> dict[str, Any]:
    """Render the registry plus current switch state for the GUI."""
    gate = _gate_from(settings)
    disabled_ops = settings.get("disabled_operations", {})

    groups = []
    for category in ToolCategory:
        specs = [s for s in TOOL_REGISTRY if s.category is category]
        if not specs:
            continue
        groups.append(
            {
                "category": category.value,
                "enabled": category.value not in settings.get("disabled_categories", []),
                "tools": [
                    {
                        "name": s.name,
                        "description": s.description,
                        "dangerous": s.dangerous,
                        "enabled": gate.is_tool_enabled(s.name),
                        "operations": [
                            {
                                "name": op,
                                "enabled": op not in disabled_ops.get(s.name, []),
                            }
                            for op in s.operations
                        ],
                    }
                    for s in specs
                ],
            }
        )

    # Flat list first: ToolManager.jsx reads `tools` and groups by `category`.
    flat = [
        {
            "name": spec.name,
            "category": spec.category.value,
            "description": spec.description,
            "dangerous": spec.dangerous,
            "enabled": gate.is_tool_enabled(spec.name),
            "operations": [
                {"name": op, "enabled": op not in disabled_ops.get(spec.name, [])}
                for op in spec.operations
            ],
        }
        for spec in TOOL_REGISTRY
    ]

    return {
        "tools": flat,
        "categories": groups,
        "total": len(TOOL_REGISTRY),
        "enabled_count": len(gate.enabled_tools()),
        **{k: settings.get(k) for k in
           ("disabled_categories", "disabled_tools", "disabled_operations", "readonly")},
    }


@router.get("")
def get_tools(store: ToolConfigStore = Depends(get_store)) -> dict[str, Any]:
    """Every tool, grouped by category, with its current switch state."""
    return _view(store.load())


@router.put("")
async def put_tools(
    settings: ToolSettings, store: ToolConfigStore = Depends(get_store)
) -> dict[str, Any]:
    """Persist the switches the operator changed, then make them take effect.

    Only the fields present in the request are touched, so the GUI can send
    a single toggle without restating the whole configuration.
    """
    saved = store.save(settings.to_patch())
    status = await apply_to_runtime(saved)
    return {**_view(saved), "status": status}
