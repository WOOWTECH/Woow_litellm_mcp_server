"""Spend / cost-reporting tools (category: spend)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..deps import litellm_client
from ..gating import ToolGate
from ._common import prune_none, read_only


def register(mcp: Any, gate: ToolGate) -> None:
    if gate.is_tool_enabled("litellm_spend_logs"):

        @mcp.tool(
            name="litellm_spend_logs",
            annotations=read_only("Spend logs"),
        )
        async def litellm_spend_logs(
            ctx: Context,
            api_key: str | None = None,
            user_id: str | None = None,
            request_id: str | None = None,
            start_date: str | None = None,
            end_date: str | None = None,
            summarize: bool | None = None,
        ) -> Any:
            """Fetch per-request spend logs.

            Dates are ``YYYY-MM-DD``. Filter by ``api_key``, ``user_id`` or a
            single ``request_id``. Returns a list of spend-log rows.
            """
            params = prune_none(
                {
                    "api_key": api_key,
                    "user_id": user_id,
                    "request_id": request_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "summarize": summarize,
                }
            )
            return await litellm_client(ctx).get("/spend/logs", params=params)

    if gate.is_tool_enabled("litellm_global_spend_report"):

        @mcp.tool(
            name="litellm_global_spend_report",
            annotations=read_only("Global spend report"),
        )
        async def litellm_global_spend_report(
            ctx: Context,
            start_date: str,
            end_date: str,
            group_by: str | None = None,
            api_key: str | None = None,
            internal_user_id: str | None = None,
            team_id: str | None = None,
        ) -> Any:
            """Aggregated spend report over a date range.

            ``group_by`` is one of ``team``/``api_key``/``user``/``customer``.
            Dates are required and formatted ``YYYY-MM-DD``.
            """
            params = prune_none(
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    "group_by": group_by,
                    "api_key": api_key,
                    "internal_user_id": internal_user_id,
                    "team_id": team_id,
                }
            )
            return await litellm_client(ctx).get(
                "/global/spend/report", params=params
            )

    if gate.is_tool_enabled("litellm_spend_calculate"):

        @mcp.tool(
            name="litellm_spend_calculate",
            annotations=read_only("Spend calculate"),
        )
        async def litellm_spend_calculate(
            ctx: Context,
            model: str | None = None,
            messages: list[dict[str, Any]] | None = None,
            completion_response: dict[str, Any] | None = None,
        ) -> dict:
            """Estimate cost without billing.

            Provide either ``model`` + ``messages`` (to price a hypothetical
            request) or a ``completion_response`` (to price a past one).
            """
            body = prune_none(
                {
                    "model": model,
                    "messages": messages,
                    "completion_response": completion_response,
                }
            )
            return await litellm_client(ctx).post(
                "/spend/calculate", json_data=body
            )
