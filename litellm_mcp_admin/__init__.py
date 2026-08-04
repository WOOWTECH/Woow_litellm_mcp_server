"""LiteLLM MCP Admin — GUI, admin API and MCP proxy on a single port.

The heavy lifting lives in the product-agnostic ``mcp_admin_core`` package
(FastAPI factory, JWT middleware, config store, subprocess manager, MCP reverse
proxy). This package only contributes the thin LiteLLM-specific layer: the
connection/health/tool routers and the tool-switch persistence that translate
between the Admin GUI and ``woow_litellm_mcp_server``.
"""

__version__ = "0.1.0"
