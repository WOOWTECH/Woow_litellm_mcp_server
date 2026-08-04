"""Runtime settings for the LiteLLM MCP server.

All values are read from the environment with the ``LITELLM_MCP_`` prefix so
they line up with the connection section written by the admin console
(``litellm_mcp_base_url`` -> ``LITELLM_MCP_BASE_URL`` etc.) and with the k8s
Secret used by the git-clone deployment.

NEVER hard-code the master key here; it always comes from the environment.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: object) -> list[str]:
    """Accept a comma-separated string or a list and normalise to a list."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


class Settings(BaseSettings):
    """Environment-driven configuration for the MCP server."""

    model_config = SettingsConfigDict(
        env_prefix="LITELLM_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- upstream connection -------------------------------------------------
    base_url: str = Field(
        default="http://localhost:4000",
        description="Base URL of the LiteLLM gateway (no /api/v5 suffix).",
    )
    master_key: str = Field(
        default="",
        description="LiteLLM master (or admin) key sent as a Bearer token.",
    )

    # --- gating --------------------------------------------------------------
    readonly: bool = Field(
        default=False,
        description="When true, every dangerous/mutating tool is dropped.",
    )
    disabled_categories: list[str] = Field(
        default_factory=list,
        description="Tool categories to disable entirely (e.g. 'chat,users').",
    )
    disabled_tools: list[str] = Field(
        default_factory=list,
        description="Individual tool names to disable (e.g. 'litellm_delete_key').",
    )
    disabled_operations: list[str] = Field(
        default_factory=list,
        description="Operation gates, 'tool:op' or bare 'op', to disable.",
    )

    # --- paging / limits -----------------------------------------------------
    default_limit: int = Field(
        default=50, ge=1, description="Default page size for list tools."
    )
    max_limit: int = Field(
        default=500, ge=1, description="Maximum page size a caller may request."
    )
    request_timeout: float = Field(
        default=60.0, gt=0, description="Per-request HTTP timeout in seconds."
    )

    @field_validator(
        "disabled_categories",
        "disabled_tools",
        "disabled_operations",
        mode="before",
    )
    @classmethod
    def _coerce_csv(cls, value: object) -> list[str]:
        return _split_csv(value)

    @field_validator("base_url", mode="before")
    @classmethod
    def _strip_trailing_slash(cls, value: object) -> object:
        if isinstance(value, str):
            return value.rstrip("/")
        return value

    def clamp_limit(self, requested: int | None) -> int:
        """Clamp a caller-requested page size into [1, max_limit]."""
        if requested is None:
            return self.default_limit
        return max(1, min(int(requested), self.max_limit))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


# Convenience module-level singleton (evaluated lazily on first access via the
# cached factory; import ``get_settings`` where you need testable overrides).
settings = get_settings()
