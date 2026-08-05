# Architecture

Supplementary design notes for `Woow_litellm_mcp_server`. The README carries the
high-level diagrams; this document records the reasoning behind them and the details
that would clutter a landing page.

---

## 1. Why a registry instead of decorators

The obvious way to build a FastMCP server is to decorate each function with
`@mcp.tool()` and let the decorator be the source of truth. This project deliberately
does not do that. Instead, `woow_litellm_mcp_server/registry.py` holds 40 frozen
`ToolSpec` records and `server.py` walks that list at startup, consulting `gating.py`
before registering anything.

The cost is one extra indirection. The benefits are three.

**Gating becomes declarative.** A gate is a predicate over `ToolSpec` fields —
category, operations tuple, dangerous flag, name. With decorators the gate would have
to be re-implemented as a runtime check inside every tool body, which is both
repetitive and weaker (see §3).

**The GUI cannot drift.** `litellm_mcp_admin/tool_registry.py` re-exports the server's
registry verbatim, adding only two lookup helpers. The console renders one switch per
`ToolSpec`, so a tool added to the server appears in the GUI with no frontend change,
and a tool removed from the server disappears. `tests/test_mcp_surface.py` asserts the
two sets are equal and fails the build otherwise.

**Documentation can be generated.** The 40-row table in the README was produced by
importing `TOOL_REGISTRY` and formatting it, not by hand. That is precisely the defect
recorded as FINDING-001: the previous hand-maintained count said 38 while the registry
held 40.

### The ToolSpec contract

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                    # litellm_delete_key
    category: ToolCategory       # ToolCategory.KEYS
    description: str             # "[DESTRUCTIVE] Delete a virtual key…"
    method: str                  # POST
    path: str                    # /key/delete
    operations: tuple[str, ...]  # ("delete",)
    dangerous: bool              # True
```

`operations` is a tuple rather than a scalar because a handful of tools legitimately
span two verbs — `litellm_regenerate_key`, for instance, is an `update` on the key
record but has the practical effect of invalidating the previous secret. Keeping it a
tuple means `LITELLM_MCP_DISABLED_OPERATIONS=delete` can be evaluated as a set
intersection with no special cases.

`dangerous` is separate from `operations` on purpose. Not every mutation is dangerous
(`litellm_update_model` is routine) and not every dangerous tool is a delete
(`litellm_block_key` is an update that takes a key out of service). Collapsing the two
into one field would force a wrong answer in both directions.

---

## 2. The four gating axes

| Axis | Environment variable | Matches on |
|---|---|---|
| Category | `LITELLM_MCP_DISABLED_CATEGORIES` | `spec.category` |
| Tool | `LITELLM_MCP_DISABLED_TOOLS` | `spec.name` |
| Operation | `LITELLM_MCP_DISABLED_OPERATIONS` | `spec.operations`, as `tool:op` or bare `op` |
| Read-only | `LITELLM_MCP_READONLY` | `spec.operations != ("read",)` |

The axes compose by intersection: a tool is registered only if it survives all four.
There is no allow-list axis, which is a deliberate omission — an allow-list that
silently drops a newly added tool would fail closed in a way that looks like a bug, and
the composition of an allow-list with four deny-lists has no obvious semantics.

The `tool:op` form of the operation gate exists for the case where an operation should
be blocked on one tool but permitted on another —
`LITELLM_MCP_DISABLED_OPERATIONS=litellm_delete_model:delete` removes model deletion
while leaving key deletion available.

---

## 3. Registration-time gating beats call-time refusal

This is the single most important design decision in the project, so it is worth
stating carefully.

A call-time check looks like this:

```python
async def litellm_delete_key(key: str):
    if not gate.allows("litellm_delete_key"):
        raise ToolError("This tool is disabled")
    ...
```

The tool is still advertised in `tools/list`. The model sees it, may plan around it,
and a sufficiently persistent prompt injection can spend turns trying to talk the agent
into invoking it. The refusal is a wall the model can see and push against.

Registration-time gating produces a different world: the tool is never registered, so
`tools/list` never mentions it, and a `tools/call` naming it fails as an unknown tool.
The model has no concept of the capability at all. There is nothing to be talked into.

The cost is that changing a gate requires restarting the MCP child, which is why the
console's Settings page exposes a restart button and why the Permissions page says
changes apply on next restart. That is a real ergonomic cost, accepted knowingly.

`tests/test_gated_tool_message.py` pins this behaviour: it asserts that a gated tool is
absent from the listed tool set, not that calling it returns a permission error.

---

## 4. Why the token lives in the path

The public MCP endpoint is `/private_<mcp_auth_token>/mcp/`. An obvious alternative is
`?token=<mcp_auth_token>` or an `Authorization` header.

A header would be cleaner but is not universally available: some MCP client
configurations accept only a URL, with no place to attach custom headers. That
constraint is what forces the secret into the URL.

Given that it must be in the URL, path beats query string because uvicorn's access log
writes the full request line — `GET /path?token=abc HTTP/1.1` — into every log entry.
A query-string secret would be duplicated into the log ring buffer, which is then
streamed to the console's Logs page over SSE, which is then potentially screenshotted.
The path form has the same theoretical exposure, but the proxy strips the private
prefix before the inner request is logged, so the token does not reach the buffer.

A mismatched token returns `404`, identical to a nonexistent path. Probing therefore
reveals nothing: an attacker cannot distinguish "wrong token" from "no such endpoint",
so the endpoint's existence is not confirmable without the token itself.

---

## 5. Process supervision

`mcp_admin_core/process.py` owns the MCP child's lifecycle. The child is spawned as a
subprocess with `--transport http --host 127.0.0.1`, and the manager tracks its PID and
a cumulative restart count, both surfaced on the dashboard.

The restart count is cumulative for the pod's lifetime rather than reset on success,
because a child that restarts every few minutes and a child that has been stable for a
week look identical under a resetting counter. At the time of the README capture the
live value was 14 restarts against a PID of 93 — a pod that has been through a number
of configuration changes, each of which restarts the child by design.

The proxy's upstream timeout is stored in the config (not the environment) and is set
to 86,400 seconds on the live deployment. MCP sessions over Streamable-HTTP are
long-lived; a conventional 60-second gateway timeout would sever a session mid-tool-call.

---

## 6. Why `Recreate` and why `exit 0`

Two Kubernetes choices that look wrong at first glance.

**`strategy: Recreate`.** The deployment mounts a `ReadWriteOnce` PVC at `/data`. Under
`RollingUpdate`, Kubernetes starts the new pod before terminating the old one; the new
pod cannot mount the PVC because the old one still holds it, so the rollout deadlocks
until the readiness timeout. `Recreate` takes the old pod down first, accepting a brief
outage in exchange for a rollout that actually completes. This was BUG-3.

**`spa-build` ends in `exit 0`.** The SPA build runs in an init container on
`node:20-alpine`. If `npm run build` fails — a transient registry error, a dependency
resolution hiccup — a non-zero exit puts the pod in `Init:CrashLoopBackOff` and the
entire admin console, including the MCP proxy that clients depend on, goes down because
of a frontend problem. Ending in `exit 0` means a failed build leaves the previously
committed `frontend/dist/` in place: the console serves a slightly stale UI, and the
MCP endpoint keeps working. Availability of the proxy is worth more than freshness of
the UI. This was BUG-4.

The related trade-off is that a build failure is silent. It shows up in the init
container's logs and nowhere else, so a deploy that "worked" but shipped a stale SPA is
possible. That is the accepted cost.

---

## 7. Authentication in two places at once

The console issues a JWT on `POST /api/auth/login` and simultaneously sets an httpOnly
cookie with the same value. The SPA stores the JWT in `localStorage` under
`mcp-admin-token` and sends it as a bearer header on normal API calls.

The duplication exists for the log stream. `EventSource` — the browser API for SSE —
cannot set custom headers. The two options are to put the JWT in the query string, or
to use `withCredentials: true` and let the browser send the cookie. The first option
writes the JWT into uvicorn's access log for every reconnect; that was BUG-1. The
second requires the cookie, hence the duplication.

`POST /api/auth/logout` expires the cookie, so logging out invalidates the SSE path
even if the `localStorage` copy survives.

---

## 8. Cross-namespace routing

The gateway lives in namespace `litellm`; the MCP suite lives in `litellm-mcp`. The
suite reaches the gateway at `litellm.litellm.svc.cluster.local:4000` — cluster-internal
DNS, so the traffic never leaves the cluster even though both services also have public
Cloudflare tunnels.

Keeping them in separate namespaces means the MCP suite can be redeployed, restarted or
broken without touching the gateway. That separation is load-bearing: the gateway serves
production model traffic, and an experimental change to the MCP layer must not be able
to take it down.

---

## Related documents

- [`encrypted-proxy.md`](./encrypted-proxy.md) — proxy design, verification commands and
  the Cloudflare Bot Fight Mode caveat.
- [`deployment.md`](./deployment.md) — step-by-step deployment and operational runbook.
- [`tool-catalog.md`](./tool-catalog.md) — the 40 tools with parameters and danger notes.
