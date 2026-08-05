# Tool catalogue

All 40 tools, generated from `woow_litellm_mcp_server/registry.py`. Every name carries
the `litellm_` prefix. This document is the long form of the README's API Reference
table: it adds what each tool is for and, where relevant, what to be careful about.

**Totals:** 40 tools · 8 categories · 18 read-only · 8 dangerous.

Dangerous tools are marked ⚠ and carry a `[DESTRUCTIVE]` docstring prefix that MCP
clients surface to the model before invocation.

---

## models — 6 tools

Model deployments registered on the gateway. On the live deployment there are five, all
routed through OpenRouter.

| Tool | Method · Path | Ops | Purpose |
|---|---|---|---|
| `litellm_list_models` | GET `/v1/models` | read | OpenAI-compatible model list. The cheapest way to check what the gateway serves. |
| `litellm_model_info` | GET `/model/info` | read | Full deployment records: upstream target, pricing, context window, capability flags. |
| `litellm_model_group_info` | GET `/model_group/info` | read | Grouped view when several deployments share a public model name for load balancing. |
| `litellm_add_model` | POST `/model/new` | create | Register a new deployment. Requires the upstream provider credentials to already exist on the gateway. |
| `litellm_update_model` | POST `/model/update` | update | Change an existing deployment's parameters. |
| `litellm_delete_model` ⚠ | POST `/model/delete` | delete | Remove a deployment. Any key or team scoped to that model name starts failing immediately. |

---

## chat — 2 tools

| Tool | Method · Path | Ops | Purpose |
|---|---|---|---|
| `litellm_chat_completion` | POST `/v1/chat/completions` | create | Run an OpenAI-compatible completion through the gateway. This is the only tool that costs money. |
| `litellm_token_counter` | POST `/utils/token_counter` | read | Count tokens for a payload against a given model's tokenizer, without calling the provider. |

`litellm_chat_completion` is classified `create` rather than `read` because it produces
a billable spend record. Gating on `create` therefore removes the ability to spend money
while leaving every inspection tool intact — a useful configuration for an
audit-only agent.

---

## keys — 8 tools

Virtual keys are the gateway's unit of access control: each carries budgets, model
allow-lists and a team association.

| Tool | Method · Path | Ops | Purpose |
|---|---|---|---|
| `litellm_generate_key` | POST `/key/generate` | create | Mint a virtual key. The secret is returned once and cannot be retrieved afterwards. |
| `litellm_list_keys` | GET `/key/list` | read | Enumerate keys with their metadata (never their secrets). |
| `litellm_key_info` | GET `/key/info` | read | One key's budget, spend, model scope and team. |
| `litellm_update_key` | POST `/key/update` | update | Change budget, aliases, model scope or expiry. |
| `litellm_delete_key` ⚠ | POST `/key/delete` | delete | Permanently remove a key. Not reversible; the holder loses access instantly. |
| `litellm_block_key` ⚠ | POST `/key/block` | update | Suspend a key without deleting it. Reversible via unblock, but immediately cuts off the holder. |
| `litellm_unblock_key` | POST `/key/unblock` | update | Restore a blocked key. |
| `litellm_regenerate_key` ⚠ | POST `/key/{key}/regenerate` | update | Issue a new secret for an existing key record. The old secret dies immediately — every consumer must be updated. |

`litellm_regenerate_key` is the subtle one. It is an `update` operation, so an
operations gate on `delete` will not stop it, yet its practical effect on a running
system is as disruptive as deletion. That is exactly why `dangerous` is a separate
field from `operations`.

---

## teams — 7 tools

| Tool | Method · Path | Ops | Purpose |
|---|---|---|---|
| `litellm_create_team` | POST `/team/new` | create | Create a team with its own budget and model scope. |
| `litellm_list_teams` | GET `/v2/team/list` | read | Enumerate teams. Note the `/v2` path — the v1 endpoint is deprecated upstream. |
| `litellm_team_info` | GET `/team/info` | read | One team's members, budget and spend. |
| `litellm_update_team` | POST `/team/update` | update | Change budget, model scope or metadata. |
| `litellm_delete_team` ⚠ | POST `/team/delete` | delete | Remove a team. Keys scoped to it are affected. |
| `litellm_team_member_add` | POST `/team/member_add` | create | Add a user to a team. |
| `litellm_team_member_delete` ⚠ | POST `/team/member_delete` | delete | Remove a user from a team, revoking their access through it. |

---

## users — 5 tools

| Tool | Method · Path | Ops | Purpose |
|---|---|---|---|
| `litellm_create_user` | POST `/user/new` | create | Create an internal user, optionally with a key and budget. |
| `litellm_list_users` | GET `/user/list` | read | Enumerate users. |
| `litellm_user_info` | GET `/user/info` | read | One user's teams, keys and spend. |
| `litellm_update_user` | POST `/user/update` | update | Change role, budget or metadata. |
| `litellm_delete_user` ⚠ | POST `/user/delete` | delete | Remove a user and their associated access. |

---

## spend — 3 tools

| Tool | Method · Path | Ops | Purpose |
|---|---|---|---|
| `litellm_spend_logs` | GET `/spend/logs` | read | Per-request spend records, filterable by key, user or time range. |
| `litellm_global_spend_report` | GET `/spend/logs` | read | Aggregated report over the same endpoint with reporting parameters. |
| `litellm_spend_calculate` | POST `/spend/calculate` | read | Price a hypothetical payload without executing it. |

`litellm_spend_calculate` is a POST that is classified `read`: it sends a body but
changes nothing and produces no spend record. Classifying it by HTTP verb rather than
by effect would wrongly remove it under an operations gate on `create`.

Both spend tools share the `/spend/logs` path with different parameter shapes; they are
separate tools because the aggregate and per-request views have genuinely different
response schemas and a single tool would need a mode flag the model would get wrong.

---

## health — 2 tools

| Tool | Method · Path | Ops | Purpose |
|---|---|---|---|
| `litellm_health` | GET `/health` | read | Per-deployment health. Returns `healthy_count` / `unhealthy_count` and the failing endpoints. |
| `litellm_health_readiness` | GET `/health/readiness` | read | Gateway-level readiness. Cheaper than `/health`, which probes every upstream. |

The console's Connection page uses `/health/readiness` for its probe button precisely
because it does not fan out to every provider — a configuration typo should surface in
milliseconds, not after five upstream round-trips.

At the time of the README capture the live gateway reported `healthy_count: 5,
unhealthy_count: 0`.

---

## plugins — 7 tools

The Claude-Code skill hub: LiteLLM v1.83.x can serve plugin and skill manifests to
Claude Code clients, and these tools curate that catalogue.

| Tool | Method · Path | Ops | Purpose |
|---|---|---|---|
| `litellm_list_plugins` | GET `/claude-code/plugins` | read | Registered plugins and their enabled state. |
| `litellm_plugin_info` | GET `/claude-code/plugins/{plugin_name}` | read | One plugin's manifest. |
| `litellm_register_plugin` | POST `/claude-code/plugins` | create | Add a plugin to the hub. |
| `litellm_delete_plugin` ⚠ | DELETE `/claude-code/plugins/{plugin_name}` | delete | Remove a plugin from the hub. |
| `litellm_enable_plugin` | POST `/claude-code/plugins/{plugin_name}/enable` | update | Make a registered plugin available to clients. |
| `litellm_disable_plugin` | POST `/claude-code/plugins/{plugin_name}/disable` | update | Withdraw it without deleting the registration. |
| `litellm_skill_hub` | GET `/public/skill_hub` | read | The public hub manifest as clients see it. |

`litellm_delete_plugin` is the only tool in the registry using the HTTP `DELETE` verb;
every other destructive operation goes through a `POST` to an explicit `/delete` path,
which is LiteLLM's own convention.

`litellm_plugin_info` and `litellm_delete_plugin` are the two tools that were added
after the README's hand-maintained count was written, which is how the documented total
came to say 38 against a registry of 40 (FINDING-001).

---

## Read-only subset

Setting `LITELLM_MCP_READONLY=true` leaves exactly these 18 tools registered:

`litellm_list_models`, `litellm_model_info`, `litellm_model_group_info`,
`litellm_token_counter`, `litellm_list_keys`, `litellm_key_info`, `litellm_list_teams`,
`litellm_team_info`, `litellm_list_users`, `litellm_user_info`, `litellm_spend_logs`,
`litellm_global_spend_report`, `litellm_spend_calculate`, `litellm_health`,
`litellm_health_readiness`, `litellm_list_plugins`, `litellm_plugin_info`,
`litellm_skill_hub`.

This is the recommended configuration for any agent whose job is monitoring, cost
reporting or incident triage. It cannot spend money, cannot change access, and cannot
remove anything.

---

## Dangerous subset

The eight tools that carry the `[DESTRUCTIVE]` prefix:

`litellm_delete_model`, `litellm_delete_key`, `litellm_block_key`,
`litellm_regenerate_key`, `litellm_delete_team`, `litellm_team_member_delete`,
`litellm_delete_user`, `litellm_delete_plugin`.

To remove them while keeping the rest of the mutating surface:

```bash
export LITELLM_MCP_DISABLED_TOOLS=litellm_delete_model,litellm_delete_key,litellm_block_key,litellm_regenerate_key,litellm_delete_team,litellm_team_member_delete,litellm_delete_user,litellm_delete_plugin
```

---

## Adding a tool

1. Add a `ToolSpec` to `TOOL_REGISTRY` in `woow_litellm_mcp_server/registry.py`.
2. Implement it in the matching module under `woow_litellm_mcp_server/tools/`.
3. Add a request-shape case to `tests/test_tool_requests.py`.
4. Run `pytest`. `tests/test_mcp_surface.py` will fail if steps 1 and 2 disagree.

The GUI needs no change — it renders from the registry.
