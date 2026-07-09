# Host requirements & model matrix (P3-2)

This page answers two questions an operator asks before self-hosting: **what
hardware/software do I need to run the stack**, and **which class of LLM is
good enough for which product function**. Every number below is derived from
what the code and deploy scripts actually do — `docker/Dockerfile`,
`docker/docker-compose*.yml`, `scripts/proxmox-deploy.sh`, the tier-ladder
port (`src/applicant/ports/driven/llm.py`), the parse-verify layer, and the
P2-6 eval harness's live run. Where no run has exercised a claim, it is
labelled **expected-untested** per the H-series honesty invariants — an
absent verification must never render as a pass.

See also: [`docs/overview.md`](overview.md) (deploy topology + prerequisites),
[`docs/private-mode.md`](private-mode.md) (the local-only privacy contract),
[`docs/proof/eval/README.md`](proof/eval/README.md) (the P2-6 harness that
produced the material-generation evidence below), and
[`docs/studies/2026-07-07-parse-verify-tier-study.md`](studies/2026-07-07-parse-verify-tier-study.md)
(the parse-verify tier study).

---

## 1. Host requirements

### 1.1 Baseline (no local model, cloud LLM tier only)

| | Minimum | Recommended (installer default) |
|---|---|---|
| vCPU | 2 | **4** |
| RAM | 4 GB | **8 GB** |
| Disk | 20 GB | **40 GB** |
| OS | Any Docker host (Linux VM/LXC-with-VM/bare metal); the Proxmox path provisions Ubuntu Server 24.04 LTS | same |
| Network | Docker + Docker Compose v2; outbound HTTPS to your chosen LLM API (or none, if fully local) | same |

The "recommended" column is not a guess — it is the literal default
`scripts/proxmox-deploy.sh` provisions (`CORES="4"`, `RAM="8192"`,
`DISK="40"`; see the "sensible defaults" wizard mode), sized for the full
compose stack: the front-door UI image build plus `api` + `postgres` +
`searxng` + `chromadb` + `ntfy`. The "minimum" column is the smaller footprint
the same script's advanced mode still accepts, and is enough to run the stack
idle/lightly-loaded; it will feel tight during a `docker compose up --build`
first build (the `api` image alone compiles a ~700 MB TeX layer — §1.3) and
during a live pre-fill run (a real browser + Xvfb inside the `api` container).
**Fixed a stale mismatch:** `docs/overview.md` previously quoted "~2 vCPU / 4 GB
RAM" / "2 cores / 4 GB / 16 GB disk" as the Proxmox default; that no longer
matched the script (bumped to 4 cores / 8 GB / 40 GB disk once the full
front-door-UI-build stack was added) and has been corrected to match.

Disk headroom beyond the base image should account for: Postgres data growth
(campaign/application history), the credential vault, browser profile
persistence (`BROWSER_PROFILES_DIR`, so a signed-in ATS session survives
restarts), durable checkpoint state, and locally-installed fonts
(`FONTS_DIR`) — all named volumes, all small in practice for a single
operator, but not zero.

### 1.2 Add-ons that raise the floor

| Add-on | Extra requirement | Why |
|---|---|---|
| **Takeover desktop** (`--profile takeover`, live human hand-off for CAPTCHA/verification/final-submit) | `shm_size: 1gb` for that container + enough spare RAM/CPU to run a full streamed Ubuntu DE (Cinnamon/Xfce/GNOME/Pantheon) alongside the rest of the stack | It's a real desktop + real Chrome, not a thin shim (`docker/webtop-*`) |
| **Proxmox Windows sandbox backend** (`SANDBOX_BACKEND=proxmox-windows`) | A separate, licensed Windows VM on the same or a reachable Proxmox node (sized to run real Chrome comfortably — Windows' own floor, not this stack's) | Genuine-Windows-fingerprint stealth path (FR-STEALTH-1); this is infrastructure the operator provisions, not a container in `docker-compose.prod.yml` |
| **A local/on-box LLM tier** | See §1.4 — sized per model, not a fixed add-on | Optional; the default ships with zero local-model requirement (cloud tier only) |

### 1.3 Per-service footprint (production compose)

| Service | Reachability | Role | Notable footprint |
|---|---|---|---|
| `applicant-ui` | **Public**, `${APP_PORT}` → container `7000` | Front-door workspace UI (built from `workspace/`) | Standard Python/uvicorn image; brings its own SQLite |
| `api` | Internal only (`http://api:8000`) | The engine | **Heaviest image in the stack.** `python:3.12-slim` base + a *targeted* texlive subset (xetex/luatex/latex-extra/latex-recommended/fonts-recommended/fonts-extra + lmodern — deliberately not `texlive-full`) sized at **~700 MB for that layer alone** (`docker/Dockerfile` comment: "keep the image ~2GB instead of ~4GB"), plus LibreOffice Writer (docx→PDF fallback), the Camoufox browser binary + GeoIP dataset (default automation engine), and a real Google Chrome `.deb` + patchright's matched Chromium build (fallback automation engine / Proxmox CDP backend). The exact final image size was not measured in this session (CI validates `docker compose config` but does not build images — the honest gap is that this layer is "first exercised by the real `compose up --build` at deploy time," per `CLAUDE.md`); labelled **expected-untested** for a precise byte figure. Verify locally with `docker images applicant/api` after a build. |
| `postgres` (16) | Internal | Engine persistence + durable workflow state | Standard Postgres footprint; grows with application history |
| `searxng` | Internal | Metasearch for discovery (shared by engine + UI) | Lightweight |
| `chromadb` (pinned `1.0.21`) | Internal | Vector store for the workspace UI's RAG/memory | Lightweight for a single operator's corpus |
| `ntfy` | Internal | Push notifications for the workspace UI | Lightweight |
| `takeover-desktop` (opt-in profile) | Internal, published only under `--profile takeover` | Streamed Ubuntu desktop for live hand-off | Full DE image (webtop + Chrome + fonts); see §1.2 |

### 1.4 Local LLM hosting (optional): sizing a model to your hardware

Nothing in the stack requires a local model — the default tier ladder can be
100% a cloud OpenAI-compatible endpoint (§2). If you want a private/free tier
(including the hard `LLM_LOCAL_ONLY` mode, [`docs/private-mode.md`](private-mode.md)),
size it with the same math the workspace's own **Cookbook** hardware-fit tool
uses (`workspace/services/hwfit/`) rather than guessing:

```
required_VRAM_GB ≈ params_B × bytes_per_param(quant) + 0.000008 × active_params_B × context + 0.5
```

(`workspace/services/hwfit/models.py:estimate_memory_gb`). `bytes_per_param`
depends on quantization — full-precision F16/BF16 is 2.0 bytes/param, Q8_0 is
~1.0, Q4_K_M (a common "good enough, small" choice) is ~0.58, down to Q2_K at
~0.37. `hwfit` also estimates tokens/sec from GPU memory bandwidth (a lookup
table of ~50 GPUs, plus Apple Silicon unified-memory bandwidths) so it can
recommend the best quantization *for your actual detected hardware*, not a
generic rule of thumb.

**Reachable today:** the workspace's Cookbook surface (`workspace/routes/hwfit_routes.py`,
`workspace/static/js/cookbook-hwfit.js`) runs this exact calculator against
your detected GPU/RAM and a live Hugging Face model catalog — use it instead
of hand-computing the formula above. This doc does not duplicate a fixed
"buy an RTX 4090" recommendation because the right answer is hardware- and
model-specific; the tool is the source of truth.

Concrete anchor point from the parse-verify tier study (§3): a **~27B-class
model at a standard quantization** was sufficient as the free local floor for
that workload, running comfortably on a single consumer GPU in the 16–24 GB
VRAM class once quantized (Q4_K_M-equivalent) — that number came from a real
run, not the formula alone; see the study for the exact model and its
mid/ceiling escalation tiers.

---

## 2. Supported APIs / providers

The engine's LLM port (`src/applicant/ports/driven/llm.py`) is provider-agnostic:
a `TierLadder` is 1–N `TierConfig` rungs, each an independent
`{provider, base_url, api_key, model, context_window}` — any tier can be any
provider (FR-LLM-3). The wire-format layer
(`src/applicant/adapters/llm/provider_profiles.py`) resolves every tier to
exactly one of two transports:

| Wire profile | `LLM_PROVIDER` value | Covers | Notes |
|---|---|---|---|
| **Ollama-native** | `ollama` (or auto-detected from a `:11434`/`/api/` base URL when the provider string is blank) | Ollama | `/api/tags` for model listing, `/api/chat` for completion, `prompt_eval_count`/`eval_count` for usage |
| **OpenAI-compatible** (catch-all) | `openai` (or any other non-`ollama` string) | OpenAI cloud, OpenRouter, and **any other OpenAI-wire-compatible server** — vLLM, llama.cpp, SGLang, LM Studio, etc. | `/v1/models`, `/v1/chat/completions`, tool-calling + JSON-mode support, usage extracted from the OpenAI-shape `usage` block |

Every tier is independently configured — a common pattern is a free/local
Ollama or OpenAI-compatible-server tier at L1, escalating to a paid cloud
tier (OpenRouter, OpenAI) at L2/L3 only on low confidence or context overflow
(FR-LLM-4). `LLM_LOCAL_ONLY=true` filters the ladder to private-host tiers
only at construction time (see [`docs/private-mode.md`](private-mode.md) for
the exact host-classification rules) — that gate, not this table, is the
authority on what "local" means.

---

## 3. Model matrix — which class is good enough for which function

**How to read this table.** "Evidence" cites a real run where one exists;
absent that, the row is marked **expected-untested** and the pointer names the
harness that would produce real evidence (the P2-6 eval harness is the general
verification mechanism for generation-quality claims — `--golden-dir` accepts
real profiles, `--judge-model`/`--gen-model` swap the model under test).
Naming a specific model class below is product-configuration content (a value
you'd type into the setup wizard), not an engineering codename.

| Function | Capability floor (code-enforced) | Context floor | Model class actually proven | Evidence | Local-only compatible |
|---|---|---|---|---|---|
| **Parse-verify** (résumé ingest double-check, `PARSE_VERIFY_ENABLED`) | Must follow a strict "output ONLY JSON" instruction under a **generous** completion budget (`VERIFY_MAX_TOKENS=6000`) and self-report per-area confidence; reasoning/thinking mode must be OFF or capped — a reasoning-mode model burned its whole budget "thinking" and returned nothing in testing | Ladder default `context_window=8192` was sufficient for a full résumé + schema | Free local floor: a **~27B-class open-weights model, reasoning disabled**, produced a *perfect* corrected parse (zero invented strings) — the fastest of four models tried. Mid tier and a frontier-ceiling reference model also passed with zero fabrication | `docs/studies/2026-07-07-parse-verify-tier-study.md` (live run, real résumé, hand-built ground truth) | Yes — this is exactly the workload `LLM_LOCAL_ONLY` targets first |
| **Materials generation** (cover letter, tailoring, screening-question essay answers, `MaterialService`) | `SYSTEM_PROMPT`; structured output helps for the screening-answer JSON shape but the adapter has a defensive prompt-based fallback (FR-LLM-4a) so it is not a hard floor | A few thousand tokens (résumé + posting description + optional research context); no observed need for 128K-class context | A **GPT-4o-mini-class model** generated 32 materials across 20 synthetic cases: gate **PASS**, overall mean **4.60/5** (relevance 4.94, honesty 4.78, specificity 4.62, completeness 4.44, tone 4.22); zero degraded/fallback generations | `docs/proof/eval/material_eval_report.md` (live run via `material_runner.py`) | Yes, subject to the truthfulness/fabrication guard, which is deterministic (not model-dependent) |
| **Judging** (LLM-as-judge in the P2-6 eval harness) | Must approximate a `{"score": 1-5, "rationale": ...}` reply; the parser tolerates a fenced/prose-wrapped reply and falls back to a bare `"score": N` regex, but an unparseable reply is scored honestly (never silently defaulted to a passing 3) | Small — one material + rubric per call | Same **GPT-4o-mini-class model** used as both generator and judge in the only live run to date; the harness supports a separate, stronger `--judge-model` when budget allows (not yet exercised) | `docs/proof/eval/README.md` | Same as materials generation |
| **Digest / posting scoring, criteria learning** | Lightweight completion (existing calls cap output around 80 tokens) | Small | Not exercised through the eval harness; any tier on the ladder is expected to be adequate given the tiny output | **Expected-untested** for a formal quality score — no rubric-graded run exists yet; the P2-6 harness's method (golden set + LLM-as-judge) is the pointer for closing this gap | Yes |
| **Chat assistant / mind-substrate tool loop** (`chat_tools`, `loop_tools=auto`) | Base chat needs only `SYSTEM_PROMPT`; the tool-dispatch loop is enabled **only when the configured model also advertises tool calling** (`FUNCTION_CALLING`/`TOOL_USE`) — the code degrades to single-shot otherwise, never silently pretending tool support exists | Model-dependent; no fixed floor enforced | Not scored by the eval harness (it targets generated *materials*, not chat) | **Expected-untested** for quality; the tool-support gate itself is a hermetic unit-tested behavior, not a quality claim | Yes for the base chat path; tool loop needs a local model that actually advertises function-calling |
| **Plan-as-data pre-fill** (`PREFILL_USE_PLANNER`, experimental, default OFF) | `smart_router.py`'s task→capability map requires `FUNCTION_CALLING` + `STRUCTURED_OUTPUT` for reasoning-class tasks | Model-dependent | Experimental, opt-in; not covered by the eval harness | **Expected-untested** | Depends on the local model advertising both capabilities |
| **Embeddings** (RAG/memory retrieval) | None — no LLM tier involved | N/A | The engine's own local embedding adapter + in-stack vector store, always on-box regardless of `LLM_LOCAL_ONLY` | `docs/private-mode.md` ("Embeddings are always on-box") | Always (never leaves the box) |
| **Protected questions** (EEO/demographic, work-authorization) | N/A — **never AI-answered in either lane** by design (`core/rules/sensitive_fields.py`) | N/A | Not a model-selection question; this row exists so the matrix doesn't imply every function is model-driven | `docs/proof/citable-invariants.md` Claim 3 | N/A |

### 3.1 Reading the escalation ladder generically

Every row above rides the same mechanism (FR-LLM-3/4): a user-ordered
`TierLadder`, L1 (cheapest/local, tried first) through LN (the ceiling). A
call climbs on low confidence, a malformed/empty reply, or context overflow —
never silently; exhausting the ladder raises a typed error rather than
returning a degraded answer unlabeled. This is why the matrix above states a
*floor* per function rather than a single required model: any tier that
clears the floor is fine, and the ladder's job is to keep trying a stronger
tier when it doesn't.

---

## 4. Cost per application

There is no single fixed dollar figure to publish here — actual cost depends
entirely on which tier answers each call (a local L1 hit is $0), how often the
ladder escalates, and the operator's chosen provider pricing. Rather than
invent a number, the product ships a **live, per-deployment estimator**
(P1-6, DONE):

- Every completion's token usage is captured where the provider reports it
  (`ProviderProfile.usage_extractor` — OpenRouter/OpenAI-shape `usage` block,
  or Ollama's `prompt_eval_count`/`eval_count`) and folded into a process-lived
  `UsageLedger`.
- `core/rules/cost_estimate.py` turns tokens into a dollar estimate using a
  configurable **$/1K-token rate** (`LLM_COST_PER_1K_INPUT_USD=0.15`,
  `LLM_COST_PER_1K_OUTPUT_USD=0.60` by default — a deliberately conservative
  *blended cloud rate*, not any specific provider's real price list; tune it
  to your provider in Settings for a tighter estimate). A local/free tier
  costs the same $0 either way once no tokens are billed by a provider.
- `CostService` divides the day's estimated spend by applications acted on
  that day for an "≈$Y per application" figure, surfaced on **Today** (daily
  target/hard cap header) and **Settings** (monthly projection) — never
  presented as exact billing (H-series: an estimate must never render as a
  fact).

**Illustrative, not measured:** at the default rate, a single application's
LLM usage — one parse-verify call (if not already cached from onboarding),
one cover letter, one or two screening answers, worth roughly 5–10K input +
2–4K output tokens combined at a mid-tier model — lands in the neighborhood
of **$0.01–0.02** per application at the default blended rate, and **$0** if
every call is answered by a local/free L1 tier. This range is a rough,
illustrative back-of-envelope calculation from the documented per-call token
budgets above, not a measured harness output — the eval harness run that
produced §3's quality numbers did not capture token counts, so no live figure
is cited as fact. The in-product estimator is the authoritative number for any
given deployment; treat the range above as a sanity check, not a claim.

---

## 5. Platform / OS constraints

- The default deploy path (`scripts/proxmox-deploy.sh`, `docker/Dockerfile`)
  targets **amd64** (the Google Chrome `.deb`, Camoufox's fetched binary, and
  patchright's Chromium build are all fetched for the build host's
  architecture). Multi-arch is not built — this is now a documented,
  evidence-based constraint, not an open question: see
  [`docs/platform-matrix.md`](platform-matrix.md) (P3-7) for the exact
  binary-by-binary reasons and arm64/Apple-Silicon guidance. Don't infer
  arm64 support from anything in this doc.
- Docker-on-WSL2 setup + gotchas are also documented in
  [`docs/platform-matrix.md`](platform-matrix.md) §2 (procedure-only — not
  observed on a physical WSL2 box).

---

## Summary for an operator

1. **No local model:** 4 vCPU / 8 GB RAM / 40 GB disk (the installer's own
   default) is the grounded recommendation; 2 vCPU / 4 GB / 20 GB is the
   floor that still runs the stack.
2. **Adding a local model:** run the workspace's Cookbook hardware-fit tool
   against your actual GPU/RAM rather than guessing — it recommends a
   quantization that fits your box using the same formula documented in §1.4.
3. **Any OpenAI-compatible server or Ollama works** as any tier of the ladder;
   mix local and cloud tiers freely (FR-LLM-3).
4. **A ~27B-class local model (reasoning off)** is proven sufficient for the
   parse-verify workload; a **GPT-4o-mini-class model** is proven sufficient
   for material generation and its own judging, at a gate-passing 4.60/5.
   Everything else in the matrix is either capability-gated in code (chat
   tools, the experimental planner) or explicitly labelled
   expected-untested — re-run the P2-6 harness before promoting an
   expected-untested row to proven.
5. **Cost is a live per-deployment estimate**, not a fixed number — check
   Today/Settings after a day of real use, not this document, for your actual
   spend.
