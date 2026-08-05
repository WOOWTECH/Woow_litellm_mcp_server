"""The /api/tools GET/PUT contract the Web GUI drives, and apply_to_runtime.

Also covers the two cross-page contracts that live in ``litellm_mcp_admin.store``:
the JSON encoding of the child's gating environment, and the single secret-mask
helper every read path must go through.
"""

from __future__ import annotations

import json

import pytest

from litellm_mcp_admin.routers import config as config_router
from litellm_mcp_admin.routers import tokens as tokens_router
from litellm_mcp_admin.routers import tools as tools_router
from litellm_mcp_admin.store import ToolConfigStore, env_from_tool_settings, mask_secret
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

    # No MCP command is configured in the temp config, so the child cannot be
    # verified as serving: "partial" is the honest answer. It must never be a
    # blanket "ok" — that is what hid a child that had died on startup.
    assert result["status"] in {"ok", "partial", "detached"}
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


async def test_put_tools_keeps_operation_switches(temp_config) -> None:
    """The GUI posts operation flags inside each tool entry; they must persist."""
    store = _store(temp_config)
    payload = tools_router.ToolSettings(
        tools=[
            {
                "name": "litellm_list_keys",
                "enabled": True,
                "operations": [
                    {"name": "list", "enabled": True},
                    {"name": "info", "enabled": False},
                ],
            }
        ]
    )
    await tools_router.put_tools(payload, store)

    on_disk = json.loads(temp_config.read_text("utf-8"))
    assert on_disk["tools"]["disabled_operations"] == {"litellm_list_keys": ["info"]}


async def test_put_tools_drops_unknown_tool_names(temp_config) -> None:
    """An unknown name is inert for the gate; it must not reach config.json."""
    store = _store(temp_config)
    payload = tools_router.ToolSettings(
        disabled_tools=["litellm_delete_key", "not_a_real_tool"]
    )
    result = await tools_router.put_tools(payload, store)

    assert result["unknown_tools"] == ["not_a_real_tool"]
    on_disk = json.loads(temp_config.read_text("utf-8"))
    assert on_disk["tools"]["disabled_tools"] == ["litellm_delete_key"]


async def test_put_tools_mirrors_into_permissions(temp_config) -> None:
    """Both pages must agree, or the next save on /permissions re-enables tools."""
    store = _store(temp_config)
    await tools_router.put_tools(
        tools_router.ToolSettings(disabled_tools=["litellm_delete_key"]), store
    )

    on_disk = json.loads(temp_config.read_text("utf-8"))
    assert on_disk["tools"]["permissions"]["denied_tools"] == ["litellm_delete_key"]


def test_permissions_empty_allowlist_fails_closed() -> None:
    """``allowed_tools: []`` means "allow nothing", not "allow everything"."""
    everything = config_router._derive_disabled({"allowed_tools": [], "denied_tools": []})
    assert everything == set(config_router.ALL_TOOL_NAMES)

    # ``["*"]`` and a missing key both mean "no allowlist restriction".
    assert config_router._derive_disabled({"allowed_tools": ["*"]}) == set()
    assert config_router._derive_disabled({}) == set()


async def test_saving_permissions_keeps_tools_page_switches(temp_config) -> None:
    """The permissions page must merge with, never clobber, disabled_tools.

    The store is written directly here on purpose: that is the shape a config
    file has when the tools were switched off before ``tools.permissions``
    existed. Recomputing ``disabled_tools`` purely from the policy blob
    re-enabled every one of them — including litellm_delete_key — on the first
    save from the permissions page.
    """
    store = _store(temp_config)
    store.save({"disabled_tools": ["litellm_delete_key"], "readonly": True})

    await config_router.put_permissions(
        config_router.PermissionPolicy(
            permissions={"allowed_tools": ["*"], "denied_tools": ["litellm_delete_team"]}
        )
    )

    on_disk = json.loads(temp_config.read_text("utf-8"))
    tools = on_disk["tools"]
    assert set(tools["disabled_tools"]) == {"litellm_delete_key", "litellm_delete_team"}
    # ...and the other keys of the section survive the patch.
    assert tools["readonly"] is True


async def test_apply_to_runtime_writes_child_env(temp_config) -> None:
    """apply_to_runtime must push switches into mcp_server.env for the child."""
    status = await tools_router.apply_to_runtime(
        {"disabled_tools": ["litellm_delete_team"], "readonly": True}
    )
    assert status in {"ok", "partial", "detached"}

    on_disk = json.loads(temp_config.read_text("utf-8"))
    env = on_disk["mcp_server"]["env"]
    # JSON, not CSV: the CSV form raised SettingsError in the child at import.
    assert env["LITELLM_MCP_DISABLED_TOOLS"] == '["litellm_delete_team"]'
    assert env["LITELLM_MCP_READONLY"] == "true"


@pytest.mark.parametrize(
    "stored, expected",
    [
        ({"disabled_tools": []}, "[]"),
        ({"disabled_tools": "litellm_delete_key"}, '["litellm_delete_key"]'),
        ({}, "[]"),
    ],
)
def test_env_encoding_is_always_valid_json(stored, expected) -> None:
    env = env_from_tool_settings(stored)
    assert env["LITELLM_MCP_DISABLED_TOOLS"] == expected
    json.loads(env["LITELLM_MCP_DISABLED_OPERATIONS"])  # never raises


def test_mask_secret_never_leaks_more_than_four_characters() -> None:
    """One helper, one rule — a longer prefix identifies a key in a screenshot."""
    assert mask_secret("sk-placeholder-value-1234") == "sk-p…"
    assert mask_secret("short") == "…"  # 8 chars or fewer: nothing at all
    assert mask_secret("") == ""
    assert mask_secret(None) == ""
    # No trailing fragment, ever.
    assert "1234" not in mask_secret("sk-placeholder-value-1234")


def test_mask_secret_is_the_same_rule_on_both_sides() -> None:
    """The core and product copies must agree, byte for byte in behaviour.

    ``mcp_admin_core.config.mask_secret`` masks what the settings router echoes
    and ``litellm_mcp_admin.store.mask_secret`` masks what the product routers
    echo — and both are compared against on the *write* path to detect "the GUI
    posted the mask back". If they ever drift, a masked value written back
    would stop being recognised and would overwrite the real secret.
    """
    from mcp_admin_core.config import mask_secret as core_mask

    for value in (
        None,
        "",
        "a",
        "12345678",
        "123456789",
        "sk-placeholder-value-1234",
        "tok-placeholder-abcdefghijklmnop",
    ):
        assert mask_secret(value) == core_mask(value), value


def test_tools_view_accepts_the_flat_operation_form(temp_config) -> None:
    """``disabled_operations`` may be stored flat; the page must still render.

    ``store._as_operations`` preserves the legacy ``["tool:op", "op"]`` shape
    and ``gating._normalize_operations`` accepts it, but the renderer used to
    call ``.get()`` on it — so GET/PUT /api/tools answered 500 and the Tools
    page could not be opened for such a config.
    """
    temp_config.write_text(
        json.dumps(
            {"tools": {"disabled_operations": ["litellm_delete_key:delete", "write"]}}
        ),
        "utf-8",
    )
    view = tools_router.get_tools(_store(temp_config))
    flags = {
        tool["name"]: {op["name"]: op["enabled"] for op in tool["operations"]}
        for tool in view["tools"]
    }
    # "tool:op" switches off that one tool's operation...
    assert flags["litellm_delete_key"]["delete"] is False
    # ...a bare "op" switches it off everywhere it appears...
    assert all(ops["write"] is False for ops in flags.values() if "write" in ops)
    # ...and nothing else is touched.
    assert all(ops.get("read", True) is True for ops in flags.values())


def test_token_history_entries_use_the_shared_shape() -> None:
    """{"masked", "rotated_at"} — the SPA renders entry.masked directly."""
    entry = tokens_router._history_entry("tok-placeholder-abcdefgh")
    assert set(entry) == {"masked", "rotated_at"}
    assert entry["masked"] == "tok-…"
    assert entry["rotated_at"].endswith("+00:00")  # ISO-8601 UTC

    # Legacy rows (bare strings, or the other writer's "token_masked") must be
    # normalised, or React is handed a raw object and renders "[object Object]".
    normalised = tokens_router._normalise_history(
        [{"token_masked": "tok-…"}, "abc…", {"masked": "xyz…", "rotated_at": "t"}]
    )
    assert all(set(row) == {"masked", "rotated_at"} for row in normalised)
    assert [row["masked"] for row in normalised] == ["tok-…", "abc…", "xyz…"]


def test_legacy_disabled_key_is_migrated(temp_config) -> None:
    """Old config files stored the set under ``tools.disabled``."""
    temp_config.write_text(
        json.dumps({"tools": {"disabled": ["litellm_delete_key"]}}), "utf-8"
    )
    settings = _store(temp_config).load()
    assert settings["disabled_tools"] == ["litellm_delete_key"]
    assert "disabled" not in settings
