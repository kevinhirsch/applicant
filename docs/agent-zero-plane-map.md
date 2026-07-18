# Agent Zero + Applicant: Monorepo Plane Map & Integration Design

> **Status: decision-support draft.** This maps the architectural "planes" for the agreed direction so
> the trade-offs are concrete before code moves. It extends the doctrine in
> [`../HARVEST-INVENTORY.md`](../HARVEST-INVENTORY.md) (keep the moat, harvest behind seams) to the
> general-agent + full-UI case that audit did not cover.
>
> **Definition of Done (owner):** a single **Agent Zero + Applicant monorepo** — agent-zero vendored into
> this repo, both shipping together — **while maintaining updateability with upstream agent-zero to the
> extent possible.**
>
> **Fork caveat:** agent-zero facts below describe upstream `agent0ai/agent-zero`. Verify
> `kevinhirsch/agent-zero`'s deltas and its exact license before lifting.

## The two codebases, one line each

- **Applicant** — a deterministic, single-purpose **hexagonal** engine (`src/applicant/`) + a **no-build**
  vanilla-JS front-door (`workspace/`). The moat is server-side safety gates the engine *cannot* opt out
  of. ~31k LOC, ~1,214 tests. Identity (README line 1): *"the autopilot that can't fire itself."*
- **Agent Zero** — a general-purpose, **prompt-driven** agent framework. **Alpine.js webui, no build
  step** (Flask/ASGI backend, WebSocket/Socket.io streaming), tool/plugin/**MCP-client**/A2A
  extensibility, a Dockerized XFCE desktop + browser, file-based memory + "Time Travel" snapshots.

Two feasibility facts, both confirmed and both favorable:
1. **Agent-zero's UI is no-build Alpine.js** — compatible with Applicant's no-build ethos (CI gates
   `node --check` only). The *opposite* of the React/Vite/Tailwind stack that made the hermes UI harvest
   an all-or-nothing reskin. The "full UI" is genuinely usable.
2. **Agent-zero is a native MCP client**, and Applicant is already an MCP **server** built to be driven by
   an external agent (`src/applicant/app/routers/mcp.py` — *"MCP interface for external agents to discover
   and invoke guarded application services"*). The integration seam is native to both sides.

## The core tension: updateability ⟂ white-label ⟂ bespoke UI

Everything about this build is governed by one trade-off triangle. You can have any two cheaply; the third
costs:

- **Updateability** — pull upstream agent-zero indefinitely.
- **White-label** — zero agent-zero codenames on the shipped surface (CI enforces this).
- **Bespoke UI** — heavily redesigned, not just re-branded.

**Editing agent-zero's own files is what breaks updateability.** Every edit to an upstream-tracked file is
a future merge conflict on `subtree pull`. So the whole strategy is built to avoid core edits:

**The reconciling discipline — "add, don't edit; brand at build time":**
1. **Vendor agent-zero pristine** as a `git subtree` at `agent-zero/` (code physically in the monorepo →
   satisfies the DoD; `git subtree pull` keeps it update-able). Submodule is the lighter alternative but
   weaker for a "monorepo" DoD and awkward once you add files under its `tools/`.
2. **Never edit upstream files.** Precisely: `agent-zero/` is an **upstream subtree with additive-only
   local extensions** — "pristine" means every *upstream-tracked* file stays byte-identical, while
   Applicant behavior goes into agent-zero's *native extension points* as **new files** (new paths merge
   cleanly; edits to existing files do not): `tools/applicant_*`, `plugins/applicant/`, prompt
   **overlays** in `prompts/_overlay/`, MCP-server config, agent profiles, model presets.
   **Collision rule:** every local addition is namespaced (`applicant_*` file prefix or an
   `applicant`/`_overlay` directory) so upstream can never legitimately introduce the same path; on
   `subtree pull`, upstream changes touch only upstream paths and local additions ride along untouched.
   A conflict on a namespaced path is therefore always a red flag to investigate, never auto-resolve.
3. **Apply white-label branding at build time, not in git.** Logo/name/string swaps run in the Docker
   build or entrypoint against the pristine tree — so the *shipped* UI is white-labeled while the *tracked*
   subtree stays pristine and pulls clean. This is what lets you keep updateability **and** white-label at
   once; the price you pay is that the UI stays agent-zero's UX (branded), not a from-scratch redesign.
   Going bespoke means editing UI files = giving up cheap updates. **That is the one decision to make.**

## The load-bearing decision: the safety line, restated for a general agent

Today, *"the autopilot that can't fire itself"* holds because the engine's `agent_loop` is a
**deterministic pipeline** that structurally stops at human review. A general agent **can**, in principle,
drive a browser and shell itself. So the tripwire is **not** "the agent decides to submit" — the MCP
surface already default-denies that (`mcp.py:96-110`: an unknown/consequential tool returns `isError`,
*"Consequential actions stay behind human review and cannot be invoked here"*). The real tripwire is:

> **The general agent uses its OWN browser/shell to fill and submit a real application directly,
> bypassing the engine's ATS state machine and stop-boundary.**

**Non-negotiable rule:** the engine's guarded path is the **only** path to consequential job-application
actions. The general agent may discover, plan, converse, and organize freely — but login, form fill,
upload, and **submit** for a real application must route through the engine capability, which stops at
review *server-side*. The general agent is an **untrusted caller** — the status `mcp.py` already assigns
every MCP client.

**Monorepo corollary (critical):** keep agent-zero and the engine as **two services across a network/MCP
boundary — not one fused Python process.** Agent-zero calls the engine over MCP/HTTP; it must **never**
`import applicant.core` to "optimize." The gates only enforce if they run in the engine process where the
caller can't reach around them. Co-location in one repo must not become co-location in one process.

**Corollary:** the safety plane (`src/applicant/core/rules/*`) stays server-side in the engine and
**never** migrates into agent-zero's `prompts/`. A prompt is guidance, not an enforcement boundary.

## Proposed monorepo layout

```text
kevinhirsch/applicant  (the monorepo)
├── agent-zero/           # PRISTINE git-subtree of upstream — never edit existing files
│   ├── …upstream tree…   #   (agent.py, webui/, prompts/, …) left untouched → clean pulls
│   ├── tools/applicant_*.py      # ADDED: engine capabilities as agent-zero tools (new files)
│   ├── plugins/applicant/        # ADDED: Applicant plugin(s)          (new dir)
│   └── prompts/_overlay/         # ADDED: white-label + role prompt overlays (new dir)
├── src/applicant/        # UNCHANGED engine — the called, gated capability
├── workspace/            # existing front-door — keep during transition; retire per plane 1
├── branding/             # white-label overlay (assets + string map) applied at BUILD time
├── docker/               # compose runs agent-zero + api(engine) + postgres + searxng + …
└── scripts/vendor-sync.sh  # git subtree pull upstream → run gates → report real conflicts
```

Update flow: `scripts/vendor-sync.sh` → `git subtree pull --prefix=agent-zero <upstream> main` → CI
(denylist + gates) → resolve only genuine conflicts. The fewer core edits, the cheaper each pull.

## The plane map

| # | Plane | Owner | How existing code is *called* / kept update-able | Effort | Tripwire |
|---|-------|-------|--------------------------------------------------|--------|----------|
| 1 | **UI / presentation** | **agent-zero** `webui/` (Alpine, no build) | branding via the build-time overlay; **add** Applicant's operator surfaces (Portal/pending-actions, digest review, redline) as agent-zero components/plugins, not core edits | **L** | If review/approval surfaces aren't reachable in the new UI, the safety boundary is **unoperable** (reachability = done). |
| 2 | **General-agent / reasoning** | **agent-zero** `agent.py` + subordinate agents + `prompts/` (overlaid) | adopt as-is; steer via prompt **overlays**, not core edits | adopt | Must stay a **caller** of the vertical, never the authority over its gates. |
| 3 | **Job-application capability** | **Applicant engine — called, not rebuilt** | (a) the engine's MCP surface registered in agent-zero over a real MCP transport (SSE `/mcp`, needs the optional `mcp` extra in the image — the `/mcp/tools` JSON routes are discovery aids, not a transport); (b) `ports/driving/*` wrapped as `agent-zero/tools/applicant_*`; (c) `/api/applicant/*` + the ~130-method `applicant_engine.py` bridge | **S–M** | *"Call existing code where it makes sense."* Keep the moat: `prefill_service`, resume tailoring, discovery, fabrication guard, vault. |
| 4 | **Safety / policy** *(cross-cutting)* | **Applicant** `core/rules/*` — server-side | enforced regardless of caller; consequential actions default-deny (`mcp.py` already) | keep + extend | **THE LINE.** Never migrate into prompts; never gate on caller input. |
| 5 | **Orchestration / scheduling** | **split** | Applicant durable orchestration + 24/7 scheduler for the **vertical**; agent-zero's loop for **interactive** work | keep both | Don't let agent-zero's ephemeral session own durable scheduling. |
| 6 | **Execution / sandbox / browser** | **split** | engine's camoufox/patchright + ATS state machine + stop-boundary for the **vertical**; agent-zero's Docker desktop + browser for **general compute** | keep both | **Sharp:** agent-zero's own browser/computer-use must NOT do a real application around the engine. Build on `core/rules/computer_use.py`. |
| 7 | **Memory / data** | **split** | engine Postgres+Alembic+chromadb + libsodium vault; agent-zero `knowledge/` + Time Travel for general memory | keep both, **separate** | Never let the credential vault or any secret land in agent-zero's file memory or snapshots. |

## CI white-label denylist — reconcile with a pristine vendored tree

The vendored `agent-zero/` tree legitimately contains "Agent Zero" / `A0` / `agent0ai` in its *own*
code and docs. The existing denylist (two greps, each with its own `:!` exclusion list — CLAUDE.md
principle #3) would fail on it. Resolution, mirroring the Hermes/Nous model-family carve-out already in
CI: **exclude `agent-zero/**` from the codename greps** (that exclusion covers *upstream-tracked content
only*), and instead assert white-label on the *shipped surface* via a **fail-closed branded-artifact
check**: the branding step must produce a concrete staging artifact (e.g. `dist/branded-ui/` — the
overlay applied to `agent-zero/webui/` exactly as the Docker build ships it), and CI must (a) **run the
branding step itself**, (b) **fail if the artifact is missing or the step errors** — an absent artifact
must never pass as a clean scan — and (c) grep the artifact for the agent-zero identifier set
(`Agent Zero`, `agent0ai`, `A0` word-bounded) with any hit failing the build. Otherwise upstream
identifiers copied at build time would ship undetected precisely *because* of the repo-grep exclusion.
This is a real design task, not a one-liner.

## Recommended shape

**Agent-zero is the general-agent + UI shell, vendored pristine. Applicant's engine is a called, gated
capability behind its existing MCP/HTTP seams, in a separate service. Branding is build-time; all
Applicant code lives in extension points or its own dirs.** This delivers the monorepo DoD, the full UI,
a general agent, and "call existing code where it makes sense" — while keeping the moat, the safety
identity, **and** cheap upstream updates. The ~130-method bridge and the MCP surface *are* the contract:
wrap, don't rewrite.

The option to avoid is a **hard fusion** (editing agent-zero core to weld the engine in): it forfeits
updateability — the one thing the owner explicitly asked to preserve — for no capability gain.

## Suggested sequencing (only if greenlit)

1. **Audit agent-zero** the way `HARVEST-INVENTORY.md` audited its harvest sources — keep-vs-take inventory +
   a license / white-label ledger (verify the fork's license and codename surface first).
2. **Vendor the subtree** at `agent-zero/`; add a stub `scripts/vendor-sync.sh` and prove one clean
   `subtree pull` round-trips.
3. **Prove the seam (smallest end-to-end test of the thesis):** stand up agent-zero, register the
   engine's MCP surface (SSE `/mcp`, `mcp` extra installed) as an MCP server, confirm the agent can list campaigns / pending-actions **and
   that a submit attempt is refused server-side.**
4. **Build-time branding overlay + denylist carve-out** for `agent-zero/**`; assert white-label on the
   shipped surface.
5. **Operator-surface parity:** bring Portal/pending-actions + digest/redline review into the Alpine UI
   as added components, so the safety boundary stays operable.
6. **Boundary enforcement:** constrain agent-zero's general browser/computer-use from consequential
   job-application actions (extend `core/rules/computer_use.py` + `prompt_injection.py`). **DoD includes
   a negative end-to-end test of the bypass path** — step 3 proves only MCP refusal, but the real
   tripwire is the agent's *own* browser/shell: prove a general-agent computer-use session cannot
   complete ATS login, form fill, upload, or submission around the engine (the attempt is blocked and
   surfaced, not silently completed), alongside the positive listing + MCP-refusal checks from step 3.
7. **Then** decide how much of the existing front-door migrates — not before steps 3 and 5 prove the shape.
