# ADR-0015: Verified-source, wide-net job-posting discovery

**Status:** Accepted (grounds `docs/APPLICANT-BACKLOG.md` § EPIC DISCOVERY).
**Numbering:** next free slot after `docs/adr/0014-main-agent-companion.md` in the existing
`docs/adr/0001`–`0014` sequence.
**Relates to:** ADR-0011/0012/0013 (fit engine — what discovery feeds), ADR-0008 (self-heal —
circuit-breaker/source-health detectors this ADR's sources emit into).

## Context

Discovery is the top of the funnel: nothing scores, drafts, or ships if it was never found. The
product owner's standing requirement (verbatim, two related statements):

> "We only scrape jobs from verified sources… the only entity we receive is a job posting."

> "Throw the net as wide as you possibly can… prioritize aggregators but direct connections are
> useful… we can't limit ourselves to specific industries."

Two requirements, in tension if handled naively, resolved the same way real search infra resolves
them: **breadth of SOURCE, not looseness of SHAPE.** Cast the widest possible net across
aggregators + direct ATS connections, industry-agnostic — but every single row that lands in
`job_postings` must first prove it is a real, verifiable job posting, never a scrape artifact, an
"is hiring" announcement, a bare company-name row, or noise. This had **no ADR** before this one,
despite being (per the product owner) the single biggest lever on queue quality — everything
downstream (fit-scoring, drafting) is worthless against a posting that was never real.

**What already exists to build on** (grounded by file, reuse-first per
`docs/APPLICANT-BACKLOG.md` line 13):

- **A real-postings validation gate, not just "non-empty."**
  `src/applicant/adapters/discovery/validate.py` — `SourceValidationResult`,
  `validate_postings_shape(rows, title_keys, url_keys)`, `validate_provider_rows(provider, rows)`.
  `PROVIDER_SHAPES` defines, per provider, the minimum (title-field, identity/URL-field) a raw row
  must carry to count as REAL: an empty list, a 404-turned-`[]`, or a shape with rows that lack
  both a title and an identity/URL signal all **fail closed** — never silently pass. Covers
  `greenhouse` / `lever` / `ashby` / `smartrecruiters` / `workday` (ATS, identity-field variants
  documented per-provider) and `remoteok` / `remotive` / `workingnomads` (aggregators).
- **The gate is already enforced at the runtime write path, not just offline.**
  `src/applicant/application/services/discovery_service.py`, `DiscoveryService.add_board`
  (L211-266): fetches a live sample from the candidate board and calls `validate_provider_rows`
  BEFORE persisting/registering it — a token/slug that doesn't validate raises, is never written to
  `discovery_boards`. The response's reported `found` count is the **validated** posting count,
  never the raw row count (honesty-first, matching every other "what did we actually get" surface
  in this file).
- **An offline pre-deploy/operator check mirroring the same gate.**
  `scripts/validate_discovery_boards.py` — makes real outbound calls against every
  `DISCOVERY_*`-configured board (or ad-hoc candidates passed on the CLI), exits non-zero if any
  fails the real-postings check. Today this is a standalone operator tool — **not wired into CI**
  (grepped `.github/**/*.yml` for `validate_discovery_boards`: no hits) — so a board that quietly
  goes dead between deploys is caught only if someone remembers to run it by hand.
- **A wide, already-diverse, keyless-first connector roster.**
  `src/applicant/adapters/discovery/clients.py` — direct ATS connectors
  (`Live{Greenhouse,Lever,Workday,Ashby,SmartRecruiters}Client`, all keyless: public ATS listing
  APIs, no API key, no login) PLUS aggregator connectors
  (`Live{RemoteOk,Remotive,WorkingNomads}Client`, single global feeds, not per-company boards) PLUS
  `LiveJobSpyClient` (multi-board search library) / `LiveSearxngClient` (metasearch) /
  `LiveRssClient` (arbitrary feed ingestion) — each with a `Fake*` counterpart so the hermetic test
  lane runs with zero network (`live=False` default, `DISCOVERY_LIVE` opt-in per
  `src/applicant/adapters/discovery/factory.py`'s module docstring). None of these connectors
  filter by industry — they ingest whatever the source publishes; industry/role-fit narrowing
  happens downstream at the scoring gate (`core/rules/role_domain_fit.py`), never at ingestion —
  which is exactly the "can't limit ourselves to specific industries" requirement, already true by
  construction today.
- **Board configuration is env-driven and additive.** `src/applicant/app/config.py` —
  `discovery_greenhouse_boards` / `_lever_companies` / `_ashby_orgs` /
  `_smartrecruiters_companies` / `_workday_boards` (comma-separated tokens, `DISCOVERY_*` aliases),
  plus `discovery_rss_feeds`, `discovery_proxies`, and the pacing/backoff/circuit-breaker knobs
  (`discovery_rate_max_calls`, `discovery_backoff_*`, `discovery_block_max_retries`) — boards are
  added by appending a token, not by writing code.
- **A resilience layer this ADR's connectors already plug into.**
  `src/applicant/adapters/discovery/jobspy_searxng.py`, `SourceCircuitBreaker` — per-source
  `consecutive_failures` vs. `failure_threshold`, cooldown, `is_open()`/`allow()`/`record()` — a
  down/blocked/rate-limited source is isolated without an operator touching anything (ADR-0008
  detector #5). `PerBoardRateLimiter`/`ProxyConfig` give every connector the same pacing/proxy seam.
- **`easy_apply` tagging already ships across the connector roster.**
  `jobspy_searxng.py`, `detect_easy_apply()` (L270-307) plus the per-provider mappers
  (`_map_greenhouse_posting`, `_map_lever_posting`, `_map_ashby_posting`,
  `_map_smartrecruiters_posting`, `_map_workday_job`, each documented "assisted-apply parity fix")
  — every ATS connector's rows are tagged `easy_apply=True` so downstream can prioritize the
  quick-apply path consistently.
- **A source-reliability model this ADR's new connectors are NOT yet registered in.**
  `src/applicant/core/rules/source_reliability.py`, `SOURCE_TIERS` — maps a source-key prefix
  (`sample`/`jobspy`/`searxng`/`rss`/`greenhouse`/`lever`) to a trust tier used for reliability
  scoring/labelling. **Gap, grounded by absence:** `ashby`, `smartrecruiters`, `workday`,
  `remoteok`, `remotive`, `workingnomads` — all six connectors that already exist in
  `clients.py`/`factory.py` — are missing from this dict, so they fall through to the conservative
  "unknown → medium" default instead of the "direct public ATS API, no anti-bot 403s → high"
  (or aggregator-appropriate) tier their siblings already get.
- **A cold-start guard, so "wide net" never means "ungated."** `core/rules/discovery_gate.py`,
  `has_any_criterion`/`require_criteria_before_discovery` (#344) — discovery refuses to run until
  the campaign has at least one concrete search signal, so breadth never means surfacing arbitrary
  postings before the user has said what they want.

## Decision

Adopt **verified-source-only ingestion as a hard architectural gate**, paired with **maximum
source breadth, industry-agnostic, aggregator-first**, formalizing what the codebase has already
converged on independently across several sessions:

1. **Every posting that reaches `job_postings` must pass real-posting-shape validation, not mere
   non-emptiness.** `validate.validate_postings_shape`/`validate_provider_rows` is the single
   enforcement point, reused (never duplicated) at both the runtime `add_board` write path and the
   offline pre-deploy check. "Real" means: non-empty response AND at least one row carrying both a
   plausible title and a plausible identity/URL signal. A malformed response, an HTML error page
   that happens to coerce to a dict, or a 404-turned-`[]` all fail closed.
2. **Breadth strategy is keyless-connector-first, aggregator-prioritized, direct-connection
   supplementary.** Aggregators (jobspy, SearXNG, RSS, RemoteOk/Remotive/WorkingNomads) cast the
   widest net per unit of integration effort — one connector, many companies. Direct ATS
   connections (Greenhouse/Lever/Ashby/SmartRecruiters/Workday) are added per-company on top,
   useful where an aggregator under-covers a specific employer, never as the primary breadth
   mechanism. Every connector stays **keyless** where the ATS's public API allows it (zero API-key
   management, zero per-source cost) — the roster today is entirely keyless.
3. **No industry filter at ingestion, ever.** Discovery connectors fetch what the source publishes;
   they carry no title/role/industry allowlist. Narrowing to "is this posting relevant to THIS
   candidate" is exclusively `role_domain_fit`'s job, downstream, at scoring — never discovery's.
   This is already true by construction (grounded above); this ADR makes it an explicit invariant
   so a future connector is never tempted to pre-filter by industry to "clean up" its feed.
4. **Adding a board is validate-then-persist, always, both paths.** The runtime path
   (`DiscoveryService.add_board`) and the operator/CI path
   (`scripts/validate_discovery_boards.py`) both call the SAME `validate.py` gate — one
   enforcement point, two callers, per the standing reuse-first principle. The offline script
   should additionally run in CI (a genuine gap, not a design change — see Consequences) so a board
   that goes dead between deploys is caught automatically, not only when an operator remembers to
   run the script.
5. **Source-reliability tiering keeps pace with the connector roster.** `SOURCE_TIERS` is extended
   to cover every connector already shipped in `clients.py` (a data gap, not an architecture
   change) so reliability scoring/labelling reflects the real trust profile of each source instead
   of defaulting unclassified connectors to "medium."

## Consequences

**Positive:**

- Names and justifies, in one place, why the discovery layer looks the way it does (keyless-first,
  validate-then-persist, no industry filter) — future connectors have a document to follow instead
  of re-deriving the same decisions per source.
- The core enforcement mechanism (`validate.py`) already exists and is already the single
  reused gate at both call sites — this ADR ratifies an existing good pattern rather than
  introducing a new one.
- `easy_apply` tagging and circuit-breaker resilience already generalize across the whole
  connector roster — breadth doesn't dilute either invariant.

**Negative / risks:**

- **CI never runs the board-validation gate today** — a board silently going dead (renamed slug,
  ATS migration, board taken down) is invisible between manual operator runs. Recorded as an open
  story (EPIC DISCOVERY, DISC-4) rather than assumed covered.
- **`SOURCE_TIERS` is stale relative to the connector roster** — six live connectors
  (`ashby`/`smartrecruiters`/`workday`/`remoteok`/`remotive`/`workingnomads`) fall through to the
  conservative default tier instead of their appropriate one. A data-only fix (DISC-5), not a
  design change.
- **Breadth has a real ceiling the architecture doesn't remove**: aggregators/ATS boards that
  require login, paid API access, or aggressive anti-bot defenses stay out of scope for the
  keyless-first strategy (they are EPIC STEALTH's residential-proxy/browser-fingerprint problem,
  not this ADR's) — "as wide as possible" here means "as wide as possible without compromising the
  verified-source guarantee or the residential-IP-reputation guardrail," not literally unlimited.
- **Validation is shape-based, not semantic** — a row can pass `validate_provider_rows` (has a
  title + an identity/URL) and still be a bad posting in other ways (stale, mis-titled, off-domain)
  — those are `posting_quality.py`/`role_domain_fit.py`'s job downstream, not this gate's. This ADR
  only closes the "is this even a real posting" gap, by design; it does not claim to close every
  quality gap in one layer.

**Alternatives considered:**

- **Trust every configured source unconditionally (no shape gate)** — rejected: this is exactly
  the failure mode the product owner's rule exists to prevent ("verified sources… the only entity
  we receive is a job posting"); an unvalidated board silently pollutes the funnel with noise no
  downstream gate is designed to catch (role_domain_fit assumes it's looking at real postings).
- **Industry-scoped connectors (e.g., a tech-only aggregator, a finance-only board)** — rejected
  outright by the product owner's explicit instruction ("can't limit ourselves to specific
  industries"); breadth is a discovery-layer property, fit narrowing is a scoring-layer property,
  and conflating them would silently lose good roles in industries the connector author didn't
  anticipate.
- **Keyed/paid connectors as the primary breadth strategy** — rejected as the default: ongoing
  per-source cost and credential management don't scale the way a keyless public-API roster does;
  keyed sources remain an option (the `ProxyConfig`/client seams support them) but are not where
  breadth is grown first.
