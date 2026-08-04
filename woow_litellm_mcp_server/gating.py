"""Three-level tool gating: category, tool, operation, plus read-only mode.

The gate is built from :class:`~woow_litellm_mcp_server.settings.Settings` and is
consulted by each tool module's ``register`` function so disabled tools are
never even registered on the FastMCP server.

Precedence (a tool is enabled only if ALL hold):
  1. its category is not in ``disabled_categories``;
  2. its name is not in ``disabled_tools``;
  3. read-only mode is off OR the tool is not ``dangerous``.

Operation gating additionally filters the operations a still-enabled tool may
perform via ``disabled_operations`` (entries may be ``"tool:op"`` or bare
``"op"``); in read-only mode only the ``read`` operation survives.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .registry import (
    OP_READ,
    TOOL_REGISTRY,
    TOOLS_BY_NAME,
    ToolCategory,
    ToolSpec,
)
from .settings import Settings, get_settings


def _normalize_operations(value: Any) -> set[str]:
    """Coerce a disabled-operations spec into a ``{"tool:op", "op"}`` set.

    Two shapes are accepted so both call sites agree:

    * the Settings/env form — a list of strings, each ``"tool:op"`` or bare
      ``"op"`` (``["litellm_delete_key:delete", "delete"]``);
    * the admin GUI form — a mapping ``{tool_name: [op, ...]}`` which is
      expanded into the ``"tool:op"`` string set.
    """
    if not value:
        return set()
    if isinstance(value, Mapping):
        result: set[str] = set()
        for tool, ops in value.items():
            for op in ops or []:
                if str(op).strip():
                    result.add(f"{tool}:{str(op).strip()}")
        return result
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return {str(o).strip() for o in value if str(o).strip()}
    return {str(value).strip()} if str(value).strip() else set()


class ToolGate:
    """Decides which tools/operations are exposed for a given configuration.

    Construct it either from a :class:`Settings` object (the server path) or
    directly from keyword overrides (the admin-console path, which builds a gate
    on the fly from the stored ``tools`` switches). Keyword overrides win over
    the ``settings`` values when both are supplied.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        readonly: bool | None = None,
        disabled_categories: Iterable[str] | None = None,
        disabled_tools: Iterable[str] | None = None,
        disabled_operations: Any = None,
    ) -> None:
        # No settings and no overrides -> fall back to the process singleton.
        if (
            settings is None
            and readonly is None
            and disabled_categories is None
            and disabled_tools is None
            and disabled_operations is None
        ):
            settings = get_settings()

        if settings is not None:
            if readonly is None:
                readonly = settings.readonly
            if disabled_categories is None:
                disabled_categories = settings.disabled_categories
            if disabled_tools is None:
                disabled_tools = settings.disabled_tools
            if disabled_operations is None:
                disabled_operations = settings.disabled_operations

        self.readonly: bool = bool(readonly)
        self._disabled_categories: set[str] = {
            str(c).strip().lower() for c in (disabled_categories or []) if str(c).strip()
        }
        self._disabled_tools: set[str] = {
            str(t).strip() for t in (disabled_tools or []) if str(t).strip()
        }
        self._disabled_operations: set[str] = _normalize_operations(disabled_operations)

    # -- category ----------------------------------------------------------
    def is_category_enabled(self, category: ToolCategory | str) -> bool:
        value = category.value if isinstance(category, ToolCategory) else str(category)
        return value.lower() not in self._disabled_categories

    # -- tool --------------------------------------------------------------
    def is_tool_enabled(self, name: str) -> bool:
        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            return False
        if not self.is_category_enabled(spec.category):
            return False
        if spec.name in self._disabled_tools:
            return False
        if self.readonly and spec.dangerous:
            return False
        return True

    # -- operation ---------------------------------------------------------
    def is_operation_allowed(self, name: str, operation: str) -> bool:
        if f"{name}:{operation}" in self._disabled_operations:
            return False
        if operation in self._disabled_operations:
            return False
        if self.readonly and operation != OP_READ:
            return False
        return True

    def allowed_operations(self, name: str) -> tuple[str, ...]:
        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            return ()
        return tuple(
            op for op in spec.operations if self.is_operation_allowed(name, op)
        )

    # -- bulk views --------------------------------------------------------
    def enabled_tools(self) -> list[ToolSpec]:
        return [s for s in TOOL_REGISTRY if self.is_tool_enabled(s.name)]

    def enabled_tool_names(self) -> list[str]:
        return [s.name for s in self.enabled_tools()]
