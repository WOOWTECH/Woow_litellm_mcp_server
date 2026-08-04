"""Error mapping in ``errors.litellm_request`` — actionable ToolError messages."""

from __future__ import annotations

import httpx
import pytest

from woow_litellm_mcp_server.errors import (
    LiteLLMApiError,
    json_body,
    litellm_request,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="http://litellm.test",
        transport=httpx.MockTransport(handler),
    )


async def test_401_names_the_master_key() -> None:
    client = _client(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}))
    try:
        with pytest.raises(LiteLLMApiError) as exc:
            await litellm_request(client, "GET", "/key/list")
        assert "MASTER_KEY" in str(exc.value)
        assert "bad key" in str(exc.value)
    finally:
        await client.aclose()


async def test_404_names_the_endpoint() -> None:
    client = _client(lambda r: httpx.Response(404, json={"detail": "nope"}))
    try:
        with pytest.raises(LiteLLMApiError) as exc:
            await litellm_request(client, "GET", "/does/not/exist")
        assert "404" in str(exc.value)
        assert "/does/not/exist" in str(exc.value)
    finally:
        await client.aclose()


async def test_422_surfaces_validation_body() -> None:
    client = _client(lambda r: httpx.Response(422, json={"detail": "field required"}))
    try:
        with pytest.raises(LiteLLMApiError) as exc:
            await litellm_request(client, "POST", "/key/generate", json_data={})
        assert "field required" in str(exc.value)
    finally:
        await client.aclose()


async def test_connect_error_mentions_port_4000() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _client(boom)
    try:
        with pytest.raises(LiteLLMApiError) as exc:
            await litellm_request(client, "GET", "/v1/models")
        assert "4000" in str(exc.value)
    finally:
        await client.aclose()


async def test_params_with_none_are_dropped() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={})

    client = _client(handler)
    try:
        await litellm_request(
            client, "GET", "/key/list", params={"page": 1, "user_id": None}
        )
        assert seen["params"] == {"page": "1"}
    finally:
        await client.aclose()


def test_json_body_tolerates_empty_and_204() -> None:
    assert json_body(httpx.Response(204)) == {}
    assert json_body(httpx.Response(200, content=b"")) == {}
    assert json_body(httpx.Response(200, json={"a": 1})) == {"a": 1}
    # Non-JSON body is wrapped rather than raising.
    assert json_body(httpx.Response(200, content=b"not json")) == {"raw": "not json"}
