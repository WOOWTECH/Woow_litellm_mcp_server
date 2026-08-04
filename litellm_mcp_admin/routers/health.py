"""Dashboard health payload.

The shape below is a hard contract with the shared React SPA — keep the keys
even when a value is unknown. The LiteLLM branch of ``Dashboard.jsx`` reads
``target_app`` (gateway), ``item_count`` (registered models) and ``db_name``
(reused as the DB-readiness slot).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["health"])


async def _probe_litellm() -> dict[str, Any]:
    # Read the same `connection` section the GUI writes, so the dashboard
    # reflects the configured gateway rather than a stale environment variable.
    try:
        from mcp_admin_core.config import get_config_store

        connection = await get_config_store().get("connection", {})
    except Exception:  # noqa: BLE001 — core absent in unit-test contexts
        connection = {}

    base = (connection.get("litellm_mcp_base_url") or "http://localhost:4000").rstrip("/")
    master_key = connection.get("litellm_mcp_master_key", "")
    headers = {"Authorization": f"Bearer {master_key}"} if master_key else {}

    try:
        async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
            readiness = await client.get(f"{base}/health/readiness")
            readiness.raise_for_status()
            ready = readiness.json()
    except Exception as exc:  # noqa: BLE001 — surfaced to the dashboard, not raised
        return {"healthy": False, "url": base, "error": str(exc)[:200],
                "version": None, "db": None, "model_count": 0}

    ready = ready if isinstance(ready, dict) else {}

    # Best-effort model count — never let it fail the health probe.
    model_count = 0
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
            models = await client.get(f"{base}/v1/models")
            if models.status_code < 400:
                data = models.json().get("data", [])
                model_count = len(data) if isinstance(data, list) else 0
    except Exception:  # noqa: BLE001
        pass

    return {
        "healthy": True,
        "url": base,
        "error": None,
        "version": ready.get("litellm_version") or ready.get("version"),
        "status": ready.get("status", "connected"),
        "db": ready.get("db"),
        "model_count": model_count,
    }


@router.get("")
async def health() -> dict[str, Any]:
    """Aggregate status for the dashboard: gateway, MCP subprocess and proxy."""
    target = await _probe_litellm()

    try:
        from mcp_admin_core.process import get_process_manager

        # McpProcessManager.status() is a coroutine in mcp_admin_core.
        status = await get_process_manager().status()
    except Exception:  # noqa: BLE001 — core absent in unit-test contexts
        status = {}

    running = bool(status.get("running"))
    return {
        "app_type": "litellm",
        "overall_status": "ok" if target["healthy"] and running else "degraded",
        "mcp_server": {
            "healthy": running,
            "pod_name": f"pid={status.get('pid')}",
            "restart_count": status.get("restart_count", 0),
        },
        "target_app": target,
        "proxy": {"healthy": True, "pod_name": "built-in reverse proxy"},
        "version": target.get("version"),
        # The Dashboard's DB card shows LiteLLM's readiness DB status.
        "db_name": target.get("db") or "unknown",
        "item_count": target.get("model_count", 0),
        "namespace": os.environ.get("NAMESPACE", "litellm-mcp"),
    }
