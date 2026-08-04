"""Three-level gating: category, tool, operation — plus read-only mode."""

from __future__ import annotations

from woow_litellm_mcp_server.gating import ToolGate
from woow_litellm_mcp_server.registry import (
    OP_READ,
    TOOL_REGISTRY,
    TOOLS_BY_NAME,
    ToolCategory,
)

from .conftest import build_gate, register_all


def _dangerous_names() -> set[str]:
    return {s.name for s in TOOL_REGISTRY if s.dangerous}


def test_default_gate_enables_everything(all_enabled_gate: ToolGate) -> None:
    enabled = set(all_enabled_gate.enabled_tool_names())
    assert enabled == {s.name for s in TOOL_REGISTRY}


def test_disable_category_drops_the_whole_family() -> None:
    gate = build_gate(disabled_categories=["keys"])
    enabled = set(gate.enabled_tool_names())
    key_tools = {s.name for s in TOOL_REGISTRY if s.category is ToolCategory.KEYS}
    assert key_tools, "sanity: there are key tools"
    assert not (enabled & key_tools)
    # Other categories are untouched.
    assert "litellm_list_models" in enabled


def test_disable_single_tool() -> None:
    gate = build_gate(disabled_tools=["litellm_delete_key"])
    assert not gate.is_tool_enabled("litellm_delete_key")
    # Its siblings survive.
    assert gate.is_tool_enabled("litellm_generate_key")


def test_readonly_drops_every_dangerous_tool() -> None:
    gate = build_gate(readonly=True)
    enabled = set(gate.enabled_tool_names())
    dangerous = _dangerous_names()
    assert dangerous, "sanity: the surface has dangerous tools"
    assert not (enabled & dangerous)
    # Read tools remain.
    assert "litellm_list_models" in enabled
    assert "litellm_health" in enabled


def test_readonly_registration_never_installs_dangerous_tools() -> None:
    """The gate must stop dangerous tools from ever reaching FastMCP."""
    mcp = register_all(build_gate(readonly=True))
    installed = set(mcp.tools)
    assert not (installed & _dangerous_names())


def test_operation_gate_bare_op() -> None:
    gate = build_gate(disabled_operations=["delete"])
    # A delete tool's delete op is filtered out of its allowed operations.
    assert "delete" not in gate.allowed_operations("litellm_delete_key")


def test_operation_gate_tool_scoped_op() -> None:
    gate = build_gate(disabled_operations=["litellm_generate_key:create"])
    assert "create" not in gate.allowed_operations("litellm_generate_key")
    # A different create tool is unaffected.
    assert "create" in gate.allowed_operations("litellm_create_team")


def test_operation_gate_accepts_dict_form() -> None:
    """The admin GUI passes {tool: [ops]}; the gate must accept that too."""
    gate = ToolGate(disabled_operations={"litellm_update_key": ["update"]})
    assert "update" not in gate.allowed_operations("litellm_update_key")


def test_readonly_leaves_only_read_operations() -> None:
    gate = build_gate(readonly=True)
    for spec in TOOL_REGISTRY:
        if not gate.is_tool_enabled(spec.name):
            continue
        allowed = gate.allowed_operations(spec.name)
        assert all(op == OP_READ for op in allowed), spec.name


def test_unknown_tool_is_never_enabled() -> None:
    gate = build_gate()
    assert not gate.is_tool_enabled("litellm_does_not_exist")
    assert "litellm_does_not_exist" not in TOOLS_BY_NAME
