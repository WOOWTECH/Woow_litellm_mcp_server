# syntax=docker/dockerfile:1
#
# Woow LiteLLM MCP Admin — production image
# ==========================================
# Two-stage build, mirroring the EMQX reference:
#
#   stage 1 (node:20)         builds the React/Vite SPA, applies the LiteLLM
#                             ConnectionConfig override, and rewrites a handful
#                             of product strings (EMQX -> LiteLLM) so the shared
#                             frontend renders LiteLLM branding.
#   stage 2 (python:3.12-slim) installs the mcp-admin-core wheel first, then the
#                             product package with the [admin] extra, copies the
#                             built SPA into the static dir, and serves the admin
#                             console (which spawns the FastMCP child) on :8080.
#
# The single published image runs the admin console + encrypted proxy + the
# FastMCP child as one unit:
#
#   docker build -t ghcr.io/woowtech/woow-litellm-mcp-admin:latest .
#   docker run -p 8080:8080 -e JWT_SECRET=... -v litellm_mcp_data:/data \
#       ghcr.io/woowtech/woow-litellm-mcp-admin:latest
#
# NOTE: no secrets are baked into the image. LITELLM connection details are
# supplied at runtime via the Admin GUI / ConfigStore (/data/config.json) or the
# LITELLM_MCP_* environment variables, and JWT_SECRET is injected at run time.

# ---------------------------------------------------------------------------
# Stage 1 — build the SPA
# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /build

# Install deps first for better layer caching.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

# Bring in the shared SPA sources.
COPY frontend/ ./

# Apply the LiteLLM-specific ConnectionConfig override (single Bearer secret,
# no key/secret pair) on top of the shared page before building.
COPY frontend-overrides/ConnectionConfig.jsx ./src/pages/ConnectionConfig.jsx

# Rewrite residual product strings in the shared SPA so it reads as LiteLLM.
# Safe, idempotent, and limited to user-visible copy.
RUN set -eux; \
    find ./src -type f \( -name '*.jsx' -o -name '*.js' \) -print0 \
      | xargs -0 sed -i \
          -e 's/EMQX MCP Admin/LiteLLM MCP Admin/g' \
          -e 's/EMQX Broker/LiteLLM Gateway/g' \
          -e 's/\bEMQX\b/LiteLLM/g'

RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — python runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Non-interactive, no .pyc, unbuffered logs (so SSE log streaming is live).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MCP_ADMIN_CONFIG=/data/config.json

WORKDIR /app

# Install the shared admin-core package FIRST (its own pyproject), so the
# product install resolves against the already-present core.
COPY mcp_admin_core.pyproject.toml ./pyproject.toml
COPY mcp_admin_core/ ./mcp_admin_core/
RUN pip install .

# Now install the product packages (FastMCP server + admin layer) with the
# [admin] extra (fastapi/uvicorn/pyjwt/httpx).
COPY pyproject.toml ./pyproject.toml
COPY woow_litellm_mcp_server/ ./woow_litellm_mcp_server/
COPY litellm_mcp_admin/ ./litellm_mcp_admin/
RUN pip install ".[admin]"

# Copy the built SPA into the static dir the admin app serves from.
COPY --from=frontend /build/dist/ ./litellm_mcp_admin/static/

# Config lives on a volume; seed dir exists so first-run write succeeds.
RUN mkdir -p /data && chmod 700 /data
VOLUME ["/data"]

# The admin console listens on 8080. The FastMCP child is spawned by the
# McpProcessManager and bound to loopback only — never exposed here.
EXPOSE 8080

# Basic liveness: the admin app exposes an unauthenticated /healthz.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3).status==200 else 1)"

CMD ["uvicorn", "litellm_mcp_admin.main:app", "--host", "0.0.0.0", "--port", "8080"]
