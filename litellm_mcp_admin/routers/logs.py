"""MCP subprocess logs: ring buffer, search and SSE stream.

``mcp_admin_core.process`` logs the child's stdout at INFO on its own module
logger. Nothing configures that logger, so it inherits root's WARNING and the
records are dropped before any handler runs — which is why the LogViewer page
could connect happily and then show nothing at all. ``install_log_capture()``
therefore sets the level as well as attaching the handler.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api/logs", tags=["logs"])

CORE_PROCESS_LOGGER = "mcp_admin_core.process"
_MCP_PREFIX = "[mcp-server] "
_BUFFER_SIZE = 5000
_REPLAY_ON_CONNECT = 200
_HEARTBEAT_SECONDS = 20

_BUFFER: deque[str] = deque(maxlen=_BUFFER_SIZE)
_SUBSCRIBERS: set[asyncio.Queue] = set()

# The child prints its own level; the record level only says how the core
# wrapped it, which is always INFO.
_LEVEL_IN_TEXT = re.compile(r"\b(CRITICAL|ERROR|WARNING|WARN|INFO|DEBUG)\b", re.IGNORECASE)


def _classify(text: str, record_level: str) -> str:
    """Prefer a level the child printed itself over the core's INFO wrapper."""
    match = _LEVEL_IN_TEXT.search(text[:80])
    if match:
        found = match.group(1).lower()
        return "warning" if found == "warn" else found
    return record_level


def _entry(message: str, level: str, source: str) -> str:
    """One SSE payload, shaped for the fields LogViewer.jsx renders."""
    return json.dumps(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": level,
            "message": message,
            "source": source,
        }
    )


def clear_buffer() -> None:
    _BUFFER.clear()


def recent(limit: int = _REPLAY_ON_CONNECT) -> list[str]:
    return list(_BUFFER)[-limit:]


def publish(message: str, level: str = "info", source: str = "mcp-server") -> None:
    """Add a line and fan it out to every open stream."""
    payload = _entry(message, level, source)
    _BUFFER.append(payload)
    for queue in list(_SUBSCRIBERS):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


class _BufferLogHandler(logging.Handler):
    """Mirror the core's process logger into the buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
        except Exception:  # noqa: BLE001 — logging must never raise
            return

        record_level = record.levelname.lower()
        if _MCP_PREFIX in text:
            # Child output: strip the tag so the message column stays readable.
            body = text.split(_MCP_PREFIX, 1)[-1]
            publish(body, _classify(body, record_level), "mcp-server")
        else:
            # Lifecycle lines ("Starting MCP server", "exited with code 1") are
            # exactly what an operator opens this page for.
            publish(text, record_level, "supervisor")


_installed = False


def install_log_capture() -> None:
    global _installed
    if _installed:
        return
    logger = logging.getLogger(CORE_PROCESS_LOGGER)
    # Without this the INFO records never reach the handler at all.
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
    logger.addHandler(_BufferLogHandler())
    _installed = True


install_log_capture()


@router.get("/search")
async def search_logs(q: str = "", limit: int = 200) -> dict[str, Any]:
    """Filter the buffered lines with a regular expression."""
    lines = list(_BUFFER)
    if q:
        try:
            pattern = re.compile(q, re.IGNORECASE)
        except re.error as exc:
            return {"error": f"Invalid regular expression: {exc}", "lines": []}
        lines = [line for line in lines if pattern.search(line)]
    return {"count": len(lines), "lines": lines[-limit:]}


@router.get("/stream")
async def stream_logs() -> EventSourceResponse:
    """Live tail of the MCP subprocess output.

    Replays the recent buffer first so the page is never blank, then keeps the
    connection warm — an idle SSE stream through a proxy or tunnel gets cut.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _SUBSCRIBERS.add(queue)

    async def publisher():
        try:
            for line in recent():
                yield {"data": line}
            while True:
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"data": line}
        finally:
            _SUBSCRIBERS.discard(queue)

    return EventSourceResponse(publisher())
