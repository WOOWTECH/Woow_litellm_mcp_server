"""``POST /api/config/test`` must accept "probe whatever is saved".

This is a request-*binding* contract, so every test here goes through a real
FastAPI app rather than calling the handler directly: the bug it pins lived
entirely in the model the body was bound to, and a direct call to
``test_connection(...)`` would have passed the whole time it was broken.

The bug: the endpoint bound its body to ``ConnectionSettings``, whose
``litellm_mcp_base_url`` is required because ``PUT /connection`` needs it to be.
So a client asking the documented question — "is the gateway I am already
configured against reachable?" — got ``422 Field required`` for a field it
deliberately did not send, and the saved-values fallback the handler's own
docstring promised was unreachable code.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from litellm_mcp_admin.routers import config as config_router

SAVED_URL = "http://saved-litellm:4000"
SAVED_KEY = "sk-saved-master-key"


@pytest.fixture
def client(temp_config, monkeypatch):
    """A bare app with only the config router — no auth middleware in the way."""
    temp_config.write_text(
        json.dumps(
            {
                "connection": {
                    "litellm_mcp_base_url": SAVED_URL,
                    "litellm_mcp_master_key": SAVED_KEY,
                }
            }
        ),
        "utf-8",
    )

    probes: list[tuple[str, str]] = []

    async def fake_probe(base_url: str, master_key: str) -> dict[str, object]:
        probes.append((base_url, master_key))
        return {"success": True, "ok": True, "probed": base_url}

    monkeypatch.setattr(config_router, "_probe", fake_probe)

    app = FastAPI()
    app.include_router(config_router.router)
    with TestClient(app) as test_client:
        test_client.probes = probes  # type: ignore[attr-defined]
        yield test_client


def test_empty_body_probes_the_saved_connection(client) -> None:
    """``{}`` is the regression: it used to be 422 Field required."""
    response = client.post("/api/config/test", json={})

    assert response.status_code == 200, response.text
    assert client.probes == [(SAVED_URL, SAVED_KEY)]


def test_no_body_at_all_probes_the_saved_connection(client) -> None:
    response = client.post("/api/config/test")

    assert response.status_code == 200, response.text
    assert client.probes == [(SAVED_URL, SAVED_KEY)]


def test_url_only_falls_back_to_the_saved_master_key(client) -> None:
    """ConnectionConfig.jsx's "leave the key blank to keep the stored one".

    Probing with an empty Bearer instead would report the key as rejected and
    send the operator off to fix a credential that was never wrong.
    """
    response = client.post(
        "/api/config/test", json={"litellm_mcp_base_url": "http://typed:4000"}
    )

    assert response.status_code == 200, response.text
    assert client.probes == [("http://typed:4000", SAVED_KEY)]


def test_both_fields_are_probed_verbatim(client) -> None:
    """Testing before saving must not silently substitute the stored values."""
    response = client.post(
        "/api/config/test",
        json={
            "litellm_mcp_base_url": "http://typed:4000",
            "litellm_mcp_master_key": "sk-typed",
        },
    )

    assert response.status_code == 200, response.text
    assert client.probes == [("http://typed:4000", "sk-typed")]


def test_an_explicitly_blank_url_is_honoured_not_replaced(client) -> None:
    """Supplied-but-empty differs from not supplied.

    The operator has cleared the URL field. Falling back to the stored URL here
    would answer "Connected" about a gateway they are no longer pointing at —
    the same shape of misleading success that made this endpoint stop using the
    unauthenticated /health/readiness probe.
    """
    response = client.post("/api/config/test", json={"litellm_mcp_base_url": ""})

    assert response.status_code == 200, response.text
    assert client.probes == [("", SAVED_KEY)]


def test_put_connection_still_requires_the_base_url(client) -> None:
    """The probe was loosened; the save must not have been.

    Saving a connection with no URL takes the child down on the next restart,
    so that one stays a 422.
    """
    response = client.put("/api/config/connection", json={})

    assert response.status_code == 422, response.text
    assert client.probes == []
