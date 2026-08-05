# Screenshots

Every image in this directory was captured from the running deployment on
**5 August 2026** through a headless Chromium session. No mockups, no staged data.

Sources: the admin console at `https://litellm-mcp.woowtech.io` and the LiteLLM
gateway UI at `https://litellm.woowtech.io/ui/`.

| File | Source | Shows |
|---|---|---|
| `icon_base.png` | generated | Repository icon, 480×480, transparent background. |
| `admin_console_login.png` | console `/login` | The only unauthenticated route. |
| `admin_console_dashboard.png` | console `/` | MCP child state: `PID: 93 · Restarts: 14 · running`. |
| `admin_console_tools.png` | console `/tools` | All 40 tools, 8 categories, dangerous ones badged. |
| `admin_console_connection.png` | console `/config` | Gateway target and write-only master key. |
| `admin_console_tokens.png` | console `/tokens` | `mcp_auth_token` generate vs rotate. |
| `admin_console_logs.png` | console `/logs` | SSE ring buffer, `Live · 1504 shown · 1504 buffered`. |
| `admin_console_permissions.png` | console `/permissions` | Category, operation and read-only gates. |
| `admin_console_settings.png` | console `/settings` | Proxy timeout `86400`, child restart control. |
| `litellm_proxy_ui_login.png` | gateway `/ui/` | Gateway's own auth domain, separate from the console's. |
| `litellm_proxy_ui_dashboard.png` | gateway `/ui/` | Virtual-key overview. |
| `litellm_proxy_models.png` | gateway `/ui/` | Five OpenRouter-backed deployments, all healthy. |
| `litellm_proxy_mcp_servers.png` | gateway `/ui/` | LiteLLM's own MCP registry — the inverse direction to this project. |
| `litellm_proxy_usage.png` | gateway `/ui/` | Seven days: $0.0111, 174 requests, 141 success, 7,467 tokens. |
| `litellm_proxy_logs.png` | gateway `/ui/` | Per-request records with model, tokens and cost. |

Each image is embedded in both [`README.md`](../../README.md) and
[`README_zh-TW.md`](../../README_zh-TW.md) with an explanatory caption.

## Recapturing

Screenshots go stale. When recapturing, keep the filenames identical so both READMEs
continue to resolve, capture full-page PNGs at a desktop viewport, and update any
figure quoted in the captions — the restart count, the buffer size, the spend totals
and the health counts are all cited as text in the READMEs and will disagree with a
fresh image otherwise.

Do not capture a page while a secret is revealed. The Tokens page masks
`mcp_auth_token` by default and the Connection page never renders the master key; leave
both in that state.
