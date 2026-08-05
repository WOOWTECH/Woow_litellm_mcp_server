"""Tool on/off switches — the endpoints the Web GUI drives."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from woow_litellm_mcp_server.gating import ToolGate, _normalize_operations
from woow_litellm_mcp_server.registry import TOOL_REGISTRY, ToolCategory

from ..store import DEFAULT_PERMISSIONS, ToolConfigStore, env_from_tool_settings

router = APIRouter(prefix="/api/tools", tags=["tools"])

# Only names the registry knows may be persisted — an unknown name is inert for
# the gate but pollutes config.json and inflates the counts the API reports.
ALL_TOOL_NAMES: frozenset[str] = frozenset(spec.name for spec in TOOL_REGISTRY)

# A freshly started child needs ~10-14s to import FastMCP and bind its port, so
# "did the restart actually work?" cannot be answered synchronously. Poll until
# it is serving, with a bound, rather than assuming success.
_READY_TIMEOUT_SECONDS = float(os.environ.get("MCP_ADMIN_CHILD_READY_TIMEOUT", "20"))
_READY_POLL_SECONDS = 0.5


async def port_accepts_connections(port: int) -> bool:
    """True when something is listening on the child's loopback port."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=2.0
        )
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001 — closing a probe socket must never fail
        pass
    return True


async def _wait_until_serving(manager: Any, port: int) -> bool:
    """Wait for the child to actually serve, or for it to die trying.

    ``McpProcessManager.start()`` only reports that ``create_subprocess_exec``
    did not raise; a child that exits 300 ms later on a config error still
    "started". Without this poll the API answered "ok" while the connector was
    returning 502.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _READY_TIMEOUT_SECONDS
    while True:
        if not manager.is_running:
            return False  # the child exited — report the truth, not the intent
        if await port_accepts_connections(port):
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(_READY_POLL_SECONDS)


async def apply_to_runtime(settings: dict[str, Any]) -> str:
    """Push the switches into the MCP subprocess and (re)start it.

    ``mcp_admin_core.process`` only forwards the ``connection`` section and
    ``mcp_server.env``, so the switches have to be written into the latter —
    otherwise the GUI toggles while the server keeps serving every tool.

    Returns "ok" (child verified serving), "partial" (saved but not live) or
    "detached" (no core).
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
    # A child that already crashed must be STARTED, not skipped: the old
    # `if manager.is_running` guard left a dead child dead while the endpoint
    # still answered "ok", so re-enabling everything could not recover it.
    if manager.is_running:
        started = await manager.restart()
    else:
        started = await manager.start()
    if not started:
        return "partial"

    port = int(mcp_server.get("port") or 0)
    if not port:
        return "ok" if manager.is_running else "partial"
    return "ok" if await _wait_until_serving(manager, port) else "partial"


def get_store() -> ToolConfigStore:
    return ToolConfigStore(os.environ.get("MCP_ADMIN_CONFIG", "/data/config.json"))


class ToolSettings(BaseModel):
    """Accepts both payload shapes.

    The vendored React GUI (``ToolManager.jsx``) PUTs the whole tool array back
    with ``enabled`` flags; scripts and tests prefer naming the disabled sets
    directly. Supporting both keeps the shared frontend usable unchanged.
    """

    tools: list[dict] | dict[str, bool] | None = Field(None)
    categories: list[dict] | dict[str, bool] | None = Field(None)
    disabled_categories: list[str] | None = Field(None)
    disabled_tools: list[str] | None = Field(None)
    disabled_operations: dict[str, list[str]] | None = Field(None)
    readonly: bool | None = Field(None)

    def to_patch(self) -> dict[str, Any]:
        patch = self.model_dump(exclude_none=True)
        tools = patch.pop("tools", None)
        categories = patch.pop("categories", None)

        if categories is not None:
            # The grouped view carries `category` + `enabled`; the dict form is
            # {category: enabled}. Explicit disabled_categories still wins.
            if isinstance(categories, dict):
                off = [name for name, enabled in categories.items() if not enabled]
            else:
                off = [
                    entry.get("category") or entry.get("name")
                    for entry in categories
                    if isinstance(entry, dict)
                    and (entry.get("category") or entry.get("name"))
                    and not entry.get("enabled", True)
                ]
            patch.setdefault("disabled_categories", [c for c in off if c])

        if tools is None:
            return patch

        disabled: list[str] = []
        disabled_ops: dict[str, list[str]] = {}
        saw_operations = False

        if isinstance(tools, dict):
            disabled = [name for name, enabled in tools.items() if not enabled]
        else:
            for entry in tools:
                if not isinstance(entry, dict) or "name" not in entry:
                    continue
                name = entry["name"]
                if not entry.get("enabled", True):
                    disabled.append(name)
                operations = entry.get("operations")
                if isinstance(operations, list):
                    saw_operations = True
                    off_ops = [
                        op["name"]
                        for op in operations
                        if isinstance(op, dict)
                        and "name" in op
                        and not op.get("enabled", True)
                    ]
                    if off_ops:
                        disabled_ops[name] = off_ops

        # The GUI always posts the complete array, so this is authoritative.
        patch["disabled_tools"] = disabled
        if saw_operations:
            # ...and that array carries every operation flag too. Dropping them
            # here silently reverted whatever the operator switched off at the
            # operation level, because the store then kept the old value.
            patch.setdefault("disabled_operations", disabled_ops)
        return patch


def _gate_from(settings: dict[str, Any]) -> ToolGate:
    return ToolGate(
        disabled_categories=settings.get("disabled_categories", []),
        disabled_tools=settings.get("disabled_tools", []),
        disabled_operations=settings.get("disabled_operations", {}),
        readonly=settings.get("readonly", False),
    )


def _operation_switches(value: Any) -> tuple[dict[str, set[str]], set[str]]:
    """Explicit operation switches, from EITHER stored shape.

    ``disabled_operations`` is contractually allowed to be the mapping form
    ``{tool: [op, ...]}`` the GUI writes *or* the flat ``["tool:op", "op"]``
    form — ``store._as_operations`` deliberately preserves the latter and
    ``gating._normalize_operations`` accepts both. This renderer used to call
    ``.get()`` on the raw value, so a config holding the flat form made GET and
    PUT ``/api/tools`` answer 500 (``'list' object has no attribute 'get'``)
    and the Tools page could not be opened at all.

    Returns ``(per_tool, global_ops)``. Only the *explicit* switches are
    reported: ``readonly`` deliberately does NOT feed into these checkboxes,
    because the GUI posts the rendered flags straight back and a read-only
    render would then persist every mutating operation as switched off for
    good.
    """
    per_tool: dict[str, set[str]] = {}
    global_ops: set[str] = set()
    for entry in _normalize_operations(value):
        tool, _, operation = entry.partition(":")
        if operation:
            per_tool.setdefault(tool, set()).add(operation)
        elif tool:
            global_ops.add(tool)
    return per_tool, global_ops


def _view(settings: dict[str, Any]) -> dict[str, Any]:
    """Render the registry plus current switch state for the GUI."""
    gate = _gate_from(settings)
    per_tool_ops, global_ops = _operation_switches(settings.get("disabled_operations"))

    def _op_enabled(tool: str, operation: str) -> bool:
        return operation not in per_tool_ops.get(tool, ()) and operation not in global_ops

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
                            {"name": op, "enabled": _op_enabled(s.name, op)}
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
                {"name": op, "enabled": _op_enabled(spec.name, op)}
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


def _reconcile_permissions(
    current: dict[str, Any], disabled: list[str]
) -> dict[str, Any]:
    """Keep ``tools.permissions`` in step with the switches on this page.

    The two pages used to persist two independent representations: /tools wrote
    ``disabled_tools`` and /permissions recomputed that same key from a stale
    allow/deny blob, so the next save on /permissions silently re-enabled every
    tool switched off here — including the destructive ones. Mirroring the
    effective state into the blob means /permissions renders reality.
    """
    permissions = dict(current.get("permissions") or DEFAULT_PERMISSIONS)
    permissions["denied_tools"] = sorted(disabled)
    allowed = permissions.get("allowed_tools")
    if isinstance(allowed, list) and "*" not in allowed:
        # A real allowlist must name exactly what stays on, or the next save on
        # /permissions would derive a different set from it.
        permissions["allowed_tools"] = sorted(ALL_TOOL_NAMES - set(disabled))
    return permissions


@router.put("")
async def put_tools(
    settings: ToolSettings, store: ToolConfigStore = Depends(get_store)
) -> dict[str, Any]:
    """Persist the switches the operator changed, then make them take effect.

    Only the fields present in the request are touched, so the GUI can send
    a single toggle without restating the whole configuration.
    """
    patch = settings.to_patch()

    unknown: list[str] = []
    if "disabled_tools" in patch:
        requested = list(patch["disabled_tools"])
        unknown = sorted({n for n in requested if n not in ALL_TOOL_NAMES})
        known = sorted({n for n in requested if n in ALL_TOOL_NAMES})
        patch["disabled_tools"] = known
        patch["permissions"] = _reconcile_permissions(store.load(), known)

    saved = store.save(patch)
    status = await apply_to_runtime(saved)
    return {**_view(saved), "status": status, "unknown_tools": unknown}
