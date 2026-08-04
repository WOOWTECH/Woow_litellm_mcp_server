"""Shared fixtures for the LiteLLM MCP server test suite.

Nothing here talks to a real LiteLLM gateway. Tool HTTP calls are intercepted
with ``httpx.MockTransport`` so we can assert on the exact request each tool
builds (method, path, query params, JSON body) and control the response the
tool parses. The MCP layer is exercised through a tiny ``FakeMCP`` that captures
the real tool coroutines each ``register()`` installs, so the production tool
code runs unchanged.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable

import httpx
import pytest

from woow_litellm_mcp_server.gating import ToolGate
from woow_litellm_mcp_server.lifespan import LITELLM_CLIENT_KEY
from woow_litellm_mcp_server.settings import Settings
from woow_litellm_mcp_server.tools import MODULES


# ---------------------------------------------------------------------------
# A minimal stand-in for FastMCP that records the tools a module registers.
# ---------------------------------------------------------------------------
class FakeMCP:
    """Captures ``@mcp.tool(...)``-decorated coroutines by name."""

    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {}
        self.annotations: dict[str, Any] = {}

    def tool(self, *args: Any, name: str | None = None, annotations: Any = None, **_: Any):
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            key = name or getattr(fn, "__name__", None)
            assert key, "tool must have a name"
            self.tools[key] = fn
            self.annotations[key] = annotations
            return fn

        # Support both `@mcp.tool` and `@mcp.tool(...)` usage.
        if args and callable(args[0]) and name is None:
            return decorator(args[0])
        return decorator


def build_gate(**overrides: Any) -> ToolGate:
    """A gate built from explicit overrides (init kwargs beat any env)."""
    return ToolGate(
        readonly=overrides.get("readonly", False),
        disabled_categories=overrides.get("disabled_categories", []),
        disabled_tools=overrides.get("disabled_tools", []),
        disabled_operations=overrides.get("disabled_operations", []),
    )


def register_all(gate: ToolGate) -> FakeMCP:
    """Register every tool module against a FakeMCP with the given gate."""
    mcp = FakeMCP()
    for module in MODULES:
        module.register(mcp, gate)
    return mcp


@pytest.fixture
def all_enabled_gate() -> ToolGate:
    return build_gate()


@pytest.fixture
def registered(all_enabled_gate: ToolGate) -> FakeMCP:
    """A FakeMCP with every gate-enabled tool registered."""
    return register_all(all_enabled_gate)


# ---------------------------------------------------------------------------
# A recording httpx transport standing in for the LiteLLM gateway.
# ---------------------------------------------------------------------------
class MockLiteLLM:
    """Records outbound requests and returns canned JSON responses."""

    def __init__(self, base_url: str = "http://litellm.test") -> None:
        self.base_url = base_url
        self.requests: list[httpx.Request] = []
        self._routes: dict[str, tuple[int, Any]] = {}
        self._default: tuple[int, Any] = (200, {})

    def route(self, path: str, payload: Any, status: int = 200) -> "MockLiteLLM":
        self._routes[path] = (status, payload)
        return self

    def default(self, payload: Any, status: int = 200) -> "MockLiteLLM":
        self._default = (status, payload)
        return self

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self._routes.get(request.url.path, self._default)
        return httpx.Response(status, json=payload)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            transport=httpx.MockTransport(self._handler),
        )

    # -- convenience accessors for assertions ------------------------------
    @property
    def last(self) -> httpx.Request:
        assert self.requests, "no request was made"
        return self.requests[-1]

    def last_json(self) -> Any:
        body = self.last.content
        return json.loads(body) if body else None

    def last_params(self) -> dict[str, str]:
        return dict(self.last.url.params)


def make_ctx(client: httpx.AsyncClient) -> SimpleNamespace:
    """A fake FastMCP Context exposing the lifespan context dict."""
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context={LITELLM_CLIENT_KEY: client}
        )
    )


@pytest.fixture
def mock_litellm() -> MockLiteLLM:
    return MockLiteLLM()


@pytest.fixture
async def ctx(mock_litellm: MockLiteLLM):
    """A ready-to-use fake Context whose client is the mock gateway."""
    client = mock_litellm.client()
    try:
        yield make_ctx(client)
    finally:
        await client.aclose()


@pytest.fixture
def settings_factory():
    """Build a Settings object with explicit values (init kwargs beat env)."""

    def _make(**kwargs: Any) -> Settings:
        return Settings(**kwargs)

    return _make


# ---------------------------------------------------------------------------
# Temp config store: point mcp_admin_core + the admin routers at a tmp file and
# reset their module-level singletons so tests never touch /data/config.json.
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("MCP_ADMIN_CONFIG", str(cfg_path))

    # Reset the cached singletons so they pick up the temp path.
    import mcp_admin_core.config.store as store_mod
    import mcp_admin_core.process as process_mod

    monkeypatch.setattr(store_mod, "_instance", None, raising=False)
    monkeypatch.setattr(process_mod, "_instance", None, raising=False)

    yield cfg_path

    monkeypatch.setattr(store_mod, "_instance", None, raising=False)
    monkeypatch.setattr(process_mod, "_instance", None, raising=False)
