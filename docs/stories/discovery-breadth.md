# DISCOVERY-BREADTH — Widen job-posting reach to maximum feasible coverage

**Backlog item:** `docs/APPLICANT-BACKLOG.md` line 58 (P1, CRITICAL-TO-QUALITY)
**Status:** Scoped, ready to slice into build waves
**Created:** 2026-08-10
**Scoping method:** Read-only code audit of this repo + live, read-only, keyless GET
requests against the *public* Greenhouse/Lever/Ashby/SmartRecruiters/Workable/RemoteOK/
Remotive/Arbeitnow/Jobicy/Himalayas/WeWorkRemotely/HN-Algolia job-board APIs themselves
(the exact same kind of anonymous HTTP call the shipped `LiveGreenhouseClient`/
`LiveLeverClient` already make) to verify real slugs/endpoints instead of guessing. No
code was edited, nothing was deployed, and the Applicant instance (10.0.1.11) was never
touched. Verification date: **2026-08-10**; job counts are a snapshot and will drift.

---

## Story

**As** the product owner running Applicant to find his next senior Agile-delivery role,
**I want** discovery to pull from the widest feasible set of job-posting sources —
every keyless ATS board, every free job-board API, and a resilient path through the
anti-bot-hardened sites —
**So that** the review queue is built from the largest possible unique-posting pool,
maximizing the odds a great-fit US-remote SM/RTE/Agile Coach/TPM/Delivery-Lead role is
seen before it's filled.

> Kevin, verbatim (`docs/APPLICANT-BACKLOG.md`): *"widen the net to as full a reach as I
> possibly can get — the most postings possible gives me the most edge."*

---

## Step 1 — Current discovery architecture (file-cited)

### 1.1 Correcting a naming collision (important)

The memory note `[[Applicant — ATS Discovery Connectors]]` and this task's brief both
point at `agent-zero/plugins/_discovery/`. **That directory is not the job-posting
discovery framework.** It's an Agent-Zero *plugin*-discovery UI feature (welcome-screen
cards that advertise other A0 plugins — Slack/WhatsApp/Telegram connectors, OAuth
setup, etc.), scoped by `agent-zero/plugins/_discovery/AGENTS.md`: *"Own contextual
plugin discovery cards and welcome-screen promotions."* It has nothing to do with job
postings.

The real job-discovery connector framework — the thing this story extends — lives at:

- `src/applicant/adapters/discovery/` — the adapters (network clients + `Source`
  implementations + the wiring factory).
- `src/applicant/application/services/discovery_service.py` — the orchestrating service
  (registry sync, run, dedup, yield learning, runtime board add/remove).
- `src/applicant/ports/driven/discovery.py` — the `DiscoveryPort` protocol.
- `src/applicant/core/entities/discovery_source.py` / `discovery_board.py` — persisted
  entities.
- `docs/extending.md` §2 "Add a new discovery source" — **the canonical, already-written
  extension-point doc**, with a working example (`RssSource`).
- `docs/discovery-source-reliability.md` — the existing reliability/verification-level
  contract for every source (this story's catalog below follows the same "state your
  verification level" convention).

### 1.2 The extension point — how pluggable is "a source"?

Very. `docs/extending.md:107-108`: *"A source implements the `Source` protocol
(`key: str` + `fetch(campaign_id, criteria) -> list[JobPosting]`)."* Concretely
(`src/applicant/adapters/discovery/jobspy_searxng.py:665-673`):

```python
@runtime_checkable
class Source(Protocol):
    key: str
    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]: ...
```

Adding a source is a **3-step, no-core-change** pattern (already proven 4 times over —
`JobSpySource`, `SearxngSource`, `RssSource`, `GreenhouseSource`/`LeverSource`):

1. **Client seam** in `clients.py` — a `Protocol` + a `Live*Client` (real `httpx` call,
   lazy-imported) + a `Fake*Client` (canned rows, default/test lane). This is the ONLY
   place discovery touches the network (`clients.py:1-11`).
2. **`Source` class** in `jobspy_searxng.py` — calls the client, maps the provider's raw
   shape into the shared `normalize_row(raw, campaign_id, source_key)` (title/company/
   url/location/work_mode/salary/description — zero LLM tokens, `jobspy_searxng.py:302`).
   `GreenhouseSource`/`LeverSource` (`jobspy_searxng.py:536-662`) are the templates for a
   "one fixed keyless endpoint per company/board-token" source.
3. **Registration** in `factory.py::build_default_discovery` — either a hardcoded dict
   (like `RSS_FEEDS`) or an env-configured tuple (like `GREENHOUSE_BOARD_TOKENS` /
   `LEVER_COMPANIES`, threaded from `Settings.discovery_greenhouse_boards` /
   `discovery_lever_companies` via `container.py:984-996`).

A source registered this way automatically gets: appears in `available_sources()`; seeded
enabled into per-campaign `discovery_sources` on `sync_registry`
(`discovery_service.py:115-139`); user-toggleable; feeds source-yield learning
(FR-DISC-5); covered by dedup, the rate limiter, and the circuit breaker for free — no
per-source resilience code required.

**Runtime (no-redeploy) add** exists too, but is currently narrower than the config path:
`DiscoveryService.add_board()` (`discovery_service.py:161-204`) lets a campaign owner add
one Greenhouse/Lever board at runtime via `POST /api/discovery-sources/{campaign_id}/boards`
(`app/routers/discovery_sources.py:84-91`), persisted to the `discovery_boards` table
(migration `0014_discovery_boards.py`). **Hard-coded gate:** `discovery_service.py:167`
—
```python
if provider not in ("greenhouse", "lever"):
    raise ValueError(f"unsupported provider '{provider}' ...")
```
— so today only these two provider strings are runtime-addable. Any new ATS-platform
connector type (Ashby, SmartRecruiters, …) needs this allow-list (and the paired
`_board_client`/`_default_board_source_builder`, `discovery_service.py:89-112`) widened
before it's runtime-addable the same way — see Slice B's prerequisite below.

### 1.3 What's registered today

| Source key(s) | Adapter | Registered by | Notes |
|---|---|---|---|
| `sample` | `SampleSource` | always | offline-only, clearly `example.test` fixture rows |
| `jobspy:linkedin`, `:indeed`, `:glassdoor`, `:google`, `:zip_recruiter` | `JobSpySource` | `factory.py:41` `JOBSPY_SITES` — hardcoded, all 5 "easy boards" **already wired**, not gated by env | `python-jobspy==1.1.82` (installed; `.venv/lib/python3.11/site-packages/python_jobspy-1.1.82.dist-info`) |
| `searxng` | `SearxngSource` | when `searxng_url` set | operator's own SearXNG metasearch instance |
| `rss:hn-hiring` | `RssSource` | `factory.py:46` hardcoded (`https://hnrss.org/jobs`) | **Not** the "Who is hiring" megathread — see Step 2 |
| `rss:custom-N` | `RssSource` | `DISCOVERY_RSS_FEEDS` env (comma-separated feed URLs) | operator-added feeds; zero new code needed for any RSS-native source (see Slice B note on WeWorkRemotely) |
| `greenhouse:{token}` | `GreenhouseSource` | `DISCOVERY_GREENHOUSE_BOARDS` env (comma-separated tokens) + runtime `add_board` | keyless `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` |
| `lever:{company}` | `LeverSource` | `DISCOVERY_LEVER_COMPANIES` env (comma-separated slugs) + runtime `add_board` | keyless `api.lever.co/v0/postings/{company}?mode=json` |

Baseline volume per the backlog item: 25 Greenhouse boards + 10 Lever companies (the
actual current `DISCOVERY_GREENHOUSE_BOARDS`/`DISCOVERY_LEVER_COMPANIES` values live in
the deployed `.env` on 10.0.1.11, not in this repo — `.env.example:79,83` ships both
**empty by default**, so the live list is operator config this scoping pass did not — and
per its read-only/no-ssh constraint, could not — read).

**jobspy detail:** `JobSpySource.fetch` (`jobspy_searxng.py:388-445`) defaults an unset/
"remote"/"anywhere" location to `location="United States"`, `is_remote=True`,
`country_indeed="usa"` — i.e. today's jobspy sweep is **US-remote scoped by design**,
exactly as the brief states. An explicit non-US `criteria.locations[0]` bypasses that
default and reaches jobspy's own per-country routing untouched. `hours_old=336` (~2
weeks) keeps every jobspy pull fresh. The installed `python-jobspy` package additionally
supports `bayt` (MENA) and `naukri` (India) sites (`jobspy/model.py:287-294`, `Site`
enum) — **not currently in `JOBSPY_SITES`** — low relevance for a US-remote target (see
catalog).

### 1.4 Dedup

Two layers, both already built:

1. **Within one run, cross-source:** `JobSpySearxngDiscovery.search`
   (`jobspy_searxng.py:849-891`) keeps an in-memory `seen: set[str]` of `source_url` and
   drops any posting whose exact URL repeats across sources in the same aggregation call.
2. **Cross-run, fuzzy:** `DiscoveryService._dedup` (`discovery_service.py:465-488`, #196)
   loads every previously-persisted posting for the campaign
   (`storage.postings.list_for_campaign`) and drops a new candidate whose
   `f"{title} {company}"` embedding similarity to any kept-this-run OR previously-
   persisted posting is `>= 0.97` (`_DEDUP_THRESHOLD`, local embeddings, NFR-LOCAL-1 — no
   LLM tokens). This is what makes "the same role showing up on 6 boards" collapse to one
   drafted application (AC (b) in the backlog item) — it is source-agnostic, so every new
   source added below inherits this dedup with zero new code.

### 1.5 Circuit breaker, rate limiter, pacing, scheduling

All three live in `jobspy_searxng.py` and are keyed by source `key`, so any new source
gets them automatically:

- **`SourceCircuitBreaker`** (`:97-151`) — opens after `failure_threshold=3` consecutive
  **real failures** (`SOURCE_ERROR`; a genuinely empty `SOURCE_EMPTY` run does NOT count),
  skips the source for `cooldown_seconds=1800` (30 min), then half-opens for one probe.
  This is the exact mechanism the backlog's AC (c) and EPIC SELF-HEAL's "discovery
  circuit-open" detector reference.
- **`PerBoardRateLimiter`** (`:47-86`) — 5 calls / 60s token bucket per source key,
  independent of the breaker.
- **`SourcePacer`** (`core/rules/source_pacing.py`, driven from
  `DiscoveryService._apply_pacing`, `discovery_service.py:417-445`) — spaces successive
  **postings on the same domain** at least 2s apart downstream of fetch, capped at a 10s
  total-wait budget per run so a large same-domain burst degrades to unpaced rather than
  hanging a scheduler tick.
- **Per-source outcome pipeline (H2)** — every queried source reports
  `ok`/`empty`/`error`/`rate_limited`/`cooldown` (`core/rules/underdelivery.py:22-29`),
  persisted to `discovery_sources.yield_stats.last_run`
  (`discovery_service.py:269-313`) and surfaced in the Digest + Settings → Job Searches
  panel — so a newly-added source's health is visible from day one, not silent.

### 1.6 Proxy / anti-bot infra hook

`ProxyConfig` (`jobspy_searxng.py:155-170`) is a designed-but-unused seam: `enabled=False`
unless `DISCOVERY_PROXIES` is set (`config.py:435`, threaded via `container.py:972-975`).
This is **separate** from the browser-automation egress proxy
(`EGRESS_PROXY_URL`/`EGRESS_RESIDENTIAL`, `.env.example:106-114`), which already exists
for the ATS-submission browser and explicitly supports a residential proxy with an
attestation flag. Per project memory (`[[VPS Egress Node]]`, `[[Cost-Conscious
Operation]]`), the infra to route through — a RackNerd WireGuard egress node and a
DataImpulse residential-proxy pool — already exists for other parts of the stack, but
**is not wired to `DISCOVERY_PROXIES` today**; that's pure config-plumbing (point
`DISCOVERY_PROXIES` at the same DataImpulse endpoint(s) already used for `EGRESS_PROXY_URL`),
not a new mechanism. See Slice F.

---

## Step 2 — Full reachable surface, feasibility-tagged

**Verification legend** (borrowing `docs/discovery-source-reliability.md`'s own
convention): **✅ live-verified** = this scoping pass made a real anonymous GET against
the platform's own public endpoint today and got real data back. **📚 vendor-doc** =
documented public behavior, not independently re-verified here. Every ✅ row's raw
request was identical in shape to what `LiveGreenhouseClient`/`LiveLeverClient` already
do in production — read-only, keyless, no Applicant system touched.

### 2.1 More ATS platforms — keyless public board JSON/XML (reuse the `Source` pattern)

| Platform | Endpoint pattern (keyless) | Verified? | Access | Effort | ToS/legal risk | Volume/relevance signal |
|---|---|---|---|---|---|---|
| **Greenhouse** (expand list) | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | ✅ existing prod source | keyless-public-JSON | reuse (config only) | low — public, documented, intentionally keyless | see quick-win list below |
| **Lever** (expand list) | `api.lever.co/v0/postings/{company}?mode=json` | ✅ existing prod source | keyless-public-JSON | reuse (config only) | low | see quick-win list below |
| **Ashby** | `api.ashbyhq.com/posting-api/job-board/{name}` | ✅ verified live — `openai`=741 jobs, `snowflake`=393, `perplexity`=92, `vanta`=85, `mercor`=85, `benchling`=51, `miro`=44, `attio`=42, `watershed`=33, `confluent`=29, `oyster`=19, `substack`=12, `posthog`=11, `gitbook`=2, `deel`=0-but-valid | keyless-public-JSON | new keyless connector | low — public, documented posting API | **highest-volume single find of this pass**; skews AI/2020s-startup, but several (Confluent, Snowflake, Vanta) are exactly the mid/large-SaaS profile that runs formal Agile practices |
| **SmartRecruiters** | `api.smartrecruiters.com/v1/companies/{id}/postings` | ✅ endpoint confirmed live (Visa=2 postings); several guessed company IDs 404/0 — **exact company IDs need a discovery pass, not guaranteed = display name** | keyless-public-JSON | new keyless connector | low — documented public API | skews **large enterprise** (retail, manufacturing, finance) — the employer profile statistically most likely to formally title roles "Scrum Master"/"RTE"/"Agile Coach" |
| **Workable** | `apply.workable.com/api/v1/widget/accounts/{account}` | ✅ endpoint confirmed live (Typeform/ContentSquare/Aircall/Algolia/Loom all resolve; 0 open jobs at check-time ≠ invalid, some accounts appear dormant) | keyless-public-JSON | new keyless connector | low — public widget API, documented | mid-size SaaS/startups |
| **Recruitee** | `{company}.recruitee.com/api/offers/` | 📚 documented pattern; two guessed subdomains 404'd (wrong slug guesses, not a dead pattern) | keyless-public-JSON | new keyless connector | low | EU-leaning mid-size |
| **Teamtailor** | careers-page `.json` suffix / `api.teamtailor.com` (public read scope) | 📚 documented, not independently re-verified this pass | keyless-public-JSON (public jobs endpoint) | new keyless connector | low | strongly EU/Nordic-leaning — low US-remote relevance |
| **Personio** | `{company}.jobs.personio.de/xml` (recruiting XML export) | ✅ endpoint pattern confirmed live (redirects 307 to the real feed — a real, documented Personio feature, not a guess) | keyless-public-**XML** | new keyless connector (XML, not JSON — closer to the existing `RssSource`/`_parse_feed_xml` pattern than to Greenhouse) | low | DACH/EU SMB-leaning — low US-remote relevance |
| **Jobvite** | no stable public keyless JSON endpoint found; typically requires a partner/embed key or per-tenant widget scraping | not verified — 📚 general knowledge only | scrape-anti-bot / keyed-partner | new keyed or scrape connector | medium — terms vary per tenant | uncertain; **recommend deprioritizing** |
| **iCIMS** | no stable public keyless JSON endpoint found; per-tenant widget HTML | not verified | scrape-anti-bot | new scrape connector | medium-high — fragile per-tenant markup | uncertain; **recommend deprioritizing** |
| **BambooHR** | `{company}.bamboohr.com/careers/list` unofficial JSON widget | 📚 documented by community, not verified live this pass | keyless-public-JSON (unofficial) | new keyless connector | low-medium — unofficial/undocumented, could change without notice | skews **small business** — low individual-company volume, but very numerous companies |
| **Workday** | `{tenant}.wd1.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` (POST, per-tenant CXS API) | 📚 well-documented pattern, not verified this pass | keyless-public-JSON **but per-tenant** | new connector, **materially harder**: every employer is its own tenant+site pair (no shared "list of companies" the way Greenhouse/Lever/Ashby have public token directories), each must be individually discovered and configured | low-medium ToS risk per se, but **operationally the highest effort-per-company of any keyless platform** — flagged explicitly per the task brief; **defer**, don't slice into the initial wave |

### 2.2 Keyless remote-job boards / aggregator APIs (each = access to thousands of companies via ONE connector)

| Source | Endpoint | Verified? | Volume signal (live, 2026-08-10) | Relevance note |
|---|---|---|---|---|
| **RemoteOK** | `remoteok.com/api` | ✅ 200, 101 rows/page, real postings (mixed quality — first rows included non-tech noise) | ~100/page, paginated | remote-first, mixed quality; filter hard |
| **Remotive** | `remotive.com/api/remote-jobs?search=agile` | ✅ 200 — **search=`agile` returned 20 of 20 total matches directly** | keyword-filterable server-side | **best relevance-to-effort of any new source found**: the API itself pre-filters, so `search=agile`/`search=scrum`/`search=program+manager` queries land close to the exact target roles |
| **WeWorkRemotely** | category RSS, e.g. `weworkremotely.com/categories/remote-programming-jobs.rss` | ✅ 200, valid RSS | per-category feed | **zero new code** — it's RSS, drops straight into the existing `RssSource` / `DISCOVERY_RSS_FEEDS` config exactly like `rss:hn-hiring` today; there's no "remote management & finance" or similar category worth checking for PM/Agile-adjacent roles specifically |
| **Himalayas** | `himalayas.app/jobs/api` | ✅ 200 — **totalCount: 101,873** | huge aggregate corpus, needs query/keyword narrowing | largest single corpus found; unclear default relevance without a search param — needs a short investigation of its query syntax during build |
| **Arbeitnow** | `arbeitnow.com/api/job-board-api` | ✅ 200, 176 postings in one page | EU-leaning (name is German) but includes remote/US listings | moderate volume, moderate relevance |
| **Jobicy** | `jobicy.com/api/v2/remote-jobs?tag=agile` | ✅ 200, tag-filterable (`tag=agile` → 5 results at check-time) | small but pre-filtered like Remotive | low volume, high relevance-per-result |
| **HN "Who is hiring" (Algolia)** | `hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring` → then fetch that story's comments | ✅ verified — August 2026 thread has **321 top-level comments** (each is one company's posting) | ~300+/month, refreshed monthly | **materially different from, and additive to, the already-wired `rss:hn-hiring` source** — see note below |
| **Adzuna** | REST API, `app_id`+`app_key` required (free registration) | not called (needs a key this pass doesn't have) | 📚 large aggregator, broad category/keyword search including "Agile"/"Scrum"/"Project Manager" | keyed-API; likely **highest-volume single keyed source** given its breadth — recommend prioritizing key acquisition |
| **USAJobs** | REST API, `Authorization-Key` required (free registration) | not called | 📚 US federal jobs only | niche — federal "Agile Coach"/"IT Program Manager" postings exist but volume is small relative to the private-sector target |
| **The Muse** | `themuse.com/api/public/jobs?category=...` | ✅ 200 (category param name needs tuning — a guessed category returned 0; the endpoint itself is live and keyless) | 📚 startup/mid-size, has a "Project & Product Management" category | low-medium volume, decent relevance |

**Important nuance on HN:** the already-wired `rss:hn-hiring` (`https://hnrss.org/jobs`)
is **not** the monthly "Who is hiring" megathread — live-verified this pass, it's HN's
own `job` tag (mostly YC-network companies posting directly), returning ~20 items total.
The monthly megathread (321 top-level comments this month) is a **separate, much
higher-volume, and NOT currently reached** source. It needs a small 2-step connector
(find this month's thread via Algolia search, fetch its comments, treat each top-level
comment as one loose posting) rather than a flat RSS/JSON list — it's still fully
keyless and reuses the `Source` pattern, just not a 1-call fetch.

### 2.3 jobspy site expansion

- **Already enabled, no work needed:** LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter
  — all 5 "easy boards" are already in `JOBSPY_SITES` (`factory.py:41`). The backlog's
  "widen jobspy" instinct is already partially true in code; what's NOT yet resilient is
  their real-world block rate (see Slice F).
- **`bayt` (MENA) / `naukri` (India)** — supported by the installed `python-jobspy`
  library (`jobspy/model.py:287-294`), zero new client code, purely `JOBSPY_SITES` config
  — but **low relevance** for a US-remote target; low priority.

### 2.4 What to AVOID (ToS/anti-bot risk not worth it)

- **Scraping LinkedIn beyond what `python-jobspy` already does.** LinkedIn's ToS
  explicitly prohibits scraping; `python-jobspy`'s LinkedIn scraper is already the
  highest-risk source in the stack (`docs/discovery-source-reliability.md` flags its
  fragility). Pushing more query volume at it (rather than pacing/proxying it better)
  raises block risk for marginal gain — proxy/harden it (Slice F), don't intensify it.
  This is currently a **jobspy-supplied** integration; there is no first-class,
  keyless LinkedIn Jobs API to add as a separate connector.
- **iCIMS / Jobvite generic scraping.** No stable public keyless API found for either;
  building a per-tenant HTML scraper for these is high-maintenance (fragile markup),
  ToS-uncertain per employer, and duplicates effort better spent on Ashby/SmartRecruiters/
  Workable, which have real documented public APIs. Deprioritize both.
- **Workday at scale.** Real and keyless per-tenant, but there is no discoverable
  directory of "which companies use Workday" the way Greenhouse/Lever/Ashby expose a
  token registry — each employer must be found and configured one at a time. Effort-per-
  company is far worse than any other row in the catalog. Defer past the initial wave;
  revisit only if a specific target employer is known to run Workday.
- **Any Indeed/Glassdoor scraping *outside* `python-jobspy`.** Both are already reachable
  through the existing, resilience-wrapped jobspy connector; a bespoke second path would
  violate the STANDING reuse-first/no-redundancy principle for no yield gain.

---

## Quick win — expanded Greenhouse + Lever slug lists (ready to paste)

**How these were produced:** every slug below was **live-verified** against the real
`boards-api.greenhouse.io` / `api.lever.co` public endpoints during this scoping pass
(2026-08-10) — not guessed from memory. Dozens of additional plausible company-name
guesses were tried and came back 404 (wrong slug or the company isn't on that platform)
and are **not** included — only confirmed-live tokens made this list, so **nothing below
needs an "unsure" flag**. Job counts are a same-day snapshot and will drift; a `0`-count
company is still a **valid, live board** (registering it costs nothing and it may post
later) — none were dropped for being quiet today.

Paste-ready, in the exact `DISCOVERY_GREENHOUSE_BOARDS` / `DISCOVERY_LEVER_COMPANIES`
comma-separated shape (`factory.py::_parse_greenhouse_boards`/`_parse_lever_companies`,
`.env.example:79,83`).

### Greenhouse — 65 verified tokens

```
databricks,stripe,datadog,mongodb,anthropic,okta,toast,brex,cloudflare,samsara,braze,elastic,pinterest,scaleai,remotecom,affirm,gitlab,fivetran,airbnb,coinbase,lyft,twilio,reddit,figma,flexport,klaviyo,asana,robinhood,intercom,instacart,smartsheet,justworks,gusto,wrike,hightouch,faire,carta,newrelic,mixpanel,chime,peloton,mercury,discord,gofundme,attentive,dropbox,airtable,amplitude,cultureamp,webflow,pagerduty,turing,glossier,squarespace,nextdoor,harrys,calendly,lattice,kickstarter,doximity,postscript,medium,hubspot,calm
```

Open-req snapshot at verification time, highest first (for sequencing which to enable
first if you want to phase the rollout): `databricks`(810), `stripe`(557), `datadog`(445),
`mongodb`(406), `anthropic`(391), `okta`(344), `toast`(333), `brex`(299), `cloudflare`(296),
`samsara`(290), `braze`(257), `elastic`(244), `pinterest`(219), `scaleai`(209),
`remotecom`(202), `affirm`(201), `gitlab`(189), `fivetran`(183), `airbnb`(182),
`coinbase`(172), `lyft`(171), `twilio`(167), `reddit`(165), `figma`(165), `flexport`(160),
`klaviyo`(148), `asana`(146), `robinhood`(135), `intercom`(122), `instacart`(114),
`smartsheet`(99), `justworks`(95), `gusto`(92), `wrike`(85), `hightouch`(68), `faire`(65),
`carta`(60), `newrelic`(59), `mixpanel`(58), `chime`(58), `peloton`(56), `mercury`(55),
`discord`(48), `gofundme`(41), `attentive`(40), `dropbox`(38), `airtable`(33),
`amplitude`(32), `cultureamp`(28), `webflow`(27), `pagerduty`(25), `turing`(24),
`glossier`(22), `squarespace`(19), `nextdoor`(15), `harrys`(14), `calendly`(11),
`lattice`(7), `kickstarter`(7), `doximity`(7), `postscript`(6), `medium`(1), `hubspot`(0
today), `calm`(0 today). Sum of open reqs across the list right now: **~9,017** (raw, all
role types — the discovery `_matches` title/keyword filter narrows this to the
campaign's actual Agile/delivery-leadership criteria at run time, so this is a raw
denominator, not an expected relevant-match count).

**Companies tried and confirmed NOT on Greenhouse this pass** (so they aren't wasted
config, and to save a future pass from re-guessing): `doordash`, `notion`, `hashicorp`,
`confluent`, `snowflake`, `docusign`, `zoom`, `plaid`, `ramp`, `miro`, `benchling`,
`grammarly`, `canva`, `gem`, `oyster`, `angellist`, `patreon`, `substack`, `invision`,
`sentry`, `segment`, `zendesk`, `freshworks`, `drift`, `gong`, `outreach`, `clari`,
`vanta`, `retool`, `deel`, `rippling`, `gitbook`, `shopify`, `wix`, `zillow`, `redfin`,
`opendoor`, `whoop`, `strava`, `warbyparker`. **Several of these are on Ashby instead**
(confirmed live — see §2.1/Slice B), which is exactly why Slice B matters: the GH/Lever
quick win alone leaves real, sizeable boards (`openai`=741, `snowflake`=393,
`confluent`=29, `vanta`=85, `deel`=0-but-valid, `miro`=44, `oyster`=19, `gitbook`=2,
`substack`=12) on the table.

### Lever — 24 verified tokens

```
gopuff,palantir,spotify,includedhealth,masterycharter,ro,toptal,outreach,angellist,entrata,royalambulance,hottopic,enablecomp,gettyimages,houzz,plaid,brightwheel,whoop,freshworks,clari,highspot,kpmg,nielsen,rackspace
```

Open-req snapshot: `gopuff`(809), `palantir`(311), `spotify`(98), `includedhealth`(144),
`masterycharter`(54), `ro`(51), `toptal`(25), `outreach`(31), `angellist`(22),
`entrata`(14), `royalambulance`(14), `hottopic`(18), `enablecomp`(12), `gettyimages`(8),
`houzz`(7), then 9 confirmed-live-but-0-today: `plaid`, `brightwheel`, `whoop`,
`freshworks`, `clari`, `highspot`, `kpmg`, `nielsen`, `rackspace`. Sum of open reqs: **~1,618**.

Note: Lever's public keyless-board market share is materially smaller than Greenhouse's
today (many well-known companies that historically used Lever — Netflix, Eventbrite,
Yelp, Shopify, Atlassian, Slack-era darlings — have since migrated to Greenhouse, Ashby,
or in-house ATS; each was tried this pass and came back 404). `palantir` and `gopuff`
carry most of this list's volume; `spotify` and `includedhealth` are the next-best finds.
The lower yield here vs. Greenhouse is a real market fact, not under-research — it's the
reason Ashby (Slice B) matters more for Lever-shaped gaps than a longer Lever list would.

**Relevance note (both lists):** the mid/large SaaS and fintech names — Databricks,
Stripe, Datadog, MongoDB, Okta, GitLab, Cloudflare, Twilio, Asana, PagerDuty, New Relic,
Smartsheet, Wrike, Spotify, Palantir — are exactly the employer profile that runs formal
Agile/SAFe practices and regularly opens Scrum Master/RTE/Agile Coach/TPM/Delivery Lead
requisitions. The consumer/DTC names (Harry's, Glossier, Casper-adjacent) are lower-yield
for this specific title set but cost nothing extra to leave enabled.

---

## Sliced stories

Every slice below satisfies the STANDING conventions
(`docs/APPLICANT-BACKLOG.md:5-13`): DoR, BDD Gherkin AC, DoD, full TDD+BDD, verified on
10.0.1.11, resilient to a fresh install. Every new source reuses the existing `Source`
protocol + `normalize_row` + dedup + rate limiter + circuit breaker + outcome pipeline —
**no bespoke one-off connector mechanism is proposed anywhere below** (reuse-first, ties
to EPIC SELF-HEAL's existing "discovery circuit-open" detector).

### Slice A — Greenhouse/Lever quick-win expansion (config only)

**Summary:** Set `DISCOVERY_GREENHOUSE_BOARDS` / `DISCOVERY_LEVER_COMPANIES` (compose/.env
on 10.0.1.11) to the two verified lists above, replacing or merging with the current
25+10. Zero code change — `factory.py`'s parsing/registration path already exists and is
tested (`tests/unit/test_discovery_greenhouse_lever.py`).

**DoR:**
- [ ] Current live `DISCOVERY_GREENHOUSE_BOARDS`/`DISCOVERY_LEVER_COMPANIES` values on
      10.0.1.11 read (to decide merge vs. replace — this scoping pass could not read them,
      no-ssh constraint).
- [ ] Confirm no per-board opt-outs exist that a blind replace would silently drop.

**AC (BDD):**
```gherkin
Feature: Expanded Greenhouse/Lever board list ingests more unique postings

  Scenario: The expanded board list registers as individually-toggleable sources
    Given DISCOVERY_GREENHOUSE_BOARDS and DISCOVERY_LEVER_COMPANIES are set to the
      expanded lists
    When the discovery service boots and syncs its registry
    Then every new board appears in discovery_sources for the campaign, enabled by default
    And each is independently toggleable exactly like the original 25+10

  Scenario: A discovery cycle surfaces materially more unique postings
    Given the expanded source set is enabled
    When a discovery cycle runs
    Then the count of unique postings ingested this cycle is materially higher than the
      pre-expansion baseline
    And no posting already seen from an original source is duplicated under a new source
      key (cross-run embedding dedup holds)

  Scenario: A newly-added board that 404s or times out never breaks the run
    Given one of the newly-added board tokens is invalid or the board is temporarily down
    When discovery runs
    Then that source records a SOURCE_ERROR/SOURCE_EMPTY outcome
    And every other source's results are unaffected
    And the circuit breaker opens after 3 consecutive real failures, exactly as it does
      for the original boards
```

**DoD:** `.env`/compose on 10.0.1.11 updated with the expanded lists (fresh-install
resilient — `.env.example` documents the shape, values are operator config not code);
`discovery_sources` shows every new key after a registry sync; a live `run_discovery`
shows a materially higher unique-posting count than pre-change; dedup + circuit-breaker
behavior spot-checked on at least 2 intentionally-broken tokens; existing
`test_discovery_greenhouse_lever.py` still green (proves the parsing path is unchanged).

**Reach delta (rough order of magnitude):** ~9,017 + ~1,618 = **~10,600 raw open
requisitions** newly reachable across 89 companies (65 GH + 24 Lever, net of whatever
overlap exists with the current unknown 25+10). After the campaign's actual title/keyword
filter, a defensible rough estimate is **+50 to +200 unique relevant postings per
discovery cycle** — this is the single highest-leverage, lowest-effort slice in this
story (pure config, same day turnaround).

---

### Slice B — New keyless-JSON/XML ATS connectors (batched, one connector-pattern slice)

**Summary:** Add `Source` implementations for Ashby, SmartRecruiters, Workable,
Recruitee, Teamtailor, and Personio (XML), reusing the exact `Client Protocol + Live +
Fake` / `Source` / `factory.py` registration pattern documented in `docs/extending.md`
§2 and already proven by `GreenhouseSource`/`LeverSource`. Also folds in the HN "Who is
hiring" Algolia connector (keyless, same pattern, 2-step fetch).

**Architectural prerequisite (STANDING reuse-first principle):** six near-identical
"fetch one keyless JSON list, map 4-5 fields, normalize" connectors is exactly the kind
of duplication `docs/APPLICANT-BACKLOG.md:13`'s reuse-first principle warns against.
Before writing 6 one-off `*Source` classes, extract a single generic, config-driven
`JsonBoardSource` (endpoint template + a small per-provider field-mapping function/dict,
analogous to `_map_greenhouse_job`/`_map_lever_posting` in `jobspy_searxng.py:576-662`)
that `GreenhouseSource`/`LeverSource` themselves could arguably be refactored onto later.
This is a **design decision for the slice's DoR**, not a foregone conclusion — it may
turn out the existing per-provider-class pattern is clearer; either way, decide
deliberately rather than copy-pasting six classes.

**Second prerequisite:** widen `DiscoveryService.add_board`'s hardcoded
`("greenhouse", "lever")` allow-list (`discovery_service.py:167`) and its paired
`_board_client`/`_default_board_source_builder` if these new providers should also be
runtime-addable via the existing `/api/discovery-sources/{campaign_id}/boards` endpoint
(recommended — it's the same UI surface a user already knows).

**DoR:**
- [ ] `JsonBoardSource`-vs-per-class design decision made (above).
- [ ] `add_board` provider allow-list widening scoped (above).
- [ ] Exact company-ID discovery approach for SmartRecruiters decided (this pass
      confirmed the endpoint is real and live but could not confirm company IDs beyond
      `Visa` — display name ≠ company ID is a real gotcha to design around, e.g. surfacing
      a clear error rather than a silent empty result on a wrong ID).
- [ ] Personio's XML shape reviewed against `clients.py::_parse_feed_xml`'s existing
      entity-expansion DoS guard — reuse it rather than a second parser.

**AC (BDD):**
```gherkin
Feature: New ATS platforms plug into the existing discovery framework

  Scenario: A new ATS type is a Source, not a special case
    Given an Ashby (or SmartRecruiters/Workable/Recruitee/Teamtailor/Personio) board is
      registered via factory.py, following the Source protocol
    When available_sources() is queried
    Then the new source key appears exactly like greenhouse:*/lever:* do
    And no core domain, port, or DiscoveryService code needed to change

  Scenario: Zero-network hermetic default lane holds
    Given the default (non-live) test lane
    When any new source's fetch() is exercised
    Then it uses a Fake*Client with canned rows, never touching the real network
    And the existing test suite stays fully offline

  Scenario: A blocked/misconfigured new source degrades exactly like existing sources
    Given a new source's client raises or the endpoint 404s
    Then the source records SOURCE_ERROR, never crashes the run
    And the circuit breaker + rate limiter apply identically to greenhouse/lever sources

  Scenario: The HN "Who is hiring" megathread is reachable, distinct from rss:hn-hiring
    Given the current month's "Ask HN: Who is hiring?" thread exists
    When the HN-hiring-thread source fetches
    Then it resolves the current thread via the Algolia search API
    And parses its top-level comments into loose postings distinct from the rss:hn-hiring
      feed's own items (no double-registration under the same source key)
```

**DoD:** each new `Source` shipped behind a `Live*Client`/`Fake*Client` seam; unit tests
hermetic (no real network in CI, matching existing convention); at least one live-verified
company/board per new platform (this scoping pass already has one each for Ashby,
SmartRecruiters, Workable, Personio — reuse those as the first configured boards); BDD
scenarios above green; runtime `add_board` widened if the DoR decision says so; verified
on 10.0.1.11 with at least the platforms/boards this pass confirmed live; resilient to a
fresh install (new sources default OFF or to an empty configured list — never invented).

**Reach delta:** Ashby alone, seeded even conservatively (the 15 companies this pass
sampled), is **~1,639 raw open reqs** — comparable to a third of the entire Slice-A
Greenhouse list from a single new platform; a fuller Ashby seed (Ashby is popular with
2020s/AI-era companies) plausibly reaches several thousand raw reqs. SmartRecruiters/
Workable skew toward larger, more traditional enterprises — statistically the segment
most likely to use the literal titles "Scrum Master"/"Release Train Engineer"/"Agile
Coach" — so their per-posting relevance rate to this candidate's target titles is likely
**higher** than the median Greenhouse/Ashby startup posting, even if raw volume per
company is smaller. Rough order of magnitude: **+100-400 unique relevant postings per
cycle** once several dozen companies are seeded across these platforms. The HN megathread
connector alone adds ~300+/month of raw signal, historically skewing engineering-heavy
but reliably containing PM/TPM/Agile-adjacent listings bundled into "we're also hiring
for..." comments.

---

### Slice C — Keyed-API aggregator sources (separate slice: needs registration + secret management)

**Summary:** Add Adzuna, USAJobs, and The Muse as sources. Unlike Slices A/B these need a
free API key/registration — an out-of-band human step (the agent cannot self-register for
third-party services), plus a new `Settings` field + secret-injection pattern (mirror the
already-shipped `LLM_FALLBACK_API_KEY` pattern per `docs/APPLICANT-BACKLOG.md:54`) rather
than the plain env-string pattern Greenhouse/Lever use.

**DoR:**
- [ ] Kevin (or an authorized human) registers for Adzuna's and USAJobs's free developer
      keys; the keys are supplied out-of-band (never typed into chat/committed) exactly
      like the MODEL-RESILIENCY fallback-tier key.
- [ ] Confirm The Muse's public endpoint truly needs no key at low volume (rate limits at
      higher volume without one) or budget for its optional key too.
- [ ] Secret-injection channel confirmed (same pattern as `LLM_FALLBACK_API_KEY` — never
      committed, env-injected at deploy time).

**AC (BDD):**
```gherkin
Feature: Keyed aggregator APIs extend discovery without a key by default

  Scenario: Unset key means the source stays off, byte-identical to today
    Given ADZUNA_APP_ID/ADZUNA_APP_KEY (or USAJOBS_API_KEY) are unset
    When the discovery registry builds
    Then the corresponding source is not registered
    And the discovery run's behavior is byte-identical to before this slice

  Scenario: A configured key registers a working keyword-narrowed source
    Given ADZUNA_APP_ID/ADZUNA_APP_KEY are set
    When discovery runs with the campaign's Agile/delivery-leadership search criteria
    Then Adzuna is queried with those terms
    And results normalize through the same normalize_row() as every other source

  Scenario: An invalid or revoked key degrades like any other source failure
    Given the configured key is invalid or Adzuna 401s
    Then the source records SOURCE_ERROR
    And the digest's shortfall message names it plainly ("Adzuna could not be searched...")
```

**DoD:** new `Settings` fields (`ADZUNA_APP_ID`/`ADZUNA_APP_KEY`, `USAJOBS_API_KEY`,
optional `THEMUSE_API_KEY`), OFF without a key (fresh-install resilient, matches the
`LLM_FALLBACK_*` precedent exactly); `Source`/client pair per API; BDD scenarios green;
verified live on 10.0.1.11 once Kevin supplies real keys.

**Reach delta:** Adzuna aggregates across the broader open job-search web with real
keyword/category search including "Agile"/"Scrum"/"Program Manager" — likely the
**single highest raw-volume keyed source** in this catalog, plausibly thousands of
postings with hundreds relevant after filtering, but unverified without a key (flagged
honestly rather than invented). USAJobs is niche (federal-only) — small but occasionally
exact-title matches ("Agile Coach", "IT Program Manager"). The Muse is low-medium.

---

### Slice D — jobspy site expansion (bayt/naukri) — low priority, note only

**Summary:** Add `"bayt"`, `"naukri"` to `JOBSPY_SITES` (`factory.py:41`). Pure config,
zero new client code (already in the installed library).

**DoR/AC/DoD:** trivial — a one-line tuple change + one test asserting both keys appear
in `available_sources()`. **Recommend deferring or skipping**: Bayt is MENA-focused,
Naukri is India-focused; near-zero relevance to a US-remote senior Agile-leader search.
Include only if/when the candidate's search ever broadens geographically.

**Reach delta:** ~0 net relevant reach for the stated target profile.

---

### Slice E — Anti-bot resilience / proxy routing for the jobspy live sites

**Summary:** Wire `DISCOVERY_PROXIES` (already a real, tested config seam —
`ProxyConfig`, `container.py:972-975`) to the existing external egress infra (RackNerd
WireGuard node + DataImpulse residential proxy pool, per `[[VPS Egress Node]]`) the same
way `EGRESS_PROXY_URL`/`EGRESS_RESIDENTIAL` already does for the ATS-submission browser.
This doesn't add a new source — it **protects the yield of the 5 already-registered
jobspy sources** (LinkedIn/Indeed/Glassdoor/Google/ZipRecruiter), which
`docs/discovery-source-reliability.md` already flags as the most block-prone sources in
the stack, and it directly feeds EPIC SELF-HEAL's "discovery circuit-open" detector
(a source that's proxied through a clean residential exit should trip the breaker far
less often).

**DoR:**
- [ ] Confirm the DataImpulse pool's terms permit this use (job-board scraping through a
      residential proxy is exactly `python-jobspy`'s own documented recommended mitigation
      for anti-bot blocks — not a novel or higher-risk use of that infra).
- [ ] Decide whether discovery shares the same proxy pool as the ATS-submission browser
      or gets its own allocation (shared risk of one flagged IP affecting both flows is a
      real tradeoff to weigh).

**AC (BDD):**
```gherkin
Feature: Discovery routes hostile boards through a residential proxy when configured

  Scenario: Proxy config is off by default, byte-identical to today
    Given DISCOVERY_PROXIES is unset
    Then ProxyConfig.enabled is False and every jobspy/board call goes out direct,
      exactly as today

  Scenario: A configured proxy is threaded to every live client call
    Given DISCOVERY_PROXIES is set to the DataImpulse endpoint(s)
    When a jobspy source fetches
    Then the proxy list is passed through to python-jobspy's scrape_jobs(proxies=...)

  Scenario: Circuit-breaker open rate drops for previously-blocked boards
    Given LinkedIn/Indeed/Glassdoor were tripping the circuit breaker under direct egress
    When the same sources run proxied
    Then their SOURCE_ERROR rate over a comparable window is measurably lower
      (fault-injection / live-monitoring comparison, ties to EPIC SELF-HEAL S2's detector
      event bus for evidence)
```

**DoD:** `DISCOVERY_PROXIES` set on 10.0.1.11 to a real DataImpulse endpoint; a live run
shows jobspy calls going out through the proxy (verified via the proxy's own access log
or an IP-echo check); circuit-breaker open/close events for the 5 jobspy sources
monitored before/after; resilient to a fresh install (unset = today's exact behavior).

**Reach delta:** not a new-source addition — a **resilience multiplier** on the existing
baseline. If LinkedIn/Indeed/Glassdoor are currently tripping the breaker and sitting in
30-minute cooldowns some fraction of the time, this slice's delta is the difference
between "5 sources at full yield" and "5 sources at partial/degraded yield" — plausibly
the largest single lever in this entire story if those sources are currently
block-heavy, but its size is unmeasured from this read-only pass (no live block-rate
telemetry was available to inspect).

---

## Sequencing recommendation (ROI order)

1. **Slice A** (GH/Lever expansion) — same-day, zero code, +50-200 relevant postings/cycle.
2. **Slice B** (Ashby/SmartRecruiters/Workable/Recruitee/Teamtailor/Personio + HN
   megathread) — highest volume of any new-platform work, reuses the proven pattern,
   +100-400/cycle once seeded.
3. **Slice E** (proxy hardening) — protects/restores yield on the highest-existing-volume
   sources (the 5 jobspy boards); do this before or alongside B if block rates are
   currently high, since it's cheap and multiplies everything already running.
4. **Slice C** (Adzuna/USAJobs/The Muse) — gate on Kevin supplying free API keys
   (5-minute human task each); potentially the single biggest aggregator once unlocked.
5. **Slice D** (bayt/naukri) — skip or defer; near-zero relevance to the stated target.

---

## Top 3 highest-ROI slices (for the report back)

1. **Slice A** — Greenhouse/Lever list expansion. Zero code, same-day, ~10,600 raw open
   reqs newly reachable across 89 live-verified companies.
2. **Slice B** — Ashby (openai=741, snowflake=393, vanta=85, perplexity=92, mercor=85
   live-verified) + SmartRecruiters/Workable as a batched new-connector-pattern slice;
   single highest new-platform volume found, reuses the existing framework end-to-end.
3. **Slice E** — Proxy the already-registered LinkedIn/Indeed/Glassdoor/Google/
   ZipRecruiter jobspy sources through the existing DataImpulse/WireGuard infra; not a
   new source, but plausibly the largest yield-recovery lever on the sources already
   generating the majority of current volume.

## Sources to AVOID (ToS/anti-bot risk not worth it)

- Bespoke LinkedIn scraping beyond `python-jobspy`'s own scraper (ToS-prohibited;
  proxy/harden the existing connector instead of adding a second, riskier path).
- iCIMS / Jobvite generic per-tenant scraping (no stable public keyless API found;
  fragile, ToS-uncertain, high effort for uncertain yield).
- Workday at scale (real and keyless, but no company-directory the way Greenhouse/Lever/
  Ashby have one — each employer is a manual per-tenant discovery+config effort; defer).
- A second bespoke Indeed/Glassdoor path outside `python-jobspy` (pure redundancy against
  the STANDING reuse-first principle, zero yield gain).
