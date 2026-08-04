"""The SSE log pipeline: buffer, publish, search, and the core-logger tap."""

from __future__ import annotations

import json
import logging

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


async def test_bad_regex_is_reported_not_raised() -> None:
    result = await logs_router.search_logs(q="(")
    assert "error" in result
    assert result["lines"] == []


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


def test_install_log_capture_is_idempotent() -> None:
    core_logger = logging.getLogger(logs_router.CORE_PROCESS_LOGGER)
    logs_router.install_log_capture()
    before = len(core_logger.handlers)
    logs_router.install_log_capture()
    assert len(core_logger.handlers) == before
