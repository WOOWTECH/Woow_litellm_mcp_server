# Woow LiteLLM MCP Server（繁體中文）

用於管理 [LiteLLM](https://github.com/BerriAI/litellm) 閘道的 MCP 伺服器**套件**。
本專案將
[`WOOWTECH/Woow_emqx_mcp_server`](https://github.com/WOOWTECH/Woow_emqx_mcp_server)
的架構移植到 LiteLLM：一個把 LiteLLM 管理 API 包成 MCP 工具的 FastMCP 伺服器、一個
Web 管理主控台，以及一個加密反向代理 / admin-core，讓 Claude（或任何 MCP 用戶端）
透過單一強化端點存取這些工具。

English version: [README.md](./README.md)

---

## 套件內容

| 元件 | 套件 | 角色 |
|------|------|------|
| **1. MCP 伺服器** | `woow_litellm_mcp_server` | FastMCP 伺服器，提供 38 個 LiteLLM 工具（stdio 或 Streamable-HTTP）。 |
| **2. 管理主控台** | `litellm_mcp_admin` | FastAPI + React GUI，設定連線、開關工具、輪替代理權杖、即時檢視日誌。 |
| **3. Admin core／加密代理** | `mcp_admin_core` | 與產品無關的核心：JWT 驗證、檔案式設定儲存、MCP 子行程管理，以及擋在 MCP 子行程前面的反向代理。 |
| **4. 前端 SPA** | `frontend/` | 與參考專案共用的 Vite + React 管理介面，含 LiteLLM 覆寫。 |

### 架構

```
                       ┌───────────────────────── 單一容器 ────────────────────────┐
  Claude / MCP 用戶端  │                                                            │
        │              │  uvicorn  litellm_mcp_admin.main:app   (0.0.0.0:8080)      │
        │  HTTPS       │    ├─ AuthMiddleware (JWT)  ── /api/*  管理 GUI + API       │
        ▼              │    ├─ 代理 /private_{token}/mcp/  ──┐                       │
  Cloudflare 邊緣 ─────┼──► └─ SPA (React)                   │ 反向代理（免 nginx）  │
                       │                                     ▼                       │
                       │        McpProcessManager ► woow_litellm_mcp_server (127.0.0.1)
                       │                                     │  transport=http /mcp/ │
                       └──────────────────────────────┼──────────────────────┘
                                                              ▼
                                     LiteLLM 閘道（Bearer master key，port 4000）
```

MCP 子行程只綁定 loopback，唯一入口是代理路由 `/private_{token}/…`，其 `{token}`
必須等於儲存的 `mcp_auth_token`。此處的「加密／私有」指的是
**路徑權杖隔離 + JWT 保護的 GUI + 邊緣 TLS**，並非資料靜態加密；設定 JSON 為明文，
以檔案權限（`chmod 600`）與 API 遮罩機密保護。

---

## 工具清單（38 個）

所有工具皆以 `litellm_` 為前綴。註冊表
（`woow_litellm_mcp_server/registry.py`）是唯一真實來源，閘門與管理 GUI 皆讀取它。

| 類別 | 工具 |
|------|------|
| **models** | `list_models`、`model_info`、`model_group_info`、`add_model`、`update_model`、`delete_model` ⚠ |
| **chat** | `chat_completion`、`token_counter` |
| **keys** | `generate_key`、`list_keys`、`key_info`、`update_key`、`delete_key` ⚠、`block_key` ⚠、`unblock_key`、`regenerate_key` |
| **teams** | `create_team`、`list_teams`、`team_info`、`update_team`、`delete_team` ⚠、`team_member_add`、`team_member_delete` ⚠ |
| **users** | `create_user`、`list_users`、`user_info`、`update_user`、`delete_user` ⚠ |
| **spend** | `spend_logs`、`global_spend_report`、`spend_calculate` |
| **health** | `health`、`health_readiness` |
| **plugins**（Claude-Code skill hub） | `list_plugins`、`register_plugin`、`enable_plugin`、`disable_plugin`、`skill_hub` |

⚠ = 破壞性操作（docstring 以 `[DESTRUCTIVE]` 開頭）。唯讀模式
（`LITELLM_MCP_READONLY=true`）會在註冊階段丟棄所有破壞性工具。

### 工具閘門

三個層級加上唯讀，皆由環境變數驅動（或由 GUI 設定）：

- `LITELLM_MCP_DISABLED_CATEGORIES` — 停用整個類別（`keys,teams`）。
- `LITELLM_MCP_DISABLED_TOOLS` — 停用個別工具（`litellm_delete_key`）。
- `LITELLM_MCP_DISABLED_OPERATIONS` — 停用 CRUD 操作（`tool:op` 或純 `op`）。
- `LITELLM_MCP_READONLY` — 停用所有會變更資料的工具。

---

## 快速開始

### 1. 純 MCP 伺服器（本機，stdio 或 HTTP）

```bash
pip install .                      # 僅安裝元件 1
export LITELLM_MCP_BASE_URL=http://localhost:4000
export LITELLM_MCP_MASTER_KEY=sk-...      # 切勿提交至版本控制

# Streamable-HTTP（部署預設）：
python -m woow_litellm_mcp_server.server --transport http --host 0.0.0.0 --port 8000 --path /mcp/

# 或以 stdio 供本機 MCP 用戶端使用：
python -m woow_litellm_mcp_server.server --transport stdio
```

設定由環境變數讀取（`LITELLM_MCP_` 前綴），參見 [`.env.example`](./.env.example)。

### 2. 以 Docker Compose 執行管理主控台

```bash
cp .env.example .env               # 設定 JWT_SECRET、LITELLM_MCP_* 等
docker compose up --build          # GUI 服務於 http://localhost:8080
```

Compose 服務會先建置 SPA（第一階段）與 Python 映像（第二階段），再於 `:8080`
提供 `litellm_mcp_admin.main:app`。以設定儲存中的 `admin_password` 登入
（預設 `admin`，首次登入請更換），在**連線**頁指向你的 LiteLLM 閘道，並於**工具**頁
開關工具。

### 3. Kubernetes（k3s，git-clone 模式—免建置映像）

實際部署採用 `initContainer` 將此**公開**倉庫 clone 到 `emptyDir`；主容器
`python:3.12-slim` 會 `pip install` 後以 Streamable-HTTP 啟動伺服器，無需私有
registry。詳見 [`k8s-deploy.yaml`](./k8s-deploy.yaml)（同時記錄了映像式路徑）。

```bash
# 1) namespace + secret（master key 只存在 Secret，絕不進倉庫）
kubectl apply -f k8s-secret.example.yaml       # 填入真實金鑰後
# 2) deployment + service
kubectl apply -f k8s-deploy.yaml
```

叢集內消費者即可透過
`http://litellm-mcp.litellm-mcp.svc.cluster.local:8000/mcp/` 存取。

---

## 連接 Claude

將 MCP 端點加入自訂連接器。透過管理代理，URL 為：

```
https://<你的管理主機名>/private_<mcp_auth_token>/mcp/
```

於**Tokens**頁輪替 `mcp_auth_token`（或呼叫
`POST /api/settings/mcp_auth_token/rotate`）。可選擇以 [`cloudflare/`](./cloudflare/)
中的 Cloudflare Worker 為 MCP 端點提供獨立主機名，並對 OAuth 探索提供乾淨的匿名
回退。

---

## 設定參考

所有伺服器設定使用 `LITELLM_MCP_` 前綴（`woow_litellm_mcp_server/settings.py`）：

| 環境變數 | 預設 | 說明 |
|----------|------|------|
| `LITELLM_MCP_BASE_URL` | `http://localhost:4000` | LiteLLM 閘道基底 URL（無 `/api/v5`）。 |
| `LITELLM_MCP_MASTER_KEY` | _(空)_ | Bearer master／admin 金鑰。 |
| `LITELLM_MCP_READONLY` | `false` | 丟棄所有破壞性工具。 |
| `LITELLM_MCP_DISABLED_CATEGORIES` | _(空)_ | 要停用的類別（CSV）。 |
| `LITELLM_MCP_DISABLED_TOOLS` | _(空)_ | 要停用的工具名（CSV）。 |
| `LITELLM_MCP_DISABLED_OPERATIONS` | _(空)_ | `tool:op` / `op` 閘門（CSV）。 |
| `LITELLM_MCP_DEFAULT_LIMIT` | `50` | 預設分頁大小。 |
| `LITELLM_MCP_MAX_LIMIT` | `500` | 最大分頁大小。 |
| `LITELLM_MCP_REQUEST_TIMEOUT` | `60` | 每次請求逾時（秒）。 |

管理主控台設定：`MCP_ADMIN_CONFIG`（設定檔路徑）、`JWT_SECRET`、
`JWT_EXPIRY_HOURS`。

---

## 開發與測試

```bash
pip install -e ".[admin,test]"
pytest                     # 單元測試（預設排除線上探測）
pytest -m live             # 選擇性：需要可連線的 LiteLLM 閘道
```

測試會模擬 LiteLLM 的 HTTP API，驗證每個工具建立正確的請求並正確解析回應；
註冊表↔工具的不變式測試確保工具介面一致。詳見
[CONTRIBUTING.md](./CONTRIBUTING.md)。

## 授權

[MIT](./LICENSE)
