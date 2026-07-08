# Discovery source reliability matrix (P2-13)

This is the code-derived reliability contract for every discovery adapter behind
`applicant.adapters.discovery` — what each source supports, how it fails, how it
degrades, and how a failure/degrade actually reaches the owner. It extends the H2
("no silent underdelivery") work already on `main`, which built the per-source
outcome pipeline this doc describes; P2-13 adds the region/category quality tests
and writes the expectations down in one place.

**Honesty about verification level (read this first).** Everything below is verified
one of two ways, and each row/section says which:

- **Static/hermetic** — read directly from the adapter code, or exercised by a test
  that runs fully offline against the fake client seam (`clients.py`'s
  `FakeJobSpyClient`/`FakeSearxngClient`/`FakeRssClient`, never the network). This is
  what CI runs on every PR.
- **Community/vendor knowledge, NOT verified live in this container** — regional/
  category coverage claims about the real boards (e.g. "ZipRecruiter is US/CA-only")
  come from the `python-jobspy` project's own documentation and general operator
  knowledge, not from a live probe run here. No outbound call to a real job board was
  made while producing this document or its tests — see `docs/known-issues.md` /
  `docs/delivery-status.md`'s Phase-2 remaining list, which already flags P2-13 as
  needing a **live-deploy** pass to confirm real-world coverage. That pass is
  `tests/integration/test_discovery_live.py` (`DISCOVERY_LIVE_TEST=1`, network-gated,
  skipped by default) plus a manual run against a real `DISCOVERY_LIVE=1` deployment —
  tracked as the still-open half of this story, not claimed done here.

## Source inventory

| Source key | Adapter class | Library / protocol | Zero-LLM-token? |
|---|---|---|---|
| `sample` | `SampleSource` | none — hardcoded `example.test` rows, offline dev/demo fixture | yes |
| `jobspy:linkedin` | `JobSpySource` | `python-jobspy` (`LiveJobSpyClient`) | yes |
| `jobspy:indeed` | `JobSpySource` | `python-jobspy` | yes |
| `jobspy:glassdoor` | `JobSpySource` | `python-jobspy` | yes |
| `jobspy:google` | `JobSpySource` | `python-jobspy` (Google's jobs aggregator) | yes |
| `jobspy:zip_recruiter` | `JobSpySource` | `python-jobspy` | yes |
| `searxng` | `SearxngSource` | operator's own SearXNG instance, `?format=json` | yes |
| `rss:hn-hiring` | `RssSource` | hardcoded feed, `https://hnrss.org/jobs` | yes |
| `rss:custom-N` | `RssSource` | operator-configured feed URL(s), `DISCOVERY_RSS_FEEDS` | yes |

All of the above are registered by `adapters/discovery/factory.py::build_default_discovery`
and share ONE aggregator (`JobSpySearxngDiscovery`) and ONE per-source outcome pipeline
(below). A new source is a new `Source`-protocol class registered by key — no core
change (`NFR-EXT-1`); this table is the place to add a row when one lands.

Not a discovery source but sharing the same network-boundary pattern: `url_intake.py`'s
`LiveUrlPostingFetcher`/`FakeUrlPostingFetcher` is the single-URL "save a job from any
page" fetcher (P1-9). It is a one-shot fetch keyed by an owner-supplied URL rather than a
search, so it has no region/category or rate-limit concept of its own — but it shares the
15s bounded-timeout convention, the SSRF guard (`_assert_public_http_url`), and the
honesty rule that an unfetched field is left absent rather than guessed.

## Per-source reliability detail

### `jobspy:*` (LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter)

- **What it is:** all five sites go through ONE client seam
  (`JobSpyClient.scrape`), backed by the real `python-jobspy` library in
  `LiveJobSpyClient` (live-only, never imported in the default lane) or
  `FakeJobSpyClient` (canned per-site rows, default + CI lane). Each site is its own
  registered `Source` (`jobspy:<site>`), independently toggleable.
- **Regions/categories** *(vendor knowledge, not live-verified here)*: LinkedIn and
  Google's jobs aggregator have broad multi-region reach; Indeed and Glassdoor have
  strong coverage in the US/UK/CA/AU/DE and other markets Indeed operates a local
  domain in, but coverage thins outside those; ZipRecruiter is US/Canada-focused and a
  non-US/CA query commonly returns few or zero results. Job **category** is not a
  board-level restriction — any of the five will return whatever the search term
  matches — but a niche/rare title naturally yields fewer rows on a smaller board.
  These are the assumptions the region/category test scenarios below encode; a
  live-deploy drill is the only way to confirm them against the real sites, which
  change scraping-friendliness over time.
- **Failure modes:** `python-jobspy` raising for any reason (network error, layout
  change breaking its scraper, a captcha/bot-block response, a malformed/empty
  DataFrame) is caught in `JobSpySource.fetch`'s `except Exception` — the source
  returns `[]` and records `last_error`, never propagating and never crashing the run
  (`test_failing_client_does_not_crash_run`, `test_a_failed_board_never_crashes_or_hides_other_boards_same_run`).
- **Rate limits:** `PerBoardRateLimiter` (`jobspy_searxng.py`) gives every registered
  source key its own token bucket — 5 calls per 60s by default — so one board being
  queried repeatedly (multiple campaigns, retries) never starves the others; exceeding
  it skips the source for the remainder of the window (`SOURCE_RATE_LIMITED`), not a
  crash. Separately, `DiscoveryService._apply_pacing`/`SourcePacer` enforces a 2-second
  minimum gap between successive **postings on the same board domain** as they're
  processed downstream (anti-bot smoothing for the pipeline that follows discovery,
  distinct from the fetch-rate bucket above). A proxy hook (`ProxyConfig`, FR-DISC-6)
  exists for hostile boards but ships with no proxy committed — off by default.
- **Degradation behavior:** an errored/empty/rate-limited board never silently
  disappears from the aggregate — see "How outcomes surface" below.

### `searxng` (metasearch)

- **What it is:** hits the operator's own SearXNG instance (`{base_url}/search?format=json`).
  Reach depends entirely on which upstream engines the operator's SearXNG config
  enables — SearXNG itself is not a job board, it's a metasearch layer over whatever
  general engines are configured, so its regional/category reach is operator-defined,
  not a fixed board property.
- **Failure modes:** the client (`LiveSearxngClient`) detects the single most common
  misconfiguration explicitly — SearXNG disables `?format=json` by default and answers
  with an HTML 403 — and logs an actionable remediation hint (enable
  `search.formats: [html, json]` + `secret_key`) instead of crashing or returning a
  cryptic JSON-decode error; a non-JSON 200 or a JSON-decode failure is handled the
  same way. All three return `[]` (verified hermetically in
  `tests/unit/test_discovery_clients_robustness.py`).
- **Rate limits:** same `PerBoardRateLimiter` bucket as every other source key
  (`searxng`).
- **Degradation behavior:** a misconfigured/unreachable SearXNG instance reads as
  `SOURCE_EMPTY` or `SOURCE_ERROR` exactly like a jobspy board — never a silent zero
  that looks like "no jobs today."

### `rss:*` (HN "Who is hiring" + operator-added feeds)

- **What it is:** a generic RSS/Atom fetch + parse (`LiveRssClient`, stdlib
  `xml.etree`/`defusedxml`), proving the `Source` abstraction is extensible beyond
  "board scraper" (a third distinct SHAPE, NFR-EXT-1). The hardcoded
  `rss:hn-hiring` feed (`https://hnrss.org/jobs`) is engineering/tech-hiring and
  skews toward US/remote tech-company postings by the nature of that community;
  operator-added feeds (`rss:custom-N`, `DISCOVERY_RSS_FEEDS`) can be anything —
  a company careers feed, a regional board's feed — so their region/category
  coverage is whatever the operator points them at.
- **Failure modes:** an HTTP error (`raise_for_status`) or a malformed feed is caught
  in `RssSource.fetch`'s `except Exception`, same pattern as the jobspy sources.
  The XML parser is explicitly guarded against entity-expansion DoS (billion-laughs):
  `defusedxml` when installed, else a DTD/entity-declaration reject before falling
  back to the stdlib parser (`clients.py::_parse_feed_xml`).
- **Rate limits:** same per-source-key bucket; a custom feed queried too often is
  skipped for the window like any other source.
- **Degradation behavior:** identical outcome pipeline — empty/error/rate-limited,
  never silently absent.

### `sample`

- **What it is:** the always-on offline fixture (`example.test` URLs, clearly
  synthetic) so the default lane and a fresh/no-config deployment always have a
  yielding source; harmless in a live deployment (toggleable off) and the front-door
  marks every non-live source "Sample data" so it can never be mistaken for a real
  listing (`_liveBadge`, dark-engine audit item 65).
- **Failure modes / rate limits:** none — pure in-process data, cannot fail or be
  rate-limited.

## How outcomes surface (H2 pipeline this story builds on)

One pipeline, shared by every source above:

1. `JobSpySearxngDiscovery.search` records one outcome per queried source —
   `{"source_key", "status", "found", "error"}`, status one of `ok` / `empty` /
   `error` / `rate_limited` (`core/rules/underdelivery.py`) — on `last_source_outcomes`,
   reset every call so a stale prior run can never masquerade as the current one.
2. `DiscoveryService._persist_source_outcomes` writes each outcome to
   `discovery_sources.yield_stats.last_run` (`{at, status, found, error}`) right after
   every `run_discovery` call, best-effort (a persistence failure is logged loudly,
   never silently dropped, and never breaks the run itself).
3. Front-door reach:
   - **Digest** (in-app + email): `source_shortfalls` — one plain-language sentence
     per underdelivering enabled source, on **every** digest, not just empty days
     (`applicantDigest.js` strip; message text from `core/rules/underdelivery.py::source_shortfall_message`).
   - **Settings → Job searches** (ties to P1-3's health-panel pattern): each source's
     row shows its lifetime yield summary AND, when the last run underdelivered, a
     highlighted note — "found nothing on the last check" / "couldn't be searched on
     the last check" / "skipped on the last check to avoid over-asking"
     (`applicantCampaignSettings.js::_lastRunNote`, reading exactly the `last_run`
     shape `_persist_source_outcomes` writes). `ok` (or no record yet) renders nothing
     — no fabricated "all good" claim.
4. A source's failure is never fatal to the run: a raised exception on one board
   never blocks another board's results in the same call
   (`test_a_failed_board_never_crashes_or_hides_other_boards_same_run`).

This is the "per-source health surfaced in UI" half of the P2-13 DoD — it was already
built as part of H2; this story's tests
(`tests/unit/test_p2_13_source_reliability.py`) confirm it holds across the
region/category matrix below, not just the single-scenario case H2's own test suite
(`tests/unit/test_h2_no_silent_underdelivery.py`) covers.

## Discovery quality across regions/categories (this story's test matrix)

`tests/unit/test_p2_13_source_reliability.py` runs the SAME code path
(`DiscoveryService.run_discovery` → `JobSpySearxngDiscovery.search`) across three
region/category scenarios, each with a deliberately mixed per-source outcome (one
board `ok`, one genuinely `empty`, one simulated `error`) so a single run proves the
pipeline never lets one source's outcome bleed into another's:

| Scenario | Region | Category | Sources exercised | Mixed outcome asserted |
|---|---|---|---|---|
| US-remote engineering | Remote, US | Software Engineer | Indeed (ok), LinkedIn (ok), ZipRecruiter (empty), Glassdoor (simulated block → error) | yes |
| UK sales | London, UK | Account Executive | Indeed (ok), LinkedIn (empty), ZipRecruiter (simulated out-of-region error) | yes |
| Germany data/engineering | Berlin, Germany | Data Scientist | Indeed (ok), LinkedIn (ok), ZipRecruiter (empty), Glassdoor (empty) | — |

For every scenario the tests assert: normalization carries the region/category through
untouched (location/title on every kept posting); the criteria filter keeps only
matching titles; every queried source's outcome is exactly what the scenario intended
(`ok`/`empty`/`error`); the shortfall vocabulary names exactly the underdelivering
sources with a non-empty plain-language message; and the outcome round-trips through
`DiscoveryService` persistence into the same `yield_stats.last_run` shape the Settings
UI reads. **What this proves:** the aggregation/normalization/outcome-reporting logic
is region- and category-agnostic and behaves correctly under a realistic mixed-failure
run. **What this does NOT prove:** that the real LinkedIn/Indeed/Glassdoor/Google/
ZipRecruiter/SearXNG/RSS endpoints actually return good results for these regions
today — that is a live property of external, frequently-changing services and is
explicitly out of scope for a hermetic PR-gated suite (see the verification-level note
at the top of this doc, and `tests/integration/test_discovery_live.py`).

## Known limitations / follow-ups

- Real per-region board coverage is unverified from this container by design (no
  outbound calls). The live-deploy drill (`DISCOVERY_LIVE_TEST=1` against
  `tests/integration/test_discovery_live.py`, plus a manual `DISCOVERY_LIVE=1` run) is
  the remaining half of this story and is **not** claimed done here — see
  `docs/delivery-status.md`'s Phase-2 remaining list.
- `python-jobspy`'s scraping approach is inherently fragile to upstream site changes;
  a board silently changing its HTML/response shape could start returning malformed
  rows that `normalize_row` drops (missing title/URL) rather than erroring loudly. The
  `found: 0` / `SOURCE_EMPTY` outcome is the only signal for that case today — it reads
  identically to "no matching jobs," which is an honest but coarse distinction. A
  finer-grained "board looks broken" signal (e.g. a sudden shape change across many
  consecutive runs) is a plausible follow-up, not built here.
- SearXNG's real regional/category reach is entirely a function of the operator's own
  engine configuration and is not something this codebase can characterize in the
  abstract.
