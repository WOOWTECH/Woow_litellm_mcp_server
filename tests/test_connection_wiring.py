"""The admin connection keys must map onto the server's Settings env names.

``mcp_admin_core.process`` upper-cases each key in the ``connection`` section
and injects it into the MCP subprocess environment. Those upper-cased names must
line up with ``Settings`` (``env_prefix="LITELLM_MCP_"``) or the child server
would silently ignore the operator's configuration.
"""

from __future__ import annotations

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


def test_tool_switch_env_keys_are_prefixed_and_parse() -> None:
    env = env_from_tool_settings(
        {
            "readonly": True,
            "disabled_tools": ["litellm_delete_key", "litellm_delete_team"],
            "disabled_categories": ["chat"],
        }
    )
    for key in env:
        assert key.startswith(ENV_PREFIX), key

    # The load-bearing switches must round-trip into Settings.
    cfg = Settings(
        readonly=env["LITELLM_MCP_READONLY"],
        disabled_tools=env["LITELLM_MCP_DISABLED_TOOLS"],
        disabled_categories=env["LITELLM_MCP_DISABLED_CATEGORIES"],
    )
    assert cfg.readonly is True
    assert cfg.disabled_tools == ["litellm_delete_key", "litellm_delete_team"]
    assert cfg.disabled_categories == ["chat"]


def test_disabled_tools_csv_is_split() -> None:
    cfg = Settings(disabled_tools="litellm_delete_key, litellm_block_key")
    assert cfg.disabled_tools == ["litellm_delete_key", "litellm_block_key"]
