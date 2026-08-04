"""Every tool family builds the right HTTP request and parses the response.

One representative tool per category is exercised end-to-end through the real
tool code (register -> call), asserting the method, path, query params / JSON
body and the parsed return value. ``prune_none`` behaviour (never sending nulls)
is checked where it matters.
"""

from __future__ import annotations

from woow_litellm_mcp_server.models import HealthStatus, KeyInfo, ModelList, PluginInfo
from woow_litellm_mcp_server.tools import (
    health as health_mod,
    keys as keys_mod,
    models as models_mod,
    plugins as plugins_mod,
)

from .conftest import FakeMCP, MockLiteLLM, build_gate, make_ctx


def _register(module) -> dict:
    mcp = FakeMCP()
    module.register(mcp, build_gate())
    return mcp.tools


async def _call(gw: MockLiteLLM, tool, **kwargs):
    client = gw.client()
    try:
        return await tool(make_ctx(client), **kwargs)
    finally:
        await client.aclose()


# --- models ---------------------------------------------------------------
async def test_list_models_get_and_parse() -> None:
    gw = MockLiteLLM().route("/v1/models", {"object": "list", "data": [{"id": "gpt-4o"}]})
    result = await _call(gw, _register(models_mod)["litellm_list_models"])
    assert gw.last.method == "GET"
    assert gw.last.url.path == "/v1/models"
    parsed = ModelList.model_validate(result)
    assert parsed.data[0].id == "gpt-4o"


async def test_add_model_posts_body() -> None:
    gw = MockLiteLLM().route("/model/new", {"model_id": "m-1"})
    tool = _register(models_mod)["litellm_add_model"]
    result = await _call(
        gw,
        tool,
        model_name="my-gpt",
        litellm_params={"model": "openai/gpt-4o", "api_key": "sk-x"},
    )
    assert gw.last.method == "POST"
    assert gw.last.url.path == "/model/new"
    body = gw.last_json()
    assert body["model_name"] == "my-gpt"
    assert body["litellm_params"]["model"] == "openai/gpt-4o"
    assert "model_info" not in body  # None was pruned
    assert result == {"model_id": "m-1"}


async def test_delete_model_sends_id() -> None:
    gw = MockLiteLLM().route("/model/delete", {"deleted": True})
    tool = _register(models_mod)["litellm_delete_model"]
    await _call(gw, tool, model_id="m-9")
    assert gw.last.url.path == "/model/delete"
    assert gw.last_json() == {"id": "m-9"}


# --- keys -----------------------------------------------------------------
async def test_generate_key_prunes_none() -> None:
    gw = MockLiteLLM().route("/key/generate", {"key": "sk-new"})
    tool = _register(keys_mod)["litellm_generate_key"]
    result = await _call(gw, tool, key_alias="ci", max_budget=10.0)
    assert gw.last.method == "POST"
    assert gw.last.url.path == "/key/generate"
    body = gw.last_json()
    assert body == {"key_alias": "ci", "max_budget": 10.0}  # everything else pruned
    assert result["key"] == "sk-new"


async def test_key_info_get_with_param_and_model() -> None:
    payload = {"token": "sk-abc", "key_alias": "ci", "spend": 1.25, "max_budget": 10.0}
    gw = MockLiteLLM().route("/key/info", payload)
    tool = _register(keys_mod)["litellm_key_info"]
    result = await _call(gw, tool, key="sk-abc")
    assert gw.last.url.path == "/key/info"
    assert gw.last_params()["key"] == "sk-abc"
    parsed = KeyInfo.model_validate(result)
    assert parsed.spend == 1.25


async def test_regenerate_key_uses_path_segment() -> None:
    gw = MockLiteLLM().route("/key/sk-abc/regenerate", {"key": "sk-rotated"})
    tool = _register(keys_mod)["litellm_regenerate_key"]
    result = await _call(gw, tool, key="sk-abc")
    assert gw.last.method == "POST"
    assert gw.last.url.path == "/key/sk-abc/regenerate"
    assert result["key"] == "sk-rotated"


# --- health ---------------------------------------------------------------
async def test_health_readiness_get_and_parse() -> None:
    payload = {"status": "connected", "db": "connected", "healthy_count": 3}
    gw = MockLiteLLM().route("/health/readiness", payload)
    tool = _register(health_mod)["litellm_health_readiness"]
    result = await _call(gw, tool)
    assert gw.last.url.path == "/health/readiness"
    parsed = HealthStatus.model_validate(result)
    assert parsed.status == "connected"
    assert parsed.db == "connected"


# --- plugins (Claude-Code skill hub) --------------------------------------
async def test_list_plugins_omits_false_enabled_only() -> None:
    gw = MockLiteLLM().route("/claude-code/plugins", [{"name": "p", "enabled": True}])
    tool = _register(plugins_mod)["litellm_list_plugins"]
    result = await _call(gw, tool)  # enabled_only defaults False -> pruned
    assert gw.last.url.path == "/claude-code/plugins"
    assert "enabled_only" not in gw.last_params()
    parsed = [PluginInfo.model_validate(p) for p in result]
    assert parsed[0].name == "p"


async def test_enable_plugin_posts_to_named_path() -> None:
    gw = MockLiteLLM().route("/claude-code/plugins/my-plugin/enable", {"enabled": True})
    tool = _register(plugins_mod)["litellm_enable_plugin"]
    result = await _call(gw, tool, plugin_name="my-plugin")
    assert gw.last.method == "POST"
    assert gw.last.url.path == "/claude-code/plugins/my-plugin/enable"
    assert result == {"enabled": True}
