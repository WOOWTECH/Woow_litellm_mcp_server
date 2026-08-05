"""Dashboard health payload.

The shape below is a hard contract with the shared React SPA — keep the keys
even when a value is unknown. The LiteLLM branch of ``Dashboard.jsx`` reads
``target_app.healthy`` / ``.url`` / ``.error`` (gateway card and error banner),
``target_app.model_count`` (Models card, ``null`` renders as "N/A") and
``target_app.db`` (Database card), plus ``mcp_server`` and ``proxy`` for the
other two status cards.

Top-level ``db_name`` / ``item_count`` / ``overall_status`` are compatibility
aliases for the emqx/n8n/odoo branches that share this SPA; nothing in the
LiteLLM Dashboard renders them. Keep them populated, do not trust them as the
contract.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter

from .tools import port_accepts_connections

router = APIRouter(prefix="/api/health", tags=["health"])


async def _readiness(base: str) -> dict[str, Any]:
    """Version/DB detail from LiteLLM's *unauthenticated* readiness endpoint.

    Detail only. It can never decide ``healthy``: LiteLLM answers it without
    checking the Bearer token, which is exactly why the dashboard used to show
    three green cards with a rotated master key.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base}/health/readiness")
        body = response.json() if response.status_code < 400 else {}
    except Exception:  # noqa: BLE001 — detail only, never fatal
        return {}
    return body if isinstance(body, dict) else {}


async def _probe_litellm() -> dict[str, Any]:
    # Read the same `connection` section the GUI writes, so the dashboard
    # reflects the configured gateway rather than a stale environment variable.
    try:
        from mcp_admin_core.config import get_config_store

        connection = await get_config_store().get("connection", {})
    except Exception:  # noqa: BLE001 — core absent in unit-test contexts
        connection = {}

    connection = connection or {}
    base = (connection.get("litellm_mcp_base_url") or "http://localhost:4000").rstrip("/")
    master_key = connection.get("litellm_mcp_master_key", "")
    headers = {"Authorization": f"Bearer {master_key}"} if master_key else {}

    # model_count is None (not 0) whenever it could not be established, so the
    # SPA prints "N/A" instead of a "0" that reads as "no models configured".
    result: dict[str, Any] = {
        "healthy": False,
        "url": base,
        "error": None,
        "auth_ok": None,
        "version": None,
        "status": None,
        "db": None,
        "model_count": None,
    }

    # The credential-carrying call decides health. /health/readiness is
    # unauthenticated and therefore cannot detect the single most likely
    # misconfiguration: a wrong, rotated or missing master key.
    try:
        async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
            models = await client.get(f"{base}/v1/models")
    except Exception as exc:  # noqa: BLE001 — surfaced to the dashboard, not raised
        result["error"] = f"Cannot reach LiteLLM at {base}: {exc}"[:200]
        return result

    ready = await _readiness(base)
    result["version"] = ready.get("litellm_version") or ready.get("version")
    result["status"] = ready.get("status")
    result["db"] = ready.get("db")

    if models.status_code in (401, 403):
        result["auth_ok"] = False
        result["error"] = (
            f"LiteLLM rejected the configured master key (HTTP {models.status_code})"
            if master_key
            else f"No LiteLLM master key configured (HTTP {models.status_code})"
        )
        return result
    if models.status_code >= 400:
        result["error"] = f"LiteLLM returned HTTP {models.status_code} for /v1/models"
        return result

    try:
        data = models.json().get("data", [])
    except Exception:  # noqa: BLE001
        data = None
    result["model_count"] = len(data) if isinstance(data, list) else None
    result["auth_ok"] = True
    result["healthy"] = True
    result["status"] = ready.get("status", "connected")
    return result


async def _probe_proxy(mcp_port: int) -> dict[str, Any]:
    """Real state of the built-in MCP reverse proxy.

    This card used to be the literal ``{"healthy": True, ...}``, so it stayed
    green while ``mcp_admin_core.proxy`` 403'd every ``/private_{token}/…``
    request for want of a token — i.e. exactly when the claude.ai connector was
    dead.
    """
    try:
        from mcp_admin_core.config import get_config_store

        token = await get_config_store().get("mcp_auth_token", "") or ""
    except Exception:  # noqa: BLE001 — core absent in unit-test contexts
        token = ""

    if not token:
        return {
            "healthy": False,
            "pod_name": "no MCP auth token — /private_…/mcp/ returns 403",
            "token_configured": False,
            "upstream_reachable": None,
            "error": "No mcp_auth_token configured; every connector request is rejected.",
        }

    reachable = await port_accepts_connections(mcp_port) if mcp_port else None
    if reachable is False:
        return {
            "healthy": False,
            "pod_name": f"upstream 127.0.0.1:{mcp_port} refused",
            "token_configured": True,
            "upstream_reachable": False,
            "error": f"MCP child is not listening on 127.0.0.1:{mcp_port}.",
        }
    return {
        "healthy": True,
        "pod_name": f"built-in reverse proxy → 127.0.0.1:{mcp_port}"
        if mcp_port
        else "built-in reverse proxy",
        "token_configured": True,
        "upstream_reachable": reachable,
        "error": None,
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

    port = int(status.get("port") or 0)
    proxy = await _probe_proxy(port)

    # A live pid is not the same as a serving child: the process may still be
    # importing, or already dead but not yet reaped. Trust the port.
    process_alive = bool(status.get("running"))
    serving = await port_accepts_connections(port) if (process_alive and port) else False
    running = process_alive and (serving or not port)

    return {
        "app_type": "litellm",
        "overall_status": "ok"
        if target["healthy"] and running and proxy["healthy"]
        else "degraded",
        "mcp_server": {
            "healthy": running,
            "pod_name": f"pid={status.get('pid')}"
            + ("" if running else " · not serving"),
            "restart_count": status.get("restart_count", 0),
            "exit_code": status.get("exit_code"),
            "port": port or None,
        },
        "target_app": target,
        "proxy": proxy,
        "version": target.get("version"),
        # Compatibility aliases (see module docstring) — the LiteLLM Dashboard
        # reads target_app.db / target_app.model_count instead.
        "db_name": target.get("db") or "unknown",
        "item_count": target.get("model_count"),
        "namespace": os.environ.get("NAMESPACE", "litellm-mcp"),
    }
