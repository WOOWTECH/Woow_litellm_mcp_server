"""Spend tools build the right requests and parse into the response models.

Replaces the reference repo's ``test_retained_topics``: the spend family is the
LiteLLM analogue of a read-heavy, filter-driven query surface.
"""

from __future__ import annotations

from woow_litellm_mcp_server.models import SpendReportRow, SpendRow
from woow_litellm_mcp_server.tools import spend as spend_module

from .conftest import MockLiteLLM, build_gate, make_ctx


def _spend_tools():
    from .conftest import FakeMCP

    mcp = FakeMCP()
    spend_module.register(mcp, build_gate())
    return mcp.tools


async def test_spend_logs_builds_request_and_prunes_none() -> None:
    rows = [
        {
            "request_id": "req-1",
            "api_key": "sk-abc",
            "user": "u1",
            "model": "gpt-4o",
            "spend": 0.0123,
            "total_tokens": 542,
            "startTime": "2026-08-01T00:00:00Z",
        }
    ]
    gw = MockLiteLLM().route("/spend/logs", rows)
    client = gw.client()
    try:
        tool = _spend_tools()["litellm_spend_logs"]
        result = await tool(
            make_ctx(client),
            api_key="sk-abc",
            start_date="2026-08-01",
            end_date="2026-08-02",
        )
    finally:
        await client.aclose()

    # Correct verb + path.
    assert gw.last.method == "GET"
    assert gw.last.url.path == "/spend/logs"
    # Supplied filters are forwarded; None-valued ones (user_id, request_id,
    # summarize) are pruned so we never send ?user_id=None.
    params = gw.last_params()
    assert params["api_key"] == "sk-abc"
    assert params["start_date"] == "2026-08-01"
    assert params["end_date"] == "2026-08-02"
    assert "user_id" not in params
    assert "summarize" not in params

    # Response parses into the SpendRow model.
    parsed = [SpendRow.model_validate(r) for r in result]
    assert parsed[0].request_id == "req-1"
    assert parsed[0].spend == 0.0123
    assert parsed[0].total_tokens == 542


async def test_global_spend_report_requires_dates_and_groups() -> None:
    report = [
        {"group_by_day": "2026-08-01", "total_spend": 1.5, "team_id": "team-a"},
        {"group_by_day": "2026-08-02", "total_spend": 2.0, "team_id": "team-a"},
    ]
    gw = MockLiteLLM().route("/global/spend/report", report)
    client = gw.client()
    try:
        tool = _spend_tools()["litellm_global_spend_report"]
        result = await tool(
            make_ctx(client),
            start_date="2026-08-01",
            end_date="2026-08-31",
            group_by="team",
        )
    finally:
        await client.aclose()

    assert gw.last.url.path == "/global/spend/report"
    params = gw.last_params()
    assert params["start_date"] == "2026-08-01"
    assert params["end_date"] == "2026-08-31"
    assert params["group_by"] == "team"

    parsed = [SpendReportRow.model_validate(r) for r in result]
    assert parsed[0].team_id == "team-a"
    assert sum(r.total_spend for r in parsed) == 3.5


async def test_spend_calculate_posts_body() -> None:
    gw = MockLiteLLM().route("/spend/calculate", {"cost": 0.004})
    client = gw.client()
    try:
        tool = _spend_tools()["litellm_spend_calculate"]
        result = await tool(
            make_ctx(client),
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )
    finally:
        await client.aclose()

    assert gw.last.method == "POST"
    assert gw.last.url.path == "/spend/calculate"
    body = gw.last_json()
    assert body["model"] == "gpt-4o"
    assert body["messages"][0]["content"] == "hi"
    # completion_response was None -> pruned from the body.
    assert "completion_response" not in body
    assert result == {"cost": 0.004}


def test_spend_model_is_permissive_to_new_fields() -> None:
    # extra="allow": a newer LiteLLM field must not break parsing.
    row = SpendRow.model_validate(
        {"request_id": "r", "spend": 0.1, "some_new_litellm_field": 42}
    )
    assert row.request_id == "r"
    assert row.model_dump().get("some_new_litellm_field") == 42
