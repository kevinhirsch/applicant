# Extending Applicant (NFR-EXT-1)

Applicant is hexagonal: every external concern is a **port** with swappable
**adapters**. NFR-EXT-1 mandates that the engine is extensible "across sources, ATS
adapters, tools, models, channels, UI surfaces, and to multi-campaign" — *without
core or port changes*. This guide shows the two most common extension points with
working examples that already ship.

The contract for every extension point below: **a new adapter is a new
class + a registry entry. No edit to the core domain, the ports, or the pre-fill /
discovery services is required.** That is the NFR-EXT-1 guarantee.

---

## 0. Working principles (binding)

These apply to **every** change, by humans and AI agents alike (the agent-facing copy
lives in the repo-root `CLAUDE.md`):

1. **Lift and shift first — never rebuild what already exists.** If logic or UI for
   something already exists anywhere in the tree, **copy that component into the new
   location first**, get it working there unchanged, and only **then adapt it by
   extension and removal** to meet the spec for the new context. Do not write a fresh
   from-scratch implementation when a working one exists. (E.g. the out-of-box "Connect
   a model" step reuses the existing Local/Remote endpoint manager in
   `workspace/static/js/admin.js` over the workspace's own `/api/model-endpoints`, not a
   new form.)
2. **Reachability is the definition of done.** A requirement is finished only when it is
   reachable/operable in the white-labeled front-door (`workspace/`), not merely when the
   engine implements it and tests pass. Verify the chain spec → engine → workspace proxy
   → JS → nav/section; the traceability matrix checks the engine only.
3. **White-label everything.** No vendor/persona codename and no `FR-`/`NFR-` jargon in
   user-facing strings; the product is **Applicant**.
4. **Front-door proxies; the engine owns the logic.** Workspace `/api/applicant/*` routes
   are thin, auth-protected, owner-scoped proxies over the engine client.

---

## 1. Add a new ATS adapter

The ATS abstraction lives in `src/applicant/adapters/browser/ats.py`. An ATS is
modeled as an ordered list of `FakePage`s, each exposing detectable fields and
flagging the irreducible-human-step pages (account-create, final-submit). The
maximal-pre-fill loop walks `pages()` and is therefore ATS-agnostic.

### Steps

1. **Subclass `AtsAdapter`** and set a unique `name`:

   ```python
   class LeverAts(AtsAdapter):
       name = "lever"

       def matches(self, url: str) -> bool:
           return "lever.co" in url.lower()

       def tenant_key(self, url: str) -> str:
           # per-tenant stealth profile key (FR-STEALTH-3)
           rest = url.split("lever.co/", 1)[-1]
           return f"lever:{rest.split('/', 1)[0]}"

       def pages(self, url: str) -> list[FakePage]:
           return [
               FakePage(url=f"{url}/apply", fields=(
                   DetectedField("input[name=name]", "Full name", "text"),
                   DetectedField("input[name=email]", "Email", "text"),
                   # factual screening (filled from attributes) vs essay (Phase 3 gen):
                   DetectedField("input[name=cards[work-auth]]",
                                 "Are you authorized to work?",
                                 SCREENING_FACTUAL, options=("Yes", "No")),
                   # EEO/sensitive fields are auto-detected by the sensitive-field rule:
                   DetectedField("select[name=eeo[gender]]", "Gender", "select",
                                 options=("Male", "Female", "Decline to self-identify")),
               )),
               FakePage(url=f"{url}/apply/review", is_final_submit=True, fields=()),
           ]
   ```

2. **Register it** in `ATS_REGISTRY`:

   ```python
   ATS_REGISTRY: dict[str, type[AtsAdapter]] = {
       WorkdayAts.name: WorkdayAts,
       GreenhouseAts.name: GreenhouseAts,
       LeverAts.name: LeverAts,   # <- the only wiring change
   }
   ```

That's it. `resolve_ats(url)` now returns your adapter for matching URLs, and the
pre-fill service walks its pages with no changes. Field-mapping *knowledge* (which
selector a label binds to) is learnable and **shared across campaigns** via
`field_mappings` with `campaign_id=None`, while the attribute *values* stay
per-campaign (FR-ATTR-2).

Field-type tags the pre-fill service routes on:
- `SCREENING_FACTUAL` — filled from stored attributes (FR-ANSWER-1).
- `SCREENING_ESSAY` — deferred to Phase 3 generation + redline review.
- sensitive (EEO) fields are detected by `core.rules.sensitive_fields` and filled
  only from explicit stored answers (FR-ATTR-6) — you do not special-case them.

See `LeverAts` (shipped) and its tests in `tests/unit/test_ats.py`.

---

## 2. Add a new discovery source

Discovery sources live in `src/applicant/adapters/discovery/`. A source implements
the `Source` protocol (`key: str` + `fetch(campaign_id, criteria) -> list[JobPosting]`).
The master aggregator (`JobSpySearxngDiscovery`) registers sources by key and
toggles them per campaign (FR-DISC-2). All network access sits behind a **client
seam** so the default lane runs offline with a fake client.

### Steps

1. **Define the network boundary client** (a `Protocol` + a Live + a Fake impl) in
   `clients.py`:

   ```python
   class RssClient(Protocol):
       def fetch_items(self, *, feed_url: str, proxies: list[str] | None) -> list[dict]: ...

   class LiveRssClient:   # real network (integration-only)
       def fetch_items(self, *, feed_url, proxies): ...   # httpx + xml.etree

   class FakeRssClient:   # offline, default lane
       def fetch_items(self, *, feed_url, proxies): return [...canned rows...]
   ```

2. **Implement the `Source`** in `jobspy_searxng.py`, normalizing rows to
   `JobPosting` via the shared `normalize_row` (zero LLM tokens, FR-DISC-4):

   ```python
   class RssSource:
       def __init__(self, *, client, feed_url, proxy=None, key="rss"):
           self.key = key; self._client = client; self._feed_url = feed_url
           self._proxy = proxy or ProxyConfig()

       def fetch(self, campaign_id, criteria):
           rows = self._client.fetch_items(feed_url=self._feed_url,
                                           proxies=self._proxy.as_list())
           return [p for raw in rows
                   if (p := normalize_row(raw, campaign_id, self.key))
                   and _matches(criteria, p.title, p.work_mode)]
   ```

3. **Wire it into the factory** (`factory.py`) — pick Live vs Fake by the `live`
   flag so the default/test lane stays hermetic:

   ```python
   RSS_FEEDS = {"rss:hn-hiring": "https://hnrss.org/jobs"}
   ...
   rss_client = LiveRssClient() if live else FakeRssClient()
   for key, feed_url in RSS_FEEDS.items():
       sources.append(RssSource(client=rss_client, feed_url=feed_url, key=key))
   ```

The new source appears in `available_sources()`, is seeded into `discovery_sources`
on `sync_registry`, is **user-toggleable** per campaign, and feeds source-yield
learning (FR-DISC-5) automatically. The proxy hook (FR-DISC-6) threads through the
client without committing to a proxy.

See `RssSource` (shipped) and its tests in `tests/unit/test_discovery_service.py`.

---

## 3. Multi-campaign

Everything is campaign-scoped (FR-CRIT-4): criteria, attribute-cloud values,
learning state, discovery toggles, digests, and pending actions are keyed by
`campaign_id`. **Learnable cross-campaign knowledge** — specifically ATS
field-mapping knowledge — is stored globally (`FieldMapping.campaign_id is None`)
and reused everywhere, while the values it resolves stay per-campaign (FR-ATTR-2).

To run another campaign you create another `Campaign` row; no rework is needed. See
`tests/integration/test_multi_campaign.py` and the
`p4_multi_campaign.feature` BDD scenarios, which run two campaigns concurrently and
assert value isolation + mapping sharing + independent learning.

---

## Other extension points (same pattern)

| Concern        | Port / registry                                   | Example adapters |
|----------------|---------------------------------------------------|------------------|
| LLM models     | `ports/driven/llm.py` + tier ladder               | OpenAI-compatible, Ollama |
| Notifications  | `ports/driven/notification.py`                    | Apprise (Discord/email) |
| Remote view    | `ports/driven/sandbox.py` (swappable sub-port)    | Neko/WebRTC |
| Tools          | `adapters/tools/tool_registry.py` (`ToolRegistry`)| Discovery, Scoring, Pre-fill, ... |
| Storage        | `ports/driven/storage.py`                         | SQLAlchemy, in-memory |

All follow the same rule: subclass/implement the port, register it, no core change.
