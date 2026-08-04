"""MCP proxy token: generate, preview, rotate.

Generation and rotation are deliberately separate — previewing a token must
not invalidate the one AI clients are currently using.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

_KEEP_HISTORY = 5


def _mask(token: str) -> str:
    return f"{token[:4]}…{token[-4:]}" if len(token) > 8 else "…"


@router.get("")
async def get_token() -> dict[str, Any]:
    from mcp_admin_core.config import get_config_store

    store = get_config_store()
    token = await store.get("mcp_auth_token", "")
    return {
        "masked": _mask(token) if token else "",
        "configured": bool(token),
        "history": await store.get("token_history", []),
    }


@router.post("/generate")
async def generate_token() -> dict[str, Any]:
    """Preview a new token. Nothing is persisted until /rotate."""
    return {"token": secrets.token_urlsafe(32)}


@router.post("/rotate")
async def rotate_token() -> dict[str, Any]:
    """Generate, persist and activate a new token in one step."""
    from mcp_admin_core.config import get_config_store
    from mcp_admin_core.process import get_process_manager

    store = get_config_store()
    previous = await store.get("mcp_auth_token", "")
    token = secrets.token_urlsafe(32)

    history = await store.get("token_history", [])
    if previous:
        history = ([{"masked": _mask(previous)}] + list(history))[:_KEEP_HISTORY]

    await store.put("mcp_auth_token", token)
    await store.put("token_history", history)

    manager = get_process_manager()
    status = "ok"
    if manager.is_running and not await manager.restart():
        status = "partial"

    return {"token": token, "masked": _mask(token), "status": status}
