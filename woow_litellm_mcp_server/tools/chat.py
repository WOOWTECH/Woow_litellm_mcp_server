"""Chat / inference tools (category: chat)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..deps import litellm_client
from ..gating import ToolGate
from ._common import prune_none, read_only, writing


def register(mcp: Any, gate: ToolGate) -> None:
    if gate.is_tool_enabled("litellm_chat_completion"):

        @mcp.tool(
            name="litellm_chat_completion",
            annotations=writing("Chat completion"),
        )
        async def litellm_chat_completion(
            ctx: Context,
            model: str,
            messages: list[dict[str, Any]],
            temperature: float | None = None,
            max_tokens: int | None = None,
            top_p: float | None = None,
            stream: bool = False,
            extra_body: dict[str, Any] | None = None,
        ) -> dict:
            """Run an OpenAI-compatible chat completion through LiteLLM.

            ``messages`` is the OpenAI chat array (``[{"role", "content"}]``).
            ``stream`` is accepted for parity but the tool returns the full JSON
            response (the proxy handles true streaming for connectors).
            """
            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": bool(stream),
            }
            body.update(
                prune_none(
                    {
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "top_p": top_p,
                    }
                )
            )
            if extra_body:
                body.update(extra_body)
            return await litellm_client(ctx).post(
                "/v1/chat/completions", json_data=body
            )

    if gate.is_tool_enabled("litellm_token_counter"):

        @mcp.tool(
            name="litellm_token_counter",
            annotations=read_only("Token counter"),
        )
        async def litellm_token_counter(
            ctx: Context,
            model: str,
            prompt: str | None = None,
            messages: list[dict[str, Any]] | None = None,
        ) -> dict:
            """Count prompt/message tokens for a model without inference.

            Provide either ``prompt`` (a raw string) or ``messages`` (the chat
            array). Returns the token count and the tokenizer used.
            """
            body = prune_none(
                {"model": model, "prompt": prompt, "messages": messages}
            )
            return await litellm_client(ctx).post(
                "/utils/token_counter", json_data=body
            )
