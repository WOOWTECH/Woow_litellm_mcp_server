"""The admin connection keys must map onto the server's Settings env names.

``mcp_admin_core.process`` upper-cases each key in the ``connection`` section
and injects it into the MCP subprocess environment. Those upper-cased names must
line up with ``Settings`` (``env_prefix="LITELLM_MCP_"``) or the child server
would silently ignore the operator's configuration.
"""

from __future__ import annotations

import json

from litellm_mcp_admin.routers.config import CONNECTION_KEYS
from litellm_mcp_admin.store import env_from_tool_settings
from woow_litellm_mcp_server.settings import Settings

ENV_PREFIX = "LITELLM_MCP_"


def test_connection_keys_uppercase_to_settings_env_names() -> None:
    # base_url + master_key are the two fields the connection section carries.
    assert CONNECTION_KEYS == ("litellm_mcp_base_url", "litellm_mcp_master_key")
    for key in CONNECTION_KEYS:
        assert key.startswith("litellm_mcp_")
        env_name = key.upper()
        assert env_name.startswith(ENV_PREFIX)
        field = env_name[len(ENV_PREFIX):].lower()
        assert field in Settings.model_fields, field


def test_connection_env_actually_loads_into_settings(monkeypatch) -> None:
    monkeypatch.setenv("LITELLM_MCP_BASE_URL", "http://litellm.svc:4000")
    monkeypatch.setenv("LITELLM_MCP_MASTER_KEY", "sk-test-123")
    cfg = Settings()
    assert cfg.base_url == "http://litellm.svc:4000"
    assert cfg.master_key == "sk-test-123"


def test_tool_switch_env_is_json_not_csv() -> None:
    """The writer must emit JSON: pydantic-settings json-decodes these fields."""
    env = env_from_tool_settings(
        {
            "readonly": True,
            "disabled_tools": ["litellm_delete_key", "litellm_delete_team"],
            "disabled_categories": ["chat"],
            "disabled_operations": {"litellm_list_keys": ["delete"]},
        }
    )
    for key in env:
        assert key.startswith(ENV_PREFIX), key

    # A bare "litellm_delete_key" (the old CSV form) is not valid JSON, so
    # pydantic-settings raised SettingsError before any validator ran and the
    # MCP child exited 1 — one toggle on the Tools page killed the connector.
    assert json.loads(env["LITELLM_MCP_DISABLED_TOOLS"]) == [
        "litellm_delete_key",
        "litellm_delete_team",
    ]
    assert json.loads(env["LITELLM_MCP_DISABLED_CATEGORIES"]) == ["chat"]
    assert json.loads(env["LITELLM_MCP_DISABLED_OPERATIONS"]) == {
        "litellm_list_keys": ["delete"]
    }
    assert env["LITELLM_MCP_READONLY"] == "true"


def test_tool_switch_env_round_trips_through_the_environment(monkeypatch) -> None:
    """Exactly the production path: env vars -> Settings() in the child."""
    env = env_from_tool_settings(
        {
            "readonly": True,
            "disabled_tools": ["litellm_delete_key", "litellm_delete_team"],
            "disabled_categories": ["chat"],
            "disabled_operations": {"litellm_list_keys": ["delete"]},
        }
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    cfg = Settings()
    assert cfg.readonly is True
    assert cfg.disabled_tools == ["litellm_delete_key", "litellm_delete_team"]
    assert cfg.disabled_categories == ["chat"]
    assert cfg.disabled_operations == {"litellm_list_keys": ["delete"]}


def test_empty_switch_sets_do_not_kill_the_child(monkeypatch) -> None:
    """"Nothing disabled" must serialise to "[]"/"{}", never to ""."""
    env = env_from_tool_settings({})
    assert env["LITELLM_MCP_DISABLED_TOOLS"] == "[]"
    assert env["LITELLM_MCP_DISABLED_CATEGORIES"] == "[]"
    assert env["LITELLM_MCP_DISABLED_OPERATIONS"] == "{}"
    assert env["LITELLM_MCP_READONLY"] == "false"

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    cfg = Settings()  # used to raise SettingsError -> child exit code 1
    assert cfg.disabled_tools == []
    assert cfg.disabled_categories == []
    assert cfg.readonly is False


def test_disabled_tools_csv_is_still_accepted() -> None:
    """Config files written by older builds must keep loading."""
    cfg = Settings(disabled_tools="litellm_delete_key, litellm_block_key")
    assert cfg.disabled_tools == ["litellm_delete_key", "litellm_block_key"]
