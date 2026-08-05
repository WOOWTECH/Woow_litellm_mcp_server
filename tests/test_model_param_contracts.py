"""The two ``litellm_params`` contracts /model/new and /model/update impose.

Both were found by driving the deployed server against a live LiteLLM gateway,
and both fail in ways that do not look like the tool's fault:

* ``/model/update`` rejects a body with no ``litellm_params`` at all, with a
  bare "litellm_params not provided" wrapped in a 400 — so every rename-only or
  metadata-only update looked like the *caller* had passed something wrong;
* ``/model/new`` accepts ``api_key: "os.environ/NAME"``, encrypts the literal
  text, answers 200, and produces a deployment that 401s on every request
  forever.

The second is the dangerous one: it is shaped like success. Nothing downstream
can tell you the model is dead until a user's completion fails, and the 401 it
then produces points at the wrong credential entirely (see
``tests/test_errors.py``). Hence a pre-flight refusal rather than a doc note.
"""

from __future__ import annotations

import pytest

from woow_litellm_mcp_server.errors import ToolError
from woow_litellm_mcp_server.tools import models as models_mod

from .conftest import FakeMCP, MockLiteLLM, build_gate, make_ctx


def _tool(name: str):
    mcp = FakeMCP()
    models_mod.register(mcp, build_gate())
    return mcp.tools[name]


async def _call(gw: MockLiteLLM, tool, **kwargs):
    client = gw.client()
    try:
        return await tool(make_ctx(client), **kwargs)
    finally:
        await client.aclose()


async def test_update_model_always_sends_litellm_params() -> None:
    """Omitting litellm_params must still send ``{}``, never nothing.

    LiteLLM merges the object field by field against the stored deployment, so
    ``{}`` means "change nothing here" and the existing model / api_base /
    api_key survive untouched — verified against the live gateway by updating a
    deployment with ``{}`` and then running a real completion through it.
    """
    gw = MockLiteLLM().route("/model/update", {"model_id": "m-1"})
    await _call(gw, _tool("litellm_update_model"), model_id="m-1", model_name="renamed")

    body = gw.last_json()
    assert body["litellm_params"] == {}, body
    assert body["model_name"] == "renamed"
    assert body["model_info"]["id"] == "m-1"


async def test_update_model_passes_real_params_through_untouched() -> None:
    """The always-send rule must not flatten params the caller did supply."""
    gw = MockLiteLLM().route("/model/update", {"model_id": "m-1"})
    await _call(
        gw,
        _tool("litellm_update_model"),
        model_id="m-1",
        litellm_params={"model": "openai/gpt-4o", "rpm": 60},
    )
    assert gw.last_json()["litellm_params"] == {"model": "openai/gpt-4o", "rpm": 60}


@pytest.mark.parametrize("tool_name", ["litellm_add_model", "litellm_update_model"])
async def test_env_ref_api_key_is_refused_before_the_request(tool_name: str) -> None:
    """``os.environ/NAME`` never reaches the gateway, on either endpoint."""
    gw = MockLiteLLM().default({"model_id": "m-1"})
    extra = (
        {"model_name": "m"}
        if tool_name == "litellm_add_model"
        else {"model_id": "m-1"}
    )

    with pytest.raises(ToolError) as exc:
        await _call(
            gw,
            _tool(tool_name),
            litellm_params={
                "model": "openrouter/openai/gpt-4o-mini",
                "api_key": "os.environ/OPENROUTER_API_KEY",
            },
            **extra,
        )

    message = str(exc.value)
    assert "api_key" in message
    assert "os.environ/" in message
    assert "omit" in message.lower(), "it must name the fix, not just say no"
    assert not gw.requests, "the dead model must never reach the gateway"


async def test_every_offending_key_is_named_not_just_the_first() -> None:
    """An operator fixing one key at a time round-trips for each one."""
    gw = MockLiteLLM().default({})
    with pytest.raises(ToolError) as exc:
        await _call(
            gw,
            _tool("litellm_add_model"),
            model_name="m",
            litellm_params={
                "model": "openrouter/openai/gpt-4o-mini",
                "api_key": "os.environ/OPENROUTER_API_KEY",
                "api_base": "os.environ/OPENROUTER_BASE",
            },
        )
    message = str(exc.value)
    assert "api_key" in message and "api_base" in message


async def test_a_real_api_key_still_goes_through() -> None:
    """The guard keys off the os.environ/ prefix only, not the word api_key."""
    gw = MockLiteLLM().route("/model/new", {"model_id": "m-1"})
    await _call(
        gw,
        _tool("litellm_add_model"),
        model_name="m",
        litellm_params={"model": "openai/gpt-4o", "api_key": "sk-real"},
    )
    assert gw.last_json()["litellm_params"]["api_key"] == "sk-real"


async def test_non_string_params_do_not_trip_the_guard() -> None:
    """rpm/tpm ints and nested dicts must not raise inside the prefix check."""
    gw = MockLiteLLM().route("/model/new", {"model_id": "m-1"})
    await _call(
        gw,
        _tool("litellm_add_model"),
        model_name="m",
        litellm_params={
            "model": "openai/gpt-4o",
            "rpm": 100,
            "tpm": None,
            "extra_headers": {"x-a": "b"},
        },
    )
    assert gw.last_json()["litellm_params"]["rpm"] == 100
