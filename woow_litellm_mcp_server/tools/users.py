"""Internal-user management tools (category: users)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..deps import litellm_client
from ..gating import ToolGate
from ._common import destructive, prune_none, read_only, writing


def register(mcp: Any, gate: ToolGate) -> None:
    if gate.is_tool_enabled("litellm_create_user"):

        @mcp.tool(
            name="litellm_create_user",
            annotations=writing("Create user"),
        )
        async def litellm_create_user(
            ctx: Context,
            user_email: str | None = None,
            user_id: str | None = None,
            user_role: str | None = None,
            teams: list[str] | None = None,
            models: list[str] | None = None,
            max_budget: float | None = None,
            auto_create_key: bool = True,
        ) -> dict:
            """Create an internal user.

            ``user_role`` is one of LiteLLM's roles (e.g. ``internal_user``,
            ``proxy_admin``). When ``auto_create_key`` is true a key is minted.
            """
            body = prune_none(
                {
                    "user_email": user_email,
                    "user_id": user_id,
                    "user_role": user_role,
                    "teams": teams,
                    "models": models,
                    "max_budget": max_budget,
                    "auto_create_key": auto_create_key,
                }
            )
            return await litellm_client(ctx).post("/user/new", json_data=body)

    if gate.is_tool_enabled("litellm_list_users"):

        @mcp.tool(
            name="litellm_list_users",
            annotations=read_only("List users"),
        )
        async def litellm_list_users(
            ctx: Context,
            page: int = 1,
            page_size: int = 50,
            role: str | None = None,
            user_ids: list[str] | None = None,
        ) -> dict:
            """List/paginate users."""
            params = prune_none(
                {
                    "page": page,
                    "page_size": page_size,
                    "role": role,
                    "user_ids": ",".join(user_ids) if user_ids else None,
                }
            )
            return await litellm_client(ctx).get("/user/list", params=params)

    if gate.is_tool_enabled("litellm_user_info"):

        @mcp.tool(
            name="litellm_user_info",
            annotations=read_only("User info"),
        )
        async def litellm_user_info(ctx: Context, user_id: str) -> dict:
            """Get one user's teams, keys, budget and spend by user_id."""
            return await litellm_client(ctx).get(
                "/user/info", params={"user_id": user_id}
            )

    if gate.is_tool_enabled("litellm_update_user"):

        @mcp.tool(
            name="litellm_update_user",
            annotations=writing("Update user"),
        )
        async def litellm_update_user(
            ctx: Context,
            user_id: str,
            user_role: str | None = None,
            max_budget: float | None = None,
            teams: list[str] | None = None,
            models: list[str] | None = None,
        ) -> dict:
            """Update user role/budget/teams/models."""
            body = prune_none(
                {
                    "user_id": user_id,
                    "user_role": user_role,
                    "max_budget": max_budget,
                    "teams": teams,
                    "models": models,
                }
            )
            return await litellm_client(ctx).post("/user/update", json_data=body)

    if gate.is_tool_enabled("litellm_delete_user"):

        @mcp.tool(
            name="litellm_delete_user",
            annotations=destructive("Delete user"),
        )
        async def litellm_delete_user(ctx: Context, user_ids: list[str]) -> dict:
            """[DESTRUCTIVE] Delete users by ``user_ids[]``.

            Also removes the users' keys; the action is irreversible.
            """
            return await litellm_client(ctx).post(
                "/user/delete", json_data={"user_ids": user_ids}
            )
