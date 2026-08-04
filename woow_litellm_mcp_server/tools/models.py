"""Model-management tools (category: models)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..deps import litellm_client
from ..gating import ToolGate
from ._common import destructive, prune_none, read_only, writing


def register(mcp: Any, gate: ToolGate) -> None:
    if gate.is_tool_enabled("litellm_list_models"):

        @mcp.tool(
            name="litellm_list_models",
            annotations=read_only("List models"),
        )
        async def litellm_list_models(ctx: Context) -> dict:
            """List all models registered in the LiteLLM gateway.

            Returns the OpenAI-style envelope ``{"data": [{"id": ...}]}``.
            """
            return await litellm_client(ctx).get("/v1/models")

    if gate.is_tool_enabled("litellm_model_info"):

        @mcp.tool(
            name="litellm_model_info",
            annotations=read_only("Model info"),
        )
        async def litellm_model_info(
            ctx: Context, litellm_model_id: str | None = None
        ) -> dict:
            """Full deployment detail per model.

            Provider, ``litellm_params`` and ``model_info`` for each deployment.
            Optionally filter to a single deployment by ``litellm_model_id``.
            """
            params = prune_none({"litellm_model_id": litellm_model_id})
            return await litellm_client(ctx).get("/model/info", params=params)

    if gate.is_tool_enabled("litellm_model_group_info"):

        @mcp.tool(
            name="litellm_model_group_info",
            annotations=read_only("Model group info"),
        )
        async def litellm_model_group_info(
            ctx: Context, model_group: str | None = None
        ) -> dict:
            """Aggregated per-model-group capabilities (context window, modes)."""
            params = prune_none({"model_group": model_group})
            return await litellm_client(ctx).get(
                "/model_group/info", params=params
            )

    if gate.is_tool_enabled("litellm_add_model"):

        @mcp.tool(
            name="litellm_add_model",
            annotations=writing("Add model"),
        )
        async def litellm_add_model(
            ctx: Context,
            model_name: str,
            litellm_params: dict[str, Any],
            model_info: dict[str, Any] | None = None,
        ) -> dict:
            """Register a new model deployment.

            ``litellm_params`` holds at least ``{"model": ..., "api_base": ...,
            "api_key": ...}``; ``model_info`` carries optional metadata.
            """
            body = prune_none(
                {
                    "model_name": model_name,
                    "litellm_params": litellm_params,
                    "model_info": model_info,
                }
            )
            return await litellm_client(ctx).post("/model/new", json_data=body)

    if gate.is_tool_enabled("litellm_update_model"):

        @mcp.tool(
            name="litellm_update_model",
            annotations=writing("Update model"),
        )
        async def litellm_update_model(
            ctx: Context,
            model_id: str,
            litellm_params: dict[str, Any] | None = None,
            model_info: dict[str, Any] | None = None,
        ) -> dict:
            """Update an existing deployment (updateDeployment body)."""
            body = prune_none(
                {
                    "model_id": model_id,
                    "litellm_params": litellm_params,
                    "model_info": model_info,
                }
            )
            return await litellm_client(ctx).post(
                "/model/update", json_data=body
            )

    if gate.is_tool_enabled("litellm_delete_model"):

        @mcp.tool(
            name="litellm_delete_model",
            annotations=destructive("Delete model"),
        )
        async def litellm_delete_model(ctx: Context, model_id: str) -> dict:
            """[DESTRUCTIVE] Remove a model deployment by id.

            This unregisters the deployment from the gateway; it cannot be
            undone without re-adding the model.
            """
            return await litellm_client(ctx).post(
                "/model/delete", json_data={"id": model_id}
            )
