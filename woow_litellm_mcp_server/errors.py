"""Error handling and the low-level LiteLLM request helper.

``litellm_request`` performs an HTTP call against the pooled client and maps the
common failure modes into ``ToolError`` messages that are *actionable for an
LLM*: it names the likely cause (upstream down on port 4000, wrong master key,
not found, validation error) and surfaces the LiteLLM error body verbatim.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

try:  # FastMCP ships ToolError; fall back to a plain exception if absent.
    from fastmcp.exceptions import ToolError
except Exception:  # pragma: no cover - defensive import

    class ToolError(Exception):  # type: ignore[no-redef]
        """Fallback ToolError when fastmcp is unavailable."""


class LiteLLMApiError(ToolError):
    """Raised when the LiteLLM gateway returns an error or is unreachable."""


def _extract_error_body(response: httpx.Response) -> str:
    """Pull a human/LLM-readable error message out of a LiteLLM response."""
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        text = (response.text or "").strip()
        return text or f"HTTP {response.status_code}"

    # LiteLLM/OpenAI error envelope: {"error": {"message": ...}} or {"detail": ...}
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str):
            return err
        if payload.get("detail") is not None:
            detail = payload["detail"]
            return detail if isinstance(detail, str) else json.dumps(detail)
        if payload.get("message"):
            return str(payload["message"])
    return json.dumps(payload)


def json_body(response: httpx.Response) -> Any:
    """Return the JSON body, tolerating 204/empty responses."""
    if response.status_code == 204 or not (response.content or b"").strip():
        return {}
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return {"raw": response.text}


async def litellm_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_data: Any | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP request, mapping transport/HTTP errors to ToolError.

    Returns the raw ``httpx.Response`` on success (2xx); callers use
    :func:`json_body` to decode it.
    """
    # Drop query params that are None so we don't send ?x=None to LiteLLM.
    if params:
        params = {k: v for k, v in params.items() if v is not None}

    try:
        response = await client.request(
            method.upper(),
            path,
            params=params,
            json=json_data,
            **kwargs,
        )
    except httpx.ConnectError as exc:
        raise LiteLLMApiError(
            f"Cannot reach the LiteLLM gateway at {client.base_url!s} "
            f"(connection refused). Is LiteLLM running and listening on "
            f"port 4000? Underlying error: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise LiteLLMApiError(
            f"Request to LiteLLM timed out ({method.upper()} {path}). "
            f"The gateway may be overloaded or the operation too slow. "
            f"Underlying error: {exc}"
        ) from exc
    except httpx.HTTPError as exc:  # pragma: no cover - catch-all transport error
        raise LiteLLMApiError(
            f"HTTP error talking to LiteLLM ({method.upper()} {path}): {exc}"
        ) from exc

    if response.is_success:
        return response

    body = _extract_error_body(response)
    status = response.status_code
    if status == 401:
        raise LiteLLMApiError(
            "LiteLLM rejected the credentials (401 Unauthorized). The "
            "LITELLM_MCP_MASTER_KEY is missing or wrong. Details: " + body
        )
    if status == 403:
        raise LiteLLMApiError(
            "LiteLLM forbade the request (403). The key lacks admin scope "
            "for this operation. Details: " + body
        )
    if status == 404:
        # Lead with the resource interpretation: in practice ~every 404 here is
        # a bad identifier ("Key not found in database"), and telling an LLM the
        # *endpoint* may not exist sends it hunting for a different route or
        # concluding the server is misconfigured.
        raise LiteLLMApiError(
            f"LiteLLM returned 404 Not Found for {method.upper()} {path} — the "
            f"requested resource does not exist; check the identifier you "
            f"passed. (If the identifier is definitely correct, the endpoint "
            f"itself may be unavailable on this gateway.) Details: {body}"
        )
    if status == 422 or status == 400:
        raise LiteLLMApiError(
            f"LiteLLM rejected the request body ({status}). Check the "
            f"parameters. Details: {body}"
        )
    raise LiteLLMApiError(
        f"LiteLLM returned an error ({status}) for {method.upper()} {path}: {body}"
    )
