"""LiteLLM connection settings and the tool-permission policy.

Keys written into the ``connection`` section are upper-cased by
``mcp_admin_core.process`` and injected into the MCP subprocess environment, so
they must match what ``woow_litellm_mcp_server.settings.Settings`` reads —
``litellm_mcp_base_url`` becomes ``LITELLM_MCP_BASE_URL`` and
``litellm_mcp_master_key`` becomes ``LITELLM_MCP_MASTER_KEY``.
``tests/test_connection_wiring.py`` keeps the two ends in step.

LiteLLM delta vs. the EMQX reference: authentication is a *single* Bearer
master key (no key/secret pair), and the connection probe hits
``GET {base}/health/readiness`` instead of ``/api/v5/nodes``.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from woow_litellm_mcp_server.registry import TOOL_REGISTRY

router = APIRouter(prefix="/api/config", tags=["config"])

CONNECTION_KEYS = (
    "litellm_mcp_base_url",
    "litellm_mcp_master_key",
)

DEFAULT_PERMISSIONS: dict[str, Any] = {"allowed_tools": ["*"], "denied_tools": []}


class ConnectionSettings(BaseModel):
    litellm_mcp_base_url: str = Field(
        description="LiteLLM gateway base URL, e.g. http://litellm:4000"
    )
    litellm_mcp_master_key: str = Field(
        default="",
        description="LiteLLM master key (sk-…). Sent as a Bearer token.",
    )
    restart: bool = Field(True, description="Restart the MCP server after saving.")


class PermissionPolicy(BaseModel):
    """What the PermissionEditor page saves."""

    permissions: dict[str, Any]


async def _probe(base_url: str, master_key: str) -> dict[str, Any]:
    """Ask LiteLLM whether it is ready. Shape matches ConnectionConfig.jsx."""
    base = (base_url or "").rstrip("/")
    if not base:
        return {"success": False, "ok": False, "message": "No LiteLLM URL configured yet."}

    headers = {"Authorization": f"Bearer {master_key}"} if master_key else {}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            response = await client.get(f"{base}/health/readiness")
    except Exception as exc:  # noqa: BLE001 — shown to the operator, not raised
        return {"success": False, "ok": False,
                "message": f"Cannot reach LiteLLM at {base}: {exc}"}

    if response.status_code == 401:
        return {"success": False, "ok": False,
                "message": "LiteLLM rejected the master key (401)."}
    if response.status_code >= 400:
        return {"success": False, "ok": False,
                "message": f"LiteLLM returned HTTP {response.status_code}."}

    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    version = body.get("litellm_version") or body.get("version")
    db = body.get("db")
    status = body.get("status", "connected")
    return {
        "success": True,
        "ok": True,
        "message": f"Connected to LiteLLM {version or ''} · status={status}"
                   + (f" · db={db}" if db else ""),
        "version": version,
        "db": db,
        "status": status,
    }


@router.get("")
async def get_config() -> dict[str, Any]:
    from mcp_admin_core.config import get_config_store

    store = get_config_store()
    connection = await store.get("connection", {}) or {}
    master_key = connection.get("litellm_mcp_master_key", "")
    tools = await store.get("tools", {}) or {}

    return {
        "app_type": "litellm",
        "litellm_mcp_base_url": connection.get("litellm_mcp_base_url", ""),
        # Never echo the master key back to the browser.
        "litellm_mcp_master_key_masked": "********" if master_key else "",
        "permissions": tools.get("permissions") or DEFAULT_PERMISSIONS,
    }


@router.put("/connection")
async def put_connection(payload: ConnectionSettings) -> dict[str, Any]:
    from mcp_admin_core.config import get_config_store
    from mcp_admin_core.process import get_process_manager

    store = get_config_store()
    await store.reload()
    current = await store.get("connection", {}) or {}

    updates = {key: getattr(payload, key) for key in CONNECTION_KEYS}
    # An untouched master-key field arrives as "", which must not wipe the
    # stored one.
    if not updates["litellm_mcp_master_key"]:
        updates["litellm_mcp_master_key"] = current.get("litellm_mcp_master_key", "")
    await store.patch("connection", updates)

    status = "ok"
    if payload.restart:
        manager = get_process_manager()
        if manager.is_running and not await manager.restart():
            # Saved but not yet live — say so rather than failing the request.
            status = "partial"
    return {"status": status, "success": True}


@router.post("/test")
async def test_connection(payload: ConnectionSettings | None = None) -> dict[str, Any]:
    """Verify credentials against LiteLLM — the posted ones, or the saved ones.

    ConnectionConfig.jsx calls this with no body, so saved values are the
    normal path.
    """
    if payload is not None and payload.litellm_mcp_base_url:
        master_key = payload.litellm_mcp_master_key
        if not master_key:
            from mcp_admin_core.config import get_config_store

            saved = await get_config_store().get("connection", {}) or {}
            master_key = saved.get("litellm_mcp_master_key", "")
        return await _probe(payload.litellm_mcp_base_url, master_key)

    from mcp_admin_core.config import get_config_store

    connection = await get_config_store().get("connection", {}) or {}
    return await _probe(
        connection.get("litellm_mcp_base_url", ""),
        connection.get("litellm_mcp_master_key", ""),
    )


@router.put("/permissions")
async def put_permissions(payload: PermissionPolicy) -> dict[str, Any]:
    """Save the tool-permission policy and translate it into switches.

    The editor speaks allow/deny lists; the MCP server speaks disabled sets.
    ``allowed_tools: ["*"]`` means "no allow-list restriction", otherwise every
    tool outside the list is switched off. ``denied_tools`` always wins.
    """
    from mcp_admin_core.config import get_config_store

    from .tools import apply_to_runtime

    policy = payload.permissions or {}
    allowed = policy.get("allowed_tools") or ["*"]
    denied = set(policy.get("denied_tools") or [])

    every = [spec.name for spec in TOOL_REGISTRY]
    unknown = sorted(
        {t for t in list(allowed) + list(denied) if t != "*" and t not in every}
    )

    disabled = set(denied)
    if "*" not in allowed:
        disabled |= {name for name in every if name not in set(allowed)}

    store = get_config_store()
    await store.reload()
    tools = await store.get("tools", {}) or {}
    merged = {**tools, "permissions": policy, "disabled_tools": sorted(disabled)}
    await store.patch("tools", merged)

    status = await apply_to_runtime(merged)
    return {
        "status": status,
        "success": True,
        "disabled_count": len(disabled),
        "unknown_tools": unknown,
    }
