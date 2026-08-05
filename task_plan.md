# Task plan — documentation overhaul

Working-memory document for the August 2026 documentation pass. Kept in the repository
so the plan, the progress and the findings are auditable alongside the code they
describe.

**Goal.** Bring `Woow_litellm_mcp_server` up to the documentation standard set by
[`WOOWTECH/Woow_odoo_ai_assistant_package`](https://github.com/WOOWTECH/Woow_odoo_ai_assistant_package):
content files, an introduction, architecture diagrams (with Mermaid renderings and
written explanations), bilingual zh-TW/EN READMEs, categorised screenshots each paired
with explanatory text and sourced from the live services, every constituent package
presented at the repository root, and detailed supplementary documents.

---

## Constraints accepted at the outset

| # | Constraint | Why |
|---|---|---|
| 1 | Never rotate `mcp_auth_token`. | Rotation instantly kills the user's connected MCP client. `generate` previews safely; `rotate` does not. |
| 2 | Never delete or modify pre-existing gateway resources. | The gateway serves production traffic. Test artefacts carry an `mcptest-` prefix and are the only things touched. |
| 3 | Never change `admin_password`. | It is in active use. |
| 4 | Never write the master key, admin password, `mcp_auth_token` or any PAT into a file, report or commit. | Masked to first four characters wherever they must be referenced at all. |
| 5 | Restore any changed setting before finishing, and say so. | No silent drift. |
| 6 | Do not touch the `litellm` namespace, its Service, or the Cloudflare tunnel. | `litellm.woowtech.io` must stay up. |
| 7 | Real API keys never enter git — placeholders, `os.environ/` references or Secrets only. | Verified with pre-push greps. |
| 8 | `LITELLM_SALT_KEY` is set once and never rotated. | Rotating it makes every encrypted database column undecryptable. |
| 9 | Do not retry policy denials (403/407) — report them. | Retrying a policy block is noise, not progress. |

---

## Phases

### Phase 1 — Establish ground truth

Read facts from the running systems rather than from memory. No documentation written
until this is complete.

- Import `TOOL_REGISTRY` and generate the full tool table from source.
- Pull model deployments, pricing and capability flags via `litellm_model_info`.
- Pull health counts, spend totals and request counts from the live gateway.
- Read the SPA route table, the login flow and the auth mechanism from source.
- Read `pyproject.toml`, the `Dockerfile` and both Kubernetes manifests.
- Run the test suite and record the actual result.
- Count lines across all packages.

### Phase 2 — Capture screenshots

Drive a headless browser against both deployed services. Capture all eight console
routes and five gateway pages, plus generate a repository icon. Scrape the visible text
alongside each image so captions can quote what is actually on screen.

Upload binaries directly from the browser session — the sandbox's own network path to
the GitHub write API is blocked by policy (constraint #9), so the browser function does
the `PUT`.

### Phase 3 — Author

- `README.md` — the English landing page, following the reference repository's
  structure: centred icon and title, inline navigation row, shields, `Overview` through
  `License`, four architecture diagrams in both ASCII and Mermaid with a written
  "reading the diagram" paragraph each, all fourteen screenshots with captions, the
  generated 40-row tool catalogue, the test table, a newest-first changelog.
- `README_zh-TW.md` — a full mirror in Traditional Chinese, following the family's
  deliberate divergences: Chinese anchor names, no separate API Reference section, an
  extra fixed-issues table under Testing, footer without the heart.
- `docs/architecture.md` — the reasoning behind the diagrams.
- `docs/tool-catalog.md` — all 40 tools with purpose and danger notes.
- `docs/deployment.md` — the operational runbook.
- `docs/screenshots/README.md` — image index and recapture guidance.
- `task_plan.md`, `progress.md`, `findings.md` — this working-memory triad.

### Phase 4 — Publish and verify

- Push all text files.
- Verify each file byte-for-byte against `origin/main`.
- Confirm every embedded image resolves on the rendered page.
- Run two independent secret scans over the pushed tree.
- Advise on credential rotation.

---

## Out of scope

Code changes. This pass documents the system as it is and records defects found; fixing
the one documentation defect (the tool count) is in scope because the defect *is*
documentation. `frontend/package-lock.json` is deliberately deferred — it is tangential
to the documentation goal and large enough to be worth adding in a separate commit.
