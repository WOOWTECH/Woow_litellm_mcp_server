"""Virtual-key management tools (category: keys)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..deps import litellm_client
from ..gating import ToolGate
from ._common import destructive, prune_none, read_only, writing


def register(mcp: Any, gate: ToolGate) -> None:
    if gate.is_tool_enabled("litellm_generate_key"):

        @mcp.tool(
            name="litellm_generate_key",
            annotations=writing("Generate key"),
        )
        async def litellm_generate_key(
            ctx: Context,
            key_alias: str | None = None,
            models: list[str] | None = None,
            max_budget: float | None = None,
            user_id: str | None = None,
            team_id: str | None = None,
            duration: str | None = None,
            tpm_limit: int | None = None,
            rpm_limit: int | None = None,
            budget_duration: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> dict:
            """Create a virtual key.

            All parameters are optional; ``duration`` accepts strings like
            ``"30d"`` and ``budget_duration`` resets the budget on that cadence.
            """
            body = prune_none(
                {
                    "key_alias": key_alias,
                    "models": models,
                    "max_budget": max_budget,
                    "user_id": user_id,
                    "team_id": team_id,
                    "duration": duration,
                    "tpm_limit": tpm_limit,
                    "rpm_limit": rpm_limit,
                    "budget_duration": budget_duration,
                    "metadata": metadata,
                }
            )
            return await litellm_client(ctx).post(
                "/key/generate", json_data=body
            )

    if gate.is_tool_enabled("litellm_list_keys"):

        @mcp.tool(
            name="litellm_list_keys",
            annotations=read_only("List keys"),
        )
        async def litellm_list_keys(
            ctx: Context,
            page: int = 1,
            size: int = 50,
            user_id: str | None = None,
            team_id: str | None = None,
            key_alias: str | None = None,
            return_full_object: bool = True,
        ) -> dict:
            """List/paginate virtual keys."""
            params = prune_none(
                {
                    "page": page,
                    "size": size,
                    "user_id": user_id,
                    "team_id": team_id,
                    "key_alias": key_alias,
                    "return_full_object": return_full_object,
                }
            )
            return await litellm_client(ctx).get("/key/list", params=params)

    if gate.is_tool_enabled("litellm_key_info"):

        @mcp.tool(
            name="litellm_key_info",
            annotations=read_only("Key info"),
        )
        async def litellm_key_info(ctx: Context, key: str) -> dict:
            """Get spend, budget and allowed models for one key."""
            return await litellm_client(ctx).get(
                "/key/info", params={"key": key}
            )

    if gate.is_tool_enabled("litellm_update_key"):

        @mcp.tool(
            name="litellm_update_key",
            annotations=writing("Update key"),
        )
        async def litellm_update_key(
            ctx: Context,
            key: str,
            models: list[str] | None = None,
            max_budget: float | None = None,
            tpm_limit: int | None = None,
            rpm_limit: int | None = None,
            budget_duration: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> dict:
            """Update key tunables (budget, models, limits)."""
            body = prune_none(
                {
                    "key": key,
                    "models": models,
                    "max_budget": max_budget,
                    "tpm_limit": tpm_limit,
                    "rpm_limit": rpm_limit,
                    "budget_duration": budget_duration,
                    "metadata": metadata,
                }
            )
            return await litellm_client(ctx).post("/key/update", json_data=body)

    if gate.is_tool_enabled("litellm_delete_key"):

        @mcp.tool(
            name="litellm_delete_key",
            annotations=destructive("Delete key"),
        )
        async def litellm_delete_key(
            ctx: Context,
            keys: list[str] | None = None,
            key_aliases: list[str] | None = None,
        ) -> dict:
            """[DESTRUCTIVE] Delete keys by ``keys[]`` or ``key_aliases[]``.

            Supply at least one of the two lists. Deleted keys stop working
            immediately and cannot be recovered.
            """
            body = prune_none({"keys": keys, "key_aliases": key_aliases})
            return await litellm_client(ctx).post("/key/delete", json_data=body)

    if gate.is_tool_enabled("litellm_block_key"):

        @mcp.tool(
            name="litellm_block_key",
            annotations=destructive("Block key"),
        )
        async def litellm_block_key(ctx: Context, key: str) -> dict:
            """[DESTRUCTIVE] Block a key from making requests."""
            return await litellm_client(ctx).post(
                "/key/block", json_data={"key": key}
            )

    if gate.is_tool_enabled("litellm_unblock_key"):

        @mcp.tool(
            name="litellm_unblock_key",
            annotations=writing("Unblock key"),
        )
        async def litellm_unblock_key(ctx: Context, key: str) -> dict:
            """Re-enable a previously blocked key."""
            return await litellm_client(ctx).post(
                "/key/unblock", json_data={"key": key}
            )

    if gate.is_tool_enabled("litellm_regenerate_key"):

        @mcp.tool(
            name="litellm_regenerate_key",
            annotations=writing("Regenerate key"),
        )
        async def litellm_regenerate_key(
            ctx: Context,
            key: str,
            new_master_key: str | None = None,
        ) -> dict:
            """Rotate the secret of an existing key while preserving its config.

            Returns the new key value; the old value stops working.
            """
            body = prune_none({"new_master_key": new_master_key})
            return await litellm_client(ctx).post(
                f"/key/{key}/regenerate", json_data=body
            )
