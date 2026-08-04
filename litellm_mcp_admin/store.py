"""Persistence for the tool switches.

Reads and writes the same ``tools`` section of ``config.json`` that
``mcp_admin_core.ConfigStore`` owns, so the Admin GUI and the MCP server
subprocess always agree on what is switched off.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULT: dict[str, Any] = {
    "disabled_categories": [],
    "disabled_tools": [],
    "disabled_operations": {},
    "readonly": False,
}


def env_from_tool_settings(tools: dict[str, Any]) -> dict[str, str]:
    """Translate stored switches into the subprocess environment.

    ``mcp_admin_core.process`` only forwards the ``connection`` section, so the
    MCP server would otherwise never learn what the operator switched off.
    Merge this into the child environment when starting or restarting it.

    The keys use the ``LITELLM_MCP_`` prefix so they line up with
    ``woow_litellm_mcp_server.settings.Settings`` (``env_prefix="LITELLM_MCP_"``).
    """
    settings = {**_DEFAULT, **(tools or {})}
    return {
        "LITELLM_MCP_DISABLED_CATEGORIES": ",".join(settings["disabled_categories"]),
        "LITELLM_MCP_DISABLED_TOOLS": ",".join(settings["disabled_tools"]),
        "LITELLM_MCP_DISABLED_OPERATIONS": json.dumps(settings["disabled_operations"]),
        "LITELLM_MCP_READONLY": "true" if settings["readonly"] else "false",
    }


class ToolConfigStore:
    """File-backed store for the ``tools`` section."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def _read_all(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def load(self) -> dict[str, Any]:
        """Current tool settings, merged over defaults so new keys appear."""
        return {**_DEFAULT, **self._read_all().get("tools", {})}

    def save(self, tools: dict[str, Any]) -> dict[str, Any]:
        """Persist tool settings, leaving every other config section intact."""
        config = self._read_all()
        merged = {**self.load(), **tools}
        config["tools"] = merged
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(config, indent=2), "utf-8")
        return merged
