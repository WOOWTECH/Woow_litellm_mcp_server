"""The SSE log pipeline: buffer, publish, search, and the core-logger tap."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from litellm_mcp_admin.routers import logs as logs_router


def _payloads(lines: list[str]) -> list[dict]:
    return [json.loads(line) for line in lines]


def test_publish_appends_to_buffer_with_expected_shape() -> None:
    logs_router.clear_buffer()
    logs_router.publish("hello world", level="info", source="mcp-server")

    recent = logs_router.recent()
    assert recent, "buffer should hold the published line"
    entry = _payloads(recent)[-1]
    assert entry["message"] == "hello world"
    assert entry["level"] == "info"
    assert entry["source"] == "mcp-server"
    assert "timestamp" in entry


async def test_search_filters_with_regex() -> None:
    logs_router.clear_buffer()
    logs_router.publish("Uvicorn running on 0.0.0.0:8000")
    logs_router.publish("registered 38 tools")
    logs_router.publish("GET /v1/models 200")

    result = await logs_router.search_logs(q="Uvicorn")
    assert result["count"] == 1
    assert "Uvicorn" in result["lines"][0]


async def test_search_matches_the_message_not_the_envelope() -> None:
    """``q`` must not match the timestamp/level/source fields of the JSON line."""
    logs_router.clear_buffer()
    logs_router.publish("registered 38 tools", level="info", source="mcp-server")

    # "mcp-server" only appears in the envelope, never in the message.
    assert (await logs_router.search_logs(q="mcp-server"))["count"] == 0
    # ...and an anchor is meaningful again.
    assert (await logs_router.search_logs(q="^registered", regex=True))["count"] == 1


async def test_bad_regex_is_a_422() -> None:
    """An unparseable pattern must fail loudly, not return the whole buffer."""
    with pytest.raises(HTTPException) as excinfo:
        await logs_router.search_logs(q="(", regex=True)
    assert excinfo.value.status_code == 422


async def test_level_and_source_filters_are_applied() -> None:
    logs_router.clear_buffer()
    logs_router.publish("boom", level="error", source="mcp-server")
    logs_router.publish("fine", level="info", source="mcp-server")
    logs_router.publish("admin note", level="error", source="admin")

    only_errors = await logs_router.search_logs(level="error")
    assert only_errors["count"] == 2

    child_errors = await logs_router.search_logs(level="error", source="mcp-server")
    assert child_errors["count"] == 1
    assert "boom" in child_errors["lines"][0]

    # A typo used to be ignored, so "level=eror" looked like a successful query.
    with pytest.raises(HTTPException) as excinfo:
        await logs_router.search_logs(level="eror")
    assert excinfo.value.status_code == 422


async def test_since_filter_and_validation() -> None:
    logs_router.clear_buffer()
    logs_router.publish("old line")

    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    assert (await logs_router.search_logs(since=future))["count"] == 0

    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert (await logs_router.search_logs(since=past))["count"] == 1

    with pytest.raises(HTTPException) as excinfo:
        await logs_router.search_logs(since="yesterday")
    assert excinfo.value.status_code == 422


async def test_limit_zero_does_not_return_everything() -> None:
    logs_router.clear_buffer()
    for i in range(10):
        logs_router.publish(f"line {i}")

    result = await logs_router.search_logs(limit=0)
    assert result["count"] == 10  # count is the match total...
    assert len(result["lines"]) == 1  # ...but limit=0 is clamped to 1, not "all"


def test_traceback_lines_are_classified_as_errors() -> None:
    """A crash must render red, or the error filter hides the only useful event."""
    logs_router.install_log_capture()
    logs_router.clear_buffer()

    core = logging.getLogger(logs_router.CORE_PROCESS_LOGGER)
    for line in (
        "Traceback (most recent call last):",
        '  File "/app/woow_litellm_mcp_server/settings.py", line 1, in <module>',
        "    settings = get_settings()",
        "SettingsError: error parsing value for field \"disabled_tools\"",
    ):
        core.info("[mcp-server] %s", line)

    entries = _payloads(logs_router.recent())
    assert entries and all(e["level"] == "error" for e in entries), entries


def test_admin_side_logging_is_captured() -> None:
    """An operator debugging a 500 needs the admin half of the service too."""
    logs_router.install_log_capture()
    logs_router.clear_buffer()

    logging.getLogger("litellm_mcp_admin.routers.config").error("probe failed")

    entries = _payloads(logs_router.recent())
    admin = [e for e in entries if e["message"] == "probe failed"]
    assert admin and admin[0]["source"] == "admin"
    assert admin[0]["level"] == "error"


def test_core_process_logger_is_captured_into_buffer() -> None:
    """A [mcp-server]-tagged record from the core logger lands in the buffer."""
    logs_router.install_log_capture()  # idempotent
    logs_router.clear_buffer()

    core_logger = logging.getLogger(logs_router.CORE_PROCESS_LOGGER)
    core_logger.info("[mcp-server] Application startup complete")

    entries = _payloads(logs_router.recent())
    messages = [e["message"] for e in entries]
    # The [mcp-server] tag is stripped so the message column stays readable.
    assert "Application startup complete" in messages
    child = [e for e in entries if e["message"] == "Application startup complete"][0]
    assert child["source"] == "mcp-server"


def test_supervisor_lifecycle_lines_are_captured() -> None:
    logs_router.install_log_capture()
    logs_router.clear_buffer()

    logging.getLogger(logs_router.CORE_PROCESS_LOGGER).warning(
        "MCP server exited with code 1"
    )
    entries = _payloads(logs_router.recent())
    supervisor = [e for e in entries if "exited with code" in e["message"]]
    assert supervisor and supervisor[0]["source"] == "supervisor"


async def test_idle_stream_emits_a_ping_heartbeat(monkeypatch) -> None:
    """An idle SSE stream must keep talking or a proxy/tunnel cuts it.

    This is deliberately unit-tested rather than probed in production: the
    deployment's readiness probe hits ``/healthz`` every 10s and each hit is an
    access-log line that goes down every open stream, so a live stream is never
    idle long enough for the heartbeat to fire. That makes the ping path the one
    branch a black-box test can never reach, which is exactly why it needs a
    test here.
    """
    monkeypatch.setattr(logs_router, "_HEARTBEAT_SECONDS", 0.02)
    logs_router.clear_buffer()
    logs_router.publish("replayed line", level="info", source="mcp-server")

    response = await logs_router.stream_logs()
    frames = []
    try:
        for _ in range(3):
            frames.append(await response.body_iterator.__anext__())
    finally:
        await response.body_iterator.aclose()

    first = json.loads(frames[0]["data"])
    assert first["message"] == "replayed line", "the buffer must be replayed first"
    pings = [f for f in frames[1:] if f.get("event") == "ping"]
    assert pings, f"an idle stream produced no heartbeat: {frames}"
    assert pings[0]["data"] == "{}"


async def test_stream_fans_out_newly_published_lines(monkeypatch) -> None:
    """A line published after a client connects reaches that client."""
    monkeypatch.setattr(logs_router, "_HEARTBEAT_SECONDS", 30)
    logs_router.clear_buffer()
    logs_router.publish("replayed line")

    response = await logs_router.stream_logs()
    try:
        await response.body_iterator.__anext__()  # drain the replay
        logs_router.publish("live line", level="error", source="admin")
        frame = await response.body_iterator.__anext__()
    finally:
        await response.body_iterator.aclose()

    payload = json.loads(frame["data"])
    assert payload["message"] == "live line"
    assert payload["level"] == "error"
    assert payload["source"] == "admin"


async def test_stream_unsubscribes_when_the_client_goes_away() -> None:
    """Every closed stream must drop its queue, or publish() leaks forever."""
    logs_router.clear_buffer()
    logs_router.publish("replayed line")
    before = len(logs_router._SUBSCRIBERS)

    response = await logs_router.stream_logs()
    await response.body_iterator.__anext__()
    assert len(logs_router._SUBSCRIBERS) == before + 1
    await response.body_iterator.aclose()

    assert len(logs_router._SUBSCRIBERS) == before


def test_install_log_capture_is_idempotent() -> None:
    core_logger = logging.getLogger(logs_router.CORE_PROCESS_LOGGER)
    logs_router.install_log_capture()
    before = len(core_logger.handlers)
    logs_router.install_log_capture()
    assert len(core_logger.handlers) == before
