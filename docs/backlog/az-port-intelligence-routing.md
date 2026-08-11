# AZ-Port · Intelligence Routing & Model Tiering — Spec Suite (FR-INTEL)

> **Purpose.** Applicant V2 runs on the Agent Zero shell. This suite specifies the *applied model
> configuration* the shell/agent layer must ship with — the local↔remote split, the tier topology,
> the failure-based escalation path, the deterministic routing, and the "Claude-Code-level" decision
> of *which model to use when*. It is written to have **zero blind spots**: every threshold, sampling
> value, concurrency limit, and escalation trigger is fixed to a concrete, reference-verified number,
> and every place the product must adapt to unknown user hardware defines the *mechanism*, the
> *default*, and the *fallback* — never a TBD.
>
> **Provenance.** These specs are lifted directly from the hardened configuration of the A0 instance
> that is *building* Applicant (the "reference deployment", §0). The reusable artifacts (§9) are the
> actual files in production on that instance; the product inherits them verbatim with the
> parameterizations called out per spec.
>
> **House style.** Each spec carries **As / I want / so that**, **Effort** (S = hours · M = 1–2 days ·
> L = 3+ days), **Owner**, **Depends on**, **Phase**, **DoR** (preconditions), **DoD** (behavioural,
> verifiable completion checklist), and **AC** (acceptance criteria as concrete, testable assertions).
> The universal DoD of the port backlog (`docs/backlog/road-to-market.md` + the port-wide additions)
> applies to every spec here in addition to its own.
>
> **Family:** `FR-INTEL-*` · **Phase home:** slots under **AZ-1** (model-connect) → **AZ-3** (tiers
> editor surface); the underlying policy (INTEL-1..6) is a prerequisite of **AZ1-1 #829** and is
> surfaced by **AZ3-1 #839**. **Owner:** eng unless noted.

---

## 0. Reference deployment — the ground truth (verified 2026-07-19)

Every number below is measured/live on the building instance and is the product's **reference
profile** (the default tuning a matching host inherits unchanged).

### 0.1 Local inference server
| Property | Value |
|---|---|
| Model | **Qwen3.6-27B, GPTQ-Int4** (`~/Desktop/models/Qwen3.6-27B-GPTQ-Int4`) |
| Serving id | `qwen27b-int4-tqk8v4-two250K-mtp3-text-only-cu128` (alias `qwen3.6:27b`) |
| Endpoint | `http://10.0.1.225:8000/v1` (OpenAI-compatible, vLLM) |
| GPUs | **2× RTX 2080 Ti** (SM75), tensor-parallel TP=2, 260 W cap each, `--gpu-memory-utilization 0.92` |
| KV cache | `turboquant_k8v4` (quantised) → enables 256K ctx to fit; `~19.6 GB` VRAM/GPU |
| **Max context** | **256 000** physical (`--max-model-len 256000`); **capped to 96 000** in the A0 preset (`ctx_length: 96000`, `ctx_history: 0.7`) |
| **Concurrency** | **`--max-num-seqs 2`** — HARD limit; the rig is tuned for 1–2 heavy clients. Raising it splits KV cache and slows every stream. |
| **Decode speed** | **64–86 tok/s** per stream (MTP-3 acceptance dependent) |
| **Prefill speed** | **~1 600 tok/s** |
| Modality | **text-only** (no vision) |
| Known cliff | TurboQuant continuation-prefill scratch buffer is fixed post-CUDA-graph; long prompts can exceed it → both TP workers die. Mitigated by `VLLM_TURBOQUANT_CONTINUATION_WORKSPACE_RESERVE_TOKENS=131072`. |

### 0.2 Remote (cloud) models
| Preset | Model | Endpoint | Ctx | Role |
|---|---|---|---|---|
| `DeepSeek-Chat` | `deepseek-v4-flash` | api.deepseek.com/v1 | 100 000 | Overseer chat (agent0) |
| `DeepSeek-Flash` | `deepseek-v4-flash` | api.deepseek.com/v1 | 1 000 000 | Cloud workers + reviewer + security |
| `DeepSeek-Pro` | `deepseek-v4-pro` | api.deepseek.com/v1 | 1 000 000 | Debugger + escalation target |

### 0.3 Profile → preset → tier map (verified)
| Agent profile | Preset | Model | Tier | Locality |
|---|---|---|---|---|
| `agent0` (overseer) | DeepSeek-Chat | deepseek-v4-flash | cloud-flash | **remote** |
| `coder` | Default | Qwen3.6-27B | local-fast | **local** |
| `explorer` | Default | Qwen3.6-27B | local-fast | **local** |
| `test-engineer` | Default | Qwen3.6-27B | local-fast | **local** |
| `coder-cloud` | DeepSeek-Flash | deepseek-v4-flash | cloud-flash | **remote** |
| `explorer-cloud` | DeepSeek-Flash | deepseek-v4-flash | cloud-flash | **remote** |
| `reviewer` | DeepSeek-Flash | deepseek-v4-flash | cloud-flash | **remote** |
| `security-auditor` | DeepSeek-Flash | deepseek-v4-flash | cloud-flash | **remote** |
| `debugger` | DeepSeek-Pro | deepseek-v4-pro | cloud-pro | **remote** |

### 0.4 Routing thresholds (measured, `context_estimate`)
| Band | Tokens | Decision |
|---|---|---|
| dual-local | **< 40 000** | LOCAL — up to **2 concurrent** local steps |
| single-local | **40 000 – 90 000** | LOCAL-SINGLE — one local step, run **alone** |
| cloud | **> 90 000** (≈96K cap) | CLOUD — route to `*-cloud`, or split into <40K chunks |
| base overhead | `base_tokens = 9 000` | fixed system-prompt + tool-schema budget added to every estimate |

### 0.5 Escalation (`_model_escalate`)
`THRESHOLD = 2` consecutive struggles on a **local** agent → its next call runs on **`DeepSeek-Pro`**;
a clean tool result + progress resets the counter and reverts to local. State lives on
`agent.loop_data.params_persistent["_escalate_struggle"]`. Already-cloud calls never self-escalate.

### 0.6 Sampling (verified `presets.yaml`)
| Preset | temp | top_p | top_k | presence_penalty | thinking | decoding |
|---|---|---|---|---|---|---|
| Default · chat (local) | **0.25** | 0.8 | 20 | 0.3 | off | JSON-schema `a0_tool_call` + `guided_decoding_backend: guidance` |
| Default · utility (local) | 0.3 | 0.8 | 20 | **1.0** | off | — |
| DeepSeek-* · chat (cloud) | 0.6 | 0.95 | — | — | — | native; `a0_retry_attempts: 5`, `a0_retry_delay_seconds: 3` |

---

## 1. The two model planes — the boundary (read this first)

Applicant V2 has **two independent model-using systems**. Confusing them is the single largest
blind-spot risk, so the boundary is normative:

- **Plane A — the Shell/Agent plane.** The A0 assistant, overseer, and worker profiles (coder,
  explorer, reviewer, …). Governed **entirely by this suite (INTEL-1..6)** via the A0 `_model_config`
  presets. This is the "think-here-build-there" plane.
- **Plane B — the Engine plane.** The Applicant *engine's* own LLM calls — base-résumé parse-verify,
  material tailoring/rewrite, screening answers, taste model. Governed by the **engine tier-ladder**
  (`/setup/llm/tiers`, surfaced by AZ3-1 #839). The engine already ships a tier ladder + the
  parse-verify tier study (`docs/studies/`); this suite **does not replace it**.

**INTEL-7 (§2.7)** specifies exactly how the two planes are wired, share the model connection, and stay
non-overlapping. Plane B is out of scope for INTEL-1..6 except where INTEL-7 binds them.

---

## 2. The specs

### 2.1 — FR-INTEL-1 · Canonical agent-profile tier topology
**As** the product, **I want** a fixed, named set of agent profiles each bound to an explicit model
tier, **so that** every unit of agent work runs on the cheapest model that can do it correctly and the
routing is legible, testable, and reproducible out of the box.

**Effort:** M · **Owner:** eng · **Depends on:** AZ0-5 #827 (plugin skeleton), AZ0-6 #828 (seam) ·
**Phase:** AZ-1 · **Spec:** §0.3, §9.1.

**DoR**
- [ ] AZ0-5 plugin skeleton merged (the `_model_config` plugin ships in the A0 subtree; the applicant
      plugin can carry per-profile `config.json` overrides).
- [ ] The three cloud presets (`DeepSeek-Chat/Flash/Pro`) and the local `Default` preset exist in the
      shipped `presets.yaml` (§9.1), provider-agnostic (endpoint + key injected at setup, INTEL-7).

**DoD**
- [ ] The **nine reference profiles** (§0.3) ship as agent profiles under the applicant plugin, each
      with a `_model_config/config.json` selecting its preset — byte-matching §0.3.
- [ ] Three **tiers** are named and documented: `local-fast` (local Qwen-class), `cloud-flash`
      (fast cloud), `cloud-pro` (max-intelligence cloud). Every profile maps to exactly one.
- [ ] The overseer (`agent0`) is bound to a **cloud** tier by default (never local) — see INTEL-5 for
      why (planning/verification are remote-only).
- [ ] A profile whose preset endpoint is unreachable **degrades honestly** (H2): the panel/agent
      surfaces "model tier X unavailable" and the routing falls back per INTEL-3/INTEL-5, never
      silently runs the wrong tier.
- [ ] On-surface instructions on the tiers surface (AZ3-1) name each profile's tier + locality.

**AC**
1. Loading each of the nine profiles resolves to the model in §0.3 (assert profile→preset→model).
2. `agent0` resolves to a cloud model on a clean install; no code path binds the overseer to local.
3. With the local endpoint down, spawning a `coder` step surfaces an explicit unavailable-tier
   message and does **not** fall through to an unconfigured/default model.
4. Removing any of the three cloud presets fails a shipped config-contract test (the tier set is a
   fixed contract, not free-form).

---

### 2.2 — FR-INTEL-2 · Local inference envelope & hardware-profile declaration
**As** a self-hosting user, **I want** the product to know exactly what my local hardware can and
cannot do, **so that** local work is fast and never OOMs, and anything beyond the local envelope is
routed to cloud automatically — with my box's real limits, not guesses.

**Effort:** M · **Owner:** eng · **Depends on:** INTEL-1 · **Phase:** AZ-1 · **Spec:** §0.1, §0.4.

The envelope is fully described by **three numbers** plus modality:
`concurrency` (server `max-num-seqs`), `ctx_cap` (usable context before the model degrades/OOMs),
`decode_tok_s` (throughput), and `vision` (bool). The reference profile (§0.1) is
`{concurrency: 2, ctx_cap: 96000, decode_tok_s: 75, prefill_tok_s: 1600, vision: false}`.

**DoR**
- [ ] INTEL-1 tiers exist; the local tier has a reachable endpoint OR is explicitly declared absent.
- [ ] A benchmark note format exists (`docs/vLLM-Benchmarks.md`-style) that records the three numbers.

**DoD**
- [ ] A **hardware profile** object is declared at setup with `{concurrency, ctx_cap, decode_tok_s,
      prefill_tok_s, vision}` and persisted. Three shipped defaults:
      **(a) `reference`** = §0.1 exactly; **(b) `byo-endpoint`** = user supplies an OpenAI-compatible
      local URL + the three numbers (self-declared or probed); **(c) `cloud-only`** = no local tier,
      `concurrency: 0` → every step routes cloud (INTEL-3 collapses to "always cloud").
- [ ] `concurrency` is read from the server where possible (vLLM `max-num-seqs`) and otherwise taken
      from the declared profile; it is the **hard cap** on simultaneous local workers (INTEL-5 fan-out
      obeys it).
- [ ] `ctx_cap` is the **A0 preset `ctx_length`** (default 96 000), never the raw physical
      `max-model-len` — the routing must protect the *usable* window, not the theoretical one.
- [ ] The envelope is **honest about the cliff**: the continuation-prefill workspace reserve (§0.1)
      is documented as a known long-prompt failure mode, with the reserve token knob named.
- [ ] Text-only is enforced: any step needing vision routes to a vision-capable (cloud) tier or
      surfaces "not supported locally", never sends images to the local text model.

**AC**
1. On the `reference` profile, `context_estimate` (INTEL-3) returns `concurrency=2, ctx_cap=96000`.
2. On `cloud-only`, every routing decision returns CLOUD and no local worker is ever spawned.
3. A `byo-endpoint` user setting `concurrency=1` causes INTEL-5 fan-out to never pair two local
   workers (assert at most 1 concurrent local step).
4. A step estimated at 120K tokens on the `reference` profile is refused-local and routed cloud
   (never sent to the 96K-capped local model).

---

### 2.3 — FR-INTEL-3 · Deterministic local↔remote routing (context sizing)
**As** the overseer, **I want** a deterministic, pre-flight sizing of every delegated step, **so that**
I place it on local vs cloud by measured token budget rather than vibe — the core of the split.

**Effort:** S · **Owner:** eng · **Depends on:** INTEL-2 · **Phase:** AZ-1 · **Spec:** §0.4, §9.3.

**DoR**
- [ ] INTEL-2 hardware profile available (supplies `ctx_cap`, `concurrency`).
- [ ] A token estimator (chars/token heuristic or a tokenizer) is available to the overseer tool.

**DoD**
- [ ] The `context_estimate` tool (§9.3) ships: given `paths`/`text` + `base_tokens` (default **9 000**),
      it returns `estimated_tokens` and one of three recommendations, using thresholds **derived from
      the hardware profile**, defaulting to the reference numbers:
      - **< `local_dual_below` (40 000):** `LOCAL` — up to `concurrency` local steps may run at once.
      - **`40 000`–`local_single_below` (90 000):** `LOCAL-SINGLE` — one local step, run alone.
      - **> `90 000`:** `CLOUD` — route to `*-cloud`, or split inputs into <40K local chunks.
- [ ] Thresholds scale with the profile: `local_single_below = ctx_cap − headroom`; `local_dual_below`
      is the point past which two concurrent streams degrade sharply (default 40K; ≈`ctx_cap`×0.42).
- [ ] The overseer prompt **mandates** calling `context_estimate` before any delegated read/edit step
      (INTEL-5 makes this a discipline rule); the return is advisory-but-followed.
- [ ] The recommendation includes the *why* (measured limit) and the split fallback, verbatim from §9.3.

**AC**
1. 25K-token input → `LOCAL` + "2 concurrent OK".
2. 70K-token input → `LOCAL-SINGLE` + "run it alone".
3. 130K-token input → `CLOUD` + split suggestion.
4. Same inputs on `cloud-only` profile → always `CLOUD`.
5. The tool is pure/deterministic: identical inputs return identical output (no model call).

---

### 2.4 — FR-INTEL-4 · Failure-based escalation to a higher tier
**As** the product, **I want** a local worker that keeps failing to be automatically promoted to the
strongest model for its next attempt, **so that** hard sub-tasks don't loop forever on a model that
can't do them — while easy work stays free/local.

**Effort:** M · **Owner:** eng · **Depends on:** INTEL-1 · **Phase:** AZ-1 · **Spec:** §0.5, §9.2.

**DoR**
- [ ] INTEL-1 `cloud-pro` tier (`DeepSeek-Pro`) reachable.
- [ ] The A0 extension points `chat_model_call_before`, `hist_add_warning`, `tool_execute_after` exist
      (they ship in the subtree; the plugin adds self-contained extensions — §9.2).

**DoD**
- [ ] A per-agent **struggle counter** on `loop_data.params_persistent["_escalate_struggle"]` is
      incremented by **(a)** an unusable response (misformat / empty / repeat, via `hist_add_warning`)
      and **(b)** a failing tool call (via `tool_execute_after`); a **clean tool result + progress
      resets it to 0**.
- [ ] When the counter **≥ `THRESHOLD` (2)** on a **local** agent, `chat_model_call_before` swaps that
      agent's *next* chat call to the **`DeepSeek-Pro`** preset; on success/reset it reverts to local
      automatically (no manual intervention, no permanent promotion).
- [ ] **Already-cloud agents never self-escalate** (an overseer/cloud worker struggle does not re-route).
- [ ] Every extension is **fail-safe**: any error in the tracker is swallowed and leaves the agent on
      its default tier (escalation is an optimisation, never a foot-gun).
- [ ] The escalation is **observable**: an escalation event is logged/surfaced (H1 receipts) so the
      user can see "promoted to Pro after 2 struggles", not a silent model swap.

**AC**
1. Two consecutive local misformats → the third call goes to `deepseek-v4-pro` (assert the resolved
   model on call 3).
2. A clean tool result between struggles resets the counter (call after reset is local again).
3. A struggling **cloud** worker stays on its cloud model (no double-escalation).
4. Injecting an exception into the tracker leaves the agent on its default model (fail-safe).
5. THRESHOLD is a single named constant; changing it to 3 moves the escalation to call 4 (pinned test).

---

### 2.5 — FR-INTEL-5 · Orchestration doctrine & the remote-only scenario catalog
**As** the overseer, **I want** an explicit doctrine for what I keep for the cloud brain vs delegate to
free local workers, plus the definitive list of work that is remote-only, **so that** the system spends
paid tokens only where higher intelligence is actually required — Claude-Code-level judgment about
which model to use when.

**Effort:** M · **Owner:** eng · **Depends on:** INTEL-1, INTEL-3 · **Phase:** AZ-1 (doctrine) → AZ-2
(applied in the assistant) · **Spec:** §9.4 (the `agent0` specifics prompt).

**Doctrine (normative — "think here, build there"):** the overseer runs on a **cloud** model and is the
**planner/reviewer, not the typist**. It does **no** multi-step implementation itself. It delegates:

| Work | Delegate to | Tier | Locality |
|---|---|---|---|
| Real coding / edits / running commands & builds | `coder` | local-fast | local |
| Reading / searching code | `explorer` (after `context_estimate`) | local-fast | local |
| Writing & running tests | `test-engineer` | local-fast | local |
| Independent verification of an important change | `reviewer` (`verify:true` + concrete requirement) | cloud-flash | **remote** |
| Security-sensitive review (auth, untrusted input, secrets, deps) | `security-auditor` | cloud-flash | **remote** |
| Hard debugging / deep judgment | `debugger` | cloud-pro | **remote** |

**Remote-only scenario catalog (the definitive "must be cloud" list + why):**
| # | Scenario | Why local can't | Tier |
|---|---|---|---|
| R1 | Planning, decomposition, architecture, ambiguity resolution | Needs the strongest reasoning; sets everything downstream | overseer (cloud) |
| R2 | Reviewing/synthesising worker output; final answer to the user | Must not trust a local worker's self-assessment | overseer (cloud) |
| R3 | Independent verification of an important change | A second, stronger, *independent* judge | `reviewer` (cloud-flash) |
| R4 | Security review | Higher stakes; must catch subtle issues | `security-auditor` (cloud-flash) |
| R5 | Hard debugging after local escalation exhausted | Max intelligence | `debugger` (cloud-pro) |
| R6 | Any step > `ctx_cap` (≈96K) | Physically exceeds the local window | `*-cloud` (cloud-flash, 1M ctx) |
| R7 | Repeated local failure (≥2 struggles) | Local model can't converge (INTEL-4) | `DeepSeek-Pro` (cloud-pro) |
| R8 | Parallelism beyond `concurrency` (2) local slots | GPU can't run more heavy streams | overflow → `*-cloud` |
| R9 | Vision / image reasoning | Local model is text-only | vision-capable cloud |

**DoR**
- [ ] INTEL-1 tiers + INTEL-3 sizing available.
- [ ] The `subagent`/`call_subordinate`/`orchestrate` tools ship (subtree + plugin).

**DoD**
- [ ] The overseer profile prompt encodes the doctrine table + the remote-only catalog verbatim (§9.4);
      the assistant (AZ2-5) inherits it so consequential job actions route through the engine, not the
      local model.
- [ ] **Parallel fan-out policy:** spawn at most `concurrency` (default 2) **local** workers; route
      additional independent work to **cloud** workers so it runs concurrently instead of queuing on the
      GPUs. Mixed local+cloud fan-out is the default for independent work.
- [ ] **Full-suite acceptance gate:** the overseer runs the full test suite as the gate before accepting
      any delegated code/test work — never module-scoped only (cross-test pollution only shows in a full
      run). Accept only if no new failures vs the known baseline.
- [ ] **Never trust self-assessment:** important changes get an independent `reviewer` pass (R3) before
      they count as done.
- [ ] Each remote-only scenario (R1–R9) has a corresponding routing rule that a test can assert.

**AC**
1. A "plan this feature" request is handled by the overseer (cloud), not delegated to local.
2. Three independent code sub-tasks on the reference profile spawn ≤2 local + the rest cloud (assert
   the locality split).
3. An "important change" is not marked done until a `reviewer` (cloud) verification runs.
4. A security-labelled review routes to `security-auditor` (cloud), never local.
5. A 130K-token read never runs on a local worker (R6); a vision task never hits the local text model (R9).

---

### 2.6 — FR-INTEL-6 · Per-tier sampling & decoding contracts
**As** the product, **I want** each tier's sampling and decoding fixed to what makes *that* model
reliable, **so that** the local model emits valid tool-calls every time and the cloud models stay
correct and resilient — no silent misformat, no runaway retries.

**Effort:** S · **Owner:** eng · **Depends on:** INTEL-1 · **Phase:** AZ-1 · **Spec:** §0.6, §9.1.

**DoR**
- [ ] INTEL-1 presets exist; the local server supports guided decoding (vLLM `guided_decoding_backend`).

**DoD**
- [ ] **Local (`Default.chat`)** ships exactly: `temperature 0.25, top_p 0.8, top_k 20,
      presence_penalty 0.3, chat_template_kwargs.enable_thinking=false`, **`response_format` =
      json_schema `a0_tool_call`** (`{thoughts[], headline, tool_name, tool_args}`, `required:
      [thoughts, tool_name, tool_args]`, `additionalProperties:false`), **`extra_body.guided_decoding_backend:
      guidance`**. Rationale documented: a 27B-Int4 model needs *constrained decoding + low temperature*
      to emit valid tool JSON reliably; thinking is **off** (the parse-verify tier study found reasoning
      must be off for this tier).
- [ ] **Local (`Default.utility`)** ships `temperature 0.3, presence_penalty 1.0` (higher penalty for
      naming/summarisation diversity) — same guided/no-think base.
- [ ] **Cloud (`DeepSeek-*`)** ships `temperature 0.6, top_p 0.95, stream_options.include_usage=true,
      a0_retry_attempts 5, a0_retry_delay_seconds 3` (native tool-calling; resilient to transient
      provider errors).
- [ ] A shipped test asserts the local chat preset carries the JSON-schema + guidance backend (the
      anti-misformat contract) and that `enable_thinking` is false.

**AC**
1. The local chat model, given a tool step, returns schema-valid `{thoughts, tool_name, tool_args}`
   JSON (guided decoding on) — assert 0 misformats over a fixed probe set.
2. Setting local `temperature` above 0.25 in the shipped preset fails the sampling-contract test.
3. A transient cloud 5xx is retried up to 5×3s before surfacing (assert retry behaviour).
4. The utility preset uses `presence_penalty 1.0` (distinct from chat's 0.3).

---

### 2.7 — FR-INTEL-7 · Two-plane reconciliation (shell models ↔ engine tier-ladder)
**As** the product, **I want** the shell/agent models (Plane A) and the engine's tier ladder (Plane B)
to share one model connection but stay non-overlapping, **so that** the user configures models **once**
and there is zero ambiguity about which system uses which model for what.

**Effort:** M · **Owner:** eng · **Depends on:** INTEL-1, AZ1-1 #829 (model-connect bridge),
AZ3-1 #839 (tiers editor) · **Phase:** AZ-1 → AZ-3 · **Spec:** §1.

**DoR**
- [ ] AZ1-1 model-connect bridge design available (A0 model gate → engine `/setup/llm`).
- [ ] The engine tier-ladder (`/setup/llm/tiers`) + parse-verify tier study are present.

**DoD**
- [ ] **Single connect act (D2/D11):** connecting a model in the A0 gate configures **both** Plane A
      (the shell presets' provider/key/endpoint) **and** Plane B (`POST /setup/llm`), per AZ1-1 — never
      two prompts.
- [ ] **Ownership is explicit and disjoint:** Plane A (assistant, coder, explorer, reviewer, debugger,
      security-auditor) is owned by this suite; Plane B (base-résumé parse-verify, material
      tailoring/rewrite, screening answers, taste model) is owned by the engine tier ladder. A
      documented table maps every model-using capability to exactly one plane.
- [ ] **`LLM_LOCAL_ONLY` carries across both planes:** local-only mode hides cloud/OAuth forks in the A0
      gate AND forces the engine ladder to local — and, per INTEL-5/R-catalog, the remote-only
      scenarios (R1–R5) degrade honestly to the best available *local* tier with a surfaced caveat
      (never a silent cloud call).
- [ ] The tiers editor (AZ3-1) shows **both** planes' current bindings read-only-accurately (H1: a
      projection of real config, never a synthesised guess).

**AC**
1. One model-connect action results in both a resolved Plane-A preset and a successful engine
   `/setup/llm` (assert both side effects).
2. Every model-using capability in the product resolves to exactly one plane (no capability reads both;
   contract test over the capability→plane map).
3. With `LLM_LOCAL_ONLY=1`, no cloud endpoint is ever called by either plane; remote-only scenarios
   surface a local-degrade caveat.
4. The tiers editor's displayed bindings equal the live resolved config for both planes.

---

## 3. Universal DoD additions (apply to every spec above)
Inherited from `docs/backlog/road-to-market.md` + the port-wide additions:
- [ ] **Honest degrade (H2):** any tier/endpoint failure is surfaced per-item, never silent.
- [ ] **Receipts not narration (H1):** the model/tier actually used for a result is a projection of
      real state (surfaced on request), never claimed.
- [ ] **Calibrated copy (H5):** all tier/help strings name real prerequisites (a key, a local endpoint,
      VRAM) and never overclaim local capability.
- [ ] **On-surface instructions:** the tiers/setup surfaces carry plain-language guidance.
- [ ] **Tests:** each spec's AC ships as automated tests; the sampling/threshold/tier contracts are
      pinned so drift fails CI.
- [ ] **Parallel-safe + full-suite gate:** any test added is parallel-safe and the full unit suite is
      the acceptance gate.

---

## 9. Reusable reference artifacts — lift these verbatim
The product inherits these production files with the parameterizations noted. Paths are on the
building instance (`/a0/usr/plugins/…`); they become the applicant plugin's shipped config.

- **§9.1 `presets.yaml`** — the four presets (Default local + DeepSeek-Chat/Flash/Pro). Ship verbatim;
  parameterize only `api_base` + provider key (injected at setup, INTEL-7). Local `name`/`api_base` come
  from the hardware profile (INTEL-2). → `docs/backlog/az-port-intelligence-routing/presets.reference.yaml`
- **§9.2 `_model_escalate/`** — three self-contained extensions (`chat_model_call_before/_30`,
  `hist_add_warning/end/_50`, `tool_execute_after/_20`). Ship verbatim; `THRESHOLD` and `_PRO_PRESET`
  are the only knobs. → INTEL-4.
- **§9.3 `_orchestration/tools/context_estimate.py`** — the routing tool + its prompt doc. Ship verbatim;
  `_DUAL_OK`/`_LOCAL_MAX` are sourced from the hardware profile (INTEL-2) instead of hard-coded. → INTEL-3.
- **§9.4 `agents/agent0/prompts/agent.system.main.specifics.md`** — the "think-here-build-there" doctrine
  + delegation tiers + parallel fan-out + full-suite gate. Ship as the overseer profile prompt. → INTEL-5.
- **§9.5 `_subagents/`** — named background subagents + async steering + child-visible supervision
  (the overseer's parallel-fan-out mechanism). → INTEL-5 fan-out.

> Copies of §9.1–§9.4 are placed alongside this spec in `docs/backlog/az-port-intelligence-routing/` as
> `*.reference.*` files so the spec is self-contained and the product can diff against the source of truth.
