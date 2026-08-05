"""LiteLLM connection settings and the tool-permission policy.

Keys written into the ``connection`` section are upper-cased by
``mcp_admin_core.process`` and injected into the MCP subprocess environment, so
they must match what ``woow_litellm_mcp_server.settings.Settings`` reads —
``litellm_mcp_base_url`` becomes ``LITELLM_MCP_BASE_URL`` and
``litellm_mcp_master_key`` becomes ``LITELLM_MCP_MASTER_KEY``.
``tests/test_connection_wiring.py`` keeps the two ends in step.

LiteLLM delta vs. the EMQX reference: authentication is a *single* Bearer
master key (no key/secret pair), and the connection probe hits the
*authenticated* ``GET {base}/v1/models`` instead of ``/api/v5/nodes``.
``/health/readiness`` is deliberately NOT the probe: LiteLLM serves it without
authentication, so it answers 200 for a garbage master key and the page said
"Connected" while every tool call 401'd.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from woow_litellm_mcp_server.registry import TOOL_REGISTRY

from ..store import DEFAULT_PERMISSIONS, mask_secret

router = APIRouter(prefix="/api/config", tags=["config"])

CONNECTION_KEYS = (
    "litellm_mcp_base_url",
    "litellm_mcp_master_key",
)

ALL_TOOL_NAMES: frozenset[str] = frozenset(spec.name for spec in TOOL_REGISTRY)

__all__ = [
    "router",
    "CONNECTION_KEYS",
    "DEFAULT_PERMISSIONS",  # re-exported: the canonical copy lives in store.py
    "ALL_TOOL_NAMES",
]


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


async def _readiness(base: str) -> dict[str, Any]:
    """Version/DB detail from the unauthenticated readiness endpoint.

    Purely cosmetic — it can never decide success, because LiteLLM answers it
    without checking the Bearer token.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(f"{base}/health/readiness")
        body = response.json() if response.status_code < 400 else {}
    except Exception:  # noqa: BLE001 — detail only, never fatal
        return {}
    return body if isinstance(body, dict) else {}


async def _probe(base_url: str, master_key: str) -> dict[str, Any]:
    """Verify URL *and* master key against LiteLLM. Shape matches ConnectionConfig.jsx.

    The probe hits ``GET {base}/v1/models``, which requires the master key.
    ``/health/readiness`` — the endpoint this used to call — is unauthenticated,
    so a wrong, truncated or entirely missing key still produced a green
    "Connected" banner and the operator only found out when all 38 tools
    started failing with 401.
    """
    base = (base_url or "").rstrip("/")
    if not base:
        return {"success": False, "ok": False, "message": "No LiteLLM URL configured yet."}

    headers = {"Authorization": f"Bearer {master_key}"} if master_key else {}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            response = await client.get(f"{base}/v1/models")
    except Exception as exc:  # noqa: BLE001 — shown to the operator, not raised
        return {"success": False, "ok": False,
                "message": f"Cannot reach LiteLLM at {base}: {exc}"}

    # Reachable but unauthorised is its own diagnosis: the URL is right and the
    # key is not, which is a different fix from "the gateway is down".
    if response.status_code in (401, 403):
        detail = "no master key is configured" if not master_key else "the master key was rejected"
        return {
            "success": False,
            "ok": False,
            "auth_ok": False,
            "message": f"Reached LiteLLM at {base}, but {detail} "
                       f"(HTTP {response.status_code}).",
        }
    if response.status_code >= 400:
        return {"success": False, "ok": False,
                "message": f"LiteLLM returned HTTP {response.status_code} for /v1/models."}

    try:
        models = response.json()
    except Exception:  # noqa: BLE001
        models = {}
    data = models.get("data") if isinstance(models, dict) else None
    model_count = len(data) if isinstance(data, list) else None

    ready = await _readiness(base)
    version = ready.get("litellm_version") or ready.get("version")
    db = ready.get("db")
    status = ready.get("status", "connected")
    return {
        "success": True,
        "ok": True,
        "auth_ok": True,
        "message": f"Connected to LiteLLM {version or ''} · status={status}"
                   + (f" · db={db}" if db else "")
                   + (f" · models={model_count}" if model_count is not None else ""),
        "version": version,
        "db": db,
        "status": status,
        "model_count": model_count,
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
        # Never echo the master key back to the browser — at most four leading
        # characters, so the operator can tell *which* key is stored without the
        # value leaking into a screenshot.
        "litellm_mcp_master_key_masked": mask_secret(master_key),
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
    stored_key = current.get("litellm_mcp_master_key", "")
    # An untouched master-key field arrives as "" — or, if a client echoes the
    # GET payload straight back, as the masked form. Neither may overwrite the
    # real key: doing so kills the live connector on a partial save.
    if (
        not updates["litellm_mcp_master_key"]
        or updates["litellm_mcp_master_key"] == mask_secret(stored_key)
    ):
        updates["litellm_mcp_master_key"] = stored_key
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


def _derive_disabled(policy: dict[str, Any]) -> set[str]:
    """Tools switched off by an allow/deny policy.

    ``allowed_tools`` is an ALLOWLIST. Missing or ``null`` means "no allowlist,
    everything not denied is allowed"; ``["*"]`` says the same explicitly. An
    EMPTY LIST means "allow nothing" and must fail closed — the old
    ``policy.get("allowed_tools") or ["*"]`` treated the falsy ``[]`` as the
    wildcard, so the most natural way to write a lockdown enabled all 38 tools.
    """
    denied = {str(t) for t in (policy.get("denied_tools") or [])}
    disabled = set(denied)

    allowed = policy.get("allowed_tools")
    if allowed is None:  # no allowlist at all
        return disabled
    allowed_set = {str(t) for t in allowed}
    if "*" in allowed_set:
        return disabled
    disabled |= {name for name in ALL_TOOL_NAMES if name not in allowed_set}
    return disabled


@router.put("/permissions")
async def put_permissions(payload: PermissionPolicy) -> dict[str, Any]:
    """Save the tool-permission policy and translate it into switches.

    The editor speaks allow/deny lists; the MCP server speaks disabled sets.
    ``allowed_tools: ["*"]`` (or a missing/``null`` key) means "no allow-list
    restriction", ``[]`` means "allow nothing", otherwise every tool outside the
    list is switched off. ``denied_tools`` always wins.
    """
    from mcp_admin_core.config import get_config_store

    from .tools import apply_to_runtime

    policy = dict(payload.permissions or {})

    raw_allowed = policy.get("allowed_tools")
    raw_denied = policy.get("denied_tools") or []
    unknown = sorted(
        {
            str(t)
            for t in list(raw_allowed or []) + list(raw_denied)
            if str(t) != "*" and str(t) not in ALL_TOOL_NAMES
        }
    )
    # Names the registry does not know are inert for the gate but pollute
    # config.json and the child's env, and they inflated disabled_count. Drop
    # them here and report them; the key stays absent/None if it was.
    if raw_allowed is not None:
        policy["allowed_tools"] = [
            str(t) for t in raw_allowed if str(t) == "*" or str(t) in ALL_TOOL_NAMES
        ]
    policy["denied_tools"] = [str(t) for t in raw_denied if str(t) in ALL_TOOL_NAMES]

    store = get_config_store()
    await store.reload()
    tools = await store.get("tools", {}) or {}

    # Merge, never clobber: whatever is disabled today but was NOT implied by
    # the *previous* policy was switched off on the Tools page. Recomputing
    # disabled_tools purely from this blob silently re-enabled those tools —
    # including litellm_delete_key — the first time anyone saved here.
    previous = tools.get("permissions") or {}
    tools_page_disabled = set(tools.get("disabled_tools") or []) - _derive_disabled(previous)

    disabled = {
        name
        for name in (_derive_disabled(policy) | tools_page_disabled)
        if name in ALL_TOOL_NAMES
    }

    # patch() merges into the stored section, so readonly / disabled_categories
    # / disabled_operations written by the Tools page survive this save.
    merged = await store.patch(
        "tools", {"permissions": policy, "disabled_tools": sorted(disabled)}
    )

    status = await apply_to_runtime(merged)
    return {
        "status": status,
        "success": True,
        "disabled_count": len(disabled),
        "unknown_tools": unknown,
    }
