"""Step bindings for the T05 learning / scoring / conversion / discovery specs.

Theme: issues #174, #175, #186, #195, #196, #237, #238, #239, #240.

These follow the canonical enhancement-Gherkin pattern (see
``test_enh_research_steps.py``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour that
  already ships on this branch — they assert against the actual config defaults / core
  rules / application services through in-memory adapters, and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed-but-not-built (an open feedback loop, a swallowed-exception with no log, a
  cache key that ignores learning, a missing per-board pacing seam, a missing
  production preset). Their steps make an honest probe at the real target so the
  scenario is a genuine red — never ``assert True``. ``conftest.pytest_bdd_apply_tag``
  maps ``@pending`` to a non-strict xfail.

Hexagonal: assertions target ``app.config.Settings``, ``core`` rules/entities, and
``application.services`` through ``InMemoryStorage`` + ``LocalEmbedding`` — never UI
internals, never a real socket. Speculative imports for not-yet-built targets live
INSIDE the step body so absence -> runtime error -> xfail, never a collection error.
"""

from __future__ import annotations

import logging

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.config import Settings
from applicant.application.services.learning_service import LearningService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.outcome_event import OutcomeSource
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState

scenarios(
    "../features/enhancements/enh_174_hermetic_lane_defaults.feature",
    "../features/enhancements/enh_175_automated_accounts_default.feature",
    "../features/enhancements/enh_186_llm_rate_limit_default.feature",
    "../features/enhancements/enh_195_per_board_rate_limiting.feature",
    "../features/enhancements/enh_196_cross_run_dedup.feature",
    "../features/enhancements/enh_237_feature_stats_unread.feature",
    "../features/enhancements/enh_238_record_converting_role_dead.feature",
    "../features/enhancements/enh_239_digest_cache_ignores_learning.feature",
    "../features/enhancements/enh_240_conversion_loop_swallows.feature",
)

# A configured-but-unreachable DSN keeps Settings() construction hermetic (no socket).
UNREACHABLE_DSN = "postgresql+psycopg://x:x@127.0.0.1:1/none"


@pytest.fixture
def t05ctx() -> dict:
    return {}


def _settings(**overrides) -> Settings:
    overrides.setdefault("DATABASE_URL", UNREACHABLE_DSN)
    return Settings(**overrides)


def _wire_learning():
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    learning = LearningService(storage, embedding)
    return storage, embedding, learning


def _seed_campaign(storage) -> CampaignId:
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    return cid


# ===========================================================================
# #174 — hermetic-lane defaults (GREEN) + production preset (PENDING)
# ===========================================================================
@given("default engine settings")
def default_settings(t05ctx):
    t05ctx["settings"] = _settings()


@then("the live browser, live discovery and live notifications are all off by default")
def integrations_off(t05ctx):
    s = t05ctx["settings"]
    assert s.browser_real is False
    assert s.discovery_live is False
    assert s.notifications_live is False


@then("the orchestrator runs the in-process shim and the scheduler is idle")
def shim_and_idle(t05ctx):
    s = t05ctx["settings"]
    assert s.orchestrator_backend == "shim"
    assert s.scheduler_enabled is False


@given("an operator wants the engine to do real work")
def operator_wants_real(t05ctx):
    t05ctx["mode"] = "production"


@when("a combined production-mode preset is requested")
def request_production_preset(t05ctx):
    # Honest probe: a single combined preset that flips every real integration on does
    # not exist yet. Construct settings asking for it; today nothing reads it, so the
    # individual flags stay at their hermetic defaults (the genuine red below).
    t05ctx["preset"] = _settings(APPLICANT_MODE="production")


@then(
    "one setting enables the live browser, live discovery, live notifications, "
    "durable orchestration and the scheduler together"
)
def preset_flips_everything(t05ctx):
    s = t05ctx["preset"]
    # A real production preset would derive all five from APPLICANT_MODE. Until it
    # lands, the defaults remain hermetic — a true failure for @pending.
    assert getattr(s, "applicant_mode", "") == "production"
    assert s.browser_real is True
    assert s.discovery_live is True
    assert s.notifications_live is True
    assert s.orchestrator_backend != "shim"
    assert s.scheduler_enabled is True


# ===========================================================================
# #175 — ALLOW_AUTOMATED_ACCOUNTS default (GREEN) + per-tenant allowance (PENDING)
# ===========================================================================
@then("automated account creation is off by default")
def automated_accounts_off(t05ctx):
    assert t05ctx["settings"].allow_automated_accounts is False


@given("the global automated-account opt-in is off")
def global_optin_off(t05ctx):
    t05ctx["allow_global"] = False


@given("a stored credential already exists for an ATS tenant")
def stored_credential_exists(t05ctx):
    t05ctx["tenant_has_credential"] = True


@when("the engine reaches that tenant's account-create gate")
def reach_account_gate(t05ctx):
    # Honest probe: build the prefill service with the global opt-in OFF and ask whether
    # a per-tenant stored-credential allowance would let account creation proceed. The
    # decision today keys ONLY on the global flag (``_allow_automated_accounts``); there
    # is no per-tenant override, so the allowance hook is absent.
    from applicant.application.services.prefill_service import PrefillService

    t05ctx["prefill_cls"] = PrefillService


@then(
    "a per-tenant stored-credential allowance lets it proceed without a manual hand-off"
)
def per_tenant_allowance(t05ctx):
    cls = t05ctx["prefill_cls"]
    # A per-tenant allowance seam (e.g. an instance method or ctor flag distinct from
    # the global opt-in) does not exist yet — genuine red until it lands.
    assert hasattr(cls, "allow_account_creation_for_tenant")


# ===========================================================================
# #186 — LLM rate limit wiring (GREEN) + conservative default (PENDING)
# ===========================================================================
class _RecordingOrchestrator:
    """Minimal orchestrator port double recording created queues (no IO)."""

    def __init__(self) -> None:
        self.queues: dict[str, dict] = {}

    def create_queue(self, name: str, **kwargs) -> None:
        self.queues[name] = kwargs


@given("a positive LLM rate limit is configured")
def positive_llm_limit(t05ctx):
    t05ctx["settings"] = _settings(LLM_RATE_LIMIT="30", LLM_RATE_PERIOD="60.0")


@when("the capacity service is built")
def build_capacity(t05ctx):
    from applicant.application.services.capacity_service import (
        LLM_QUEUE,
        CapacityService,
    )

    s = t05ctx["settings"]
    orch = _RecordingOrchestrator()
    CapacityService(
        orch,
        sandbox_concurrency=s.sandbox_concurrency,
        llm_limit=s.llm_rate_limit or None,
        llm_period=s.llm_rate_period or None,
    )
    t05ctx["orch"] = orch
    t05ctx["llm_queue_name"] = LLM_QUEUE


@then("a per-provider LLM limiter queue is created with that limit")
def llm_queue_created(t05ctx):
    orch = t05ctx["orch"]
    name = t05ctx["llm_queue_name"]
    assert name in orch.queues
    assert orch.queues[name].get("limiter_limit") == 30


@then(
    "the LLM rate limit defaults to a conservative positive value rather than disabled"
)
def llm_default_conservative(t05ctx):
    # Today LLM_RATE_LIMIT defaults to 0 (disabled). A conservative non-zero default
    # (e.g. 30 req/min) is the residual gap — genuine red for @pending.
    assert t05ctx["settings"].llm_rate_limit > 0


# ===========================================================================
# #195 — campaign throughput cap (GREEN) + per-board pacing (PENDING)
# ===========================================================================
@given("a campaign throughput far above the allowed ceiling")
def throughput_above_ceiling(t05ctx):
    from applicant.core.entities.campaign import THROUGHPUT_HARD_CAP

    t05ctx["requested_throughput"] = THROUGHPUT_HARD_CAP + 500
    t05ctx["hard_cap"] = THROUGHPUT_HARD_CAP


@when("the throughput is clamped")
def clamp_throughput_step(t05ctx):
    from applicant.core.entities.campaign import clamp_throughput

    t05ctx["applied_throughput"] = clamp_throughput(t05ctx["requested_throughput"])


@then("the applied value never exceeds the campaign hard cap")
def applied_within_cap(t05ctx):
    assert t05ctx["applied_throughput"] <= t05ctx["hard_cap"]


@given("several postings discovered from the same job-board domain in one run")
def postings_same_domain(t05ctx):
    t05ctx["domain"] = "linkedin.com"


@when("the engine schedules requests against that domain")
def schedule_against_domain(t05ctx):
    # Honest probe: a per-source / per-domain pacing policy does not exist. Look for a
    # rules module that would hold the per-board interval logic.
    import importlib

    t05ctx["pacing_mod_name"] = "applicant.core.rules.source_pacing"
    try:
        t05ctx["pacing_mod"] = importlib.import_module(t05ctx["pacing_mod_name"])
    except ImportError:
        t05ctx["pacing_mod"] = None


@then(
    "a per-source pacing policy holds them under a configurable per-domain interval"
)
def per_source_pacing(t05ctx):
    mod = t05ctx["pacing_mod"]
    # No per-domain pacing seam ships yet — genuine red until it lands.
    assert mod is not None
    assert hasattr(mod, "next_allowed_at") or hasattr(mod, "SourcePacer")


# ===========================================================================
# #196 — within-run dedup (GREEN) + cross-run dedup (PENDING)
# ===========================================================================
def _wire_discovery(postings_per_run):
    from applicant.application.services.discovery_service import DiscoveryService

    storage = InMemoryStorage()
    embedding = LocalEmbedding()

    class _Discovery:
        def __init__(self, runs):
            self._runs = list(runs)
            self._i = 0

        def available_sources(self):
            return ["jobspy:indeed"]

        def is_source_enabled(self, key):
            return True

        def apply_toggles(self, toggles):
            return None

        def set_source_enabled(self, key, enabled):
            return None

        def search(self, campaign_id, criteria, sources=None):
            batch = self._runs[self._i] if self._i < len(self._runs) else []
            self._i += 1
            return list(batch)

    discovery = _Discovery(postings_per_run)
    svc = DiscoveryService(storage, discovery, embedding)
    return storage, svc


def _posting(cid, title, company, url):
    return JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title=title,
        company=company,
        source_url=url,
        work_mode="remote",
        description="python backend",
        source_key="jobspy:indeed",
    )


@given("a discovery run that returns two near-identical postings")
def two_near_identical(t05ctx):
    cid = CampaignId(new_id())
    run1 = [
        _posting(cid, "Senior Python Engineer", "Acme", "https://acme.test/a"),
        _posting(cid, "Senior Python Engineer", "Acme", "https://acme.test/b"),
    ]
    storage, svc = _wire_discovery([run1])
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    t05ctx.update(storage=storage, discovery=svc, campaign_id=cid)


@when("the run deduplicates its results")
def run_dedup(t05ctx):
    t05ctx["kept"] = t05ctx["discovery"].run_discovery(t05ctx["campaign_id"])


@then("only one of the near-identical postings survives")
def one_survives(t05ctx):
    assert len(t05ctx["kept"]) == 1


@given("a posting was kept in an earlier discovery run")
def earlier_run_kept(t05ctx):
    cid = CampaignId(new_id())
    run1 = [_posting(cid, "Senior Python Engineer", "Acme", "https://acme.test/a")]
    run2 = [_posting(cid, "Senior Python Engineer", "Acme", "https://acme.test/different")]
    storage, svc = _wire_discovery([run1, run2])
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()
    t05ctx.update(storage=storage, discovery=svc, campaign_id=cid)
    t05ctx["kept_run1"] = svc.run_discovery(cid)


@when("a later run surfaces the same role with a different URL")
def later_run_same_role(t05ctx):
    t05ctx["kept_run2"] = t05ctx["discovery"].run_discovery(t05ctx["campaign_id"])


@then("a persisted rolling embedding window suppresses the cross-run duplicate")
def cross_run_suppressed(t05ctx):
    # _dedup only compares within the CURRENT run, so the second run keeps the same role
    # again (different URL evades the aggregator's source_url dedup). A persisted
    # rolling embedding window would suppress it — genuine red for @pending.
    assert t05ctx["kept_run2"] == []


# ===========================================================================
# #237 — feature_stats fold + round-trip (GREEN) + biasing (PENDING)
# ===========================================================================
@given("a fresh learning model for a campaign")
def fresh_model(t05ctx):
    storage, embedding, learning = _wire_learning()
    cid = _seed_campaign(storage)
    t05ctx.update(
        storage=storage, embedding=embedding, learning=learning, campaign_id=cid
    )
    t05ctx["model"] = learning.model_for(cid)


@when("a senior role is approved and a junior role is declined")
def approve_and_decline(t05ctx):
    learning = t05ctx["learning"]
    model = learning.record_decision(
        t05ctx["model"], approved=True, features={"seniority": "senior"}
    )
    model = learning.record_decision(
        model, approved=False, features={"seniority": "junior"}
    )
    t05ctx["model"] = model


@then("the per-feature stats record one approve bucket and one decline bucket")
def stats_have_both_buckets(t05ctx):
    stats = t05ctx["model"].feature_stats
    slot = stats.get("seniority", {})
    assert slot.get("senior:approve") == 1
    assert slot.get("junior:decline") == 1


@given("a learning model with recorded per-feature stats")
def model_with_stats(t05ctx):
    storage, embedding, learning = _wire_learning()
    cid = _seed_campaign(storage)
    model = learning.record_decision(
        learning.model_for(cid), approved=True, features={"skill": "python"}
    )
    t05ctx.update(
        storage=storage, embedding=embedding, learning=learning, campaign_id=cid,
        model=model,
    )


@when("the model is persisted and reloaded")
def persist_reload(t05ctx):
    t05ctx["learning"].persist_model(t05ctx["model"])
    t05ctx["reloaded"] = t05ctx["learning"].load_model(t05ctx["campaign_id"])


@then("the per-feature stats are restored from storage")
def stats_restored(t05ctx):
    stats = t05ctx["reloaded"].feature_stats
    assert "skill" in stats
    assert stats["skill"].get("python:approve") == 1


@given("a campaign that has approved a feature and declined another")
def campaign_with_taste(t05ctx):
    storage, embedding, learning = _wire_learning()
    cid = _seed_campaign(storage)
    model = learning.model_for(cid)
    # Decline "frontend" hard so a frontend posting SHOULD be down-weighted if the
    # taste signal were ever consumed by scoring.
    for _ in range(10):
        model = learning.record_decision(
            model, approved=False, features={"keyword": "frontend"}
        )
    learning.persist_model(model)
    t05ctx.update(
        storage=storage, embedding=embedding, learning=learning, campaign_id=cid
    )


@when("a posting matching the declined feature is scored")
def score_declined_posting(t05ctx):
    cid = t05ctx["campaign_id"]
    storage = t05ctx["storage"]
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Frontend Engineer",
        company="Acme",
        source_url="https://acme.test/fe",
        work_mode="remote",
        description="frontend react",
        source_key="jobspy:indeed",
    )
    storage.postings.add(posting)
    storage.commit()
    criteria = SearchCriteria(campaign_id=cid, keywords=("frontend",))
    # Scoring WITH the learning service wired (it only reads converting_alignment,
    # never feature_stats).
    scoring = ScoringService(
        storage, llm=None, embedding=t05ctx["embedding"], learning=t05ctx["learning"]
    )
    biased = scoring.score_posting(posting, criteria)
    # Baseline scorer with NO learning wired at all.
    baseline = ScoringService(
        storage, llm=None, embedding=t05ctx["embedding"]
    ).score_posting(posting, criteria)
    t05ctx["biased_score"] = biased.score
    t05ctx["baseline_score"] = baseline.score
    t05ctx["biased_rationale"] = biased.rationale


@then(
    "the recorded feature stats lower its viability score relative to the unbiased baseline"
)
def stats_lower_score(t05ctx):
    # #237: feature_stats is now READ by scoring via LearningService.taste_bias, so the
    # repeatedly-declined "frontend" signal nudges a frontend posting's score down
    # below the no-learning baseline, and the bias is disclosed in the rationale.
    assert t05ctx["biased_score"] < t05ctx["baseline_score"]
    assert "taste" in t05ctx["biased_rationale"].lower()


# ===========================================================================
# #238 — record_converting_role works directly (GREEN) + live loop (PENDING)
# ===========================================================================
@when("a converted role description is folded into the centroid")
def fold_converted_role(t05ctx):
    learning = t05ctx["learning"]
    jd = "Senior Python Engineer building distributed backend systems in Python"
    t05ctx["model"] = learning.record_converting_role(
        t05ctx["model"], jd, title="Senior Python Engineer"
    )
    t05ctx["fold_jd"] = jd


@then("the converting-role signature carries a non-empty centroid vector")
def centroid_vector_present(t05ctx):
    sig = t05ctx["model"].converting_role_signature
    assert sig.get("vector")
    assert t05ctx["model"].converting_samples == 1


@then("the alignment of a similar role is greater than zero")
def alignment_positive(t05ctx):
    align = t05ctx["learning"].converting_alignment(t05ctx["model"], t05ctx["fold_jd"])
    assert align > 0.0


@given("a campaign whose application converts through the submission loop")
def campaign_converts(t05ctx):
    from applicant.application.services.learning_advanced import (
        AdvancedLearningService,
    )
    from applicant.application.services.submission_service import SubmissionService

    storage, embedding, learning = _wire_learning()
    cid = _seed_campaign(storage)
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Senior Python Engineer",
        company="Acme",
        source_url="https://acme.test/job",
        work_mode="remote",
        description="python backend distributed systems",
        source_key="jobspy:indeed",
    )
    storage.postings.add(posting)
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=posting.id,
            status=ApplicationState.AWAITING_FINAL_APPROVAL,
            job_title="Senior Python Engineer",
        )
    )
    storage.commit()
    advanced = AdvancedLearningService(learning, storage=storage)
    submission = SubmissionService(
        storage, browser=None, learning=learning, advanced_learning=advanced
    )
    t05ctx.update(
        storage=storage,
        embedding=embedding,
        learning=learning,
        campaign_id=cid,
        application_id=aid,
        submission=submission,
    )


@when("the conversion loop closes")
def close_conversion_loop(t05ctx):
    app = t05ctx["storage"].applications.get(t05ctx["application_id"])
    t05ctx["submission"].record_submission(app, source=OutcomeSource.AUTO)


@then("the Phase-1 converting-role centroid vector is populated by that conversion")
def centroid_populated_by_loop(t05ctx):
    learning = t05ctx["learning"]
    model = learning.load_model(t05ctx["campaign_id"])
    # #238: the live conversion loop now folds BOTH facets — the discrete role-feature
    # signature AND the Phase-1 embedding centroid ``vector`` — off one conversion, so
    # the centroid is populated (and counted once) and Phase-1 converting_alignment is
    # non-zero after a real conversion through the submission loop.
    vector = model.converting_role_signature.get("vector")
    assert vector
    assert model.converting_samples == 1
    # The discrete signature is still folded (single source of truth for samples).
    assert any(k.startswith("role:") for k in model.converting_role_signature)
    # And the now-populated centroid makes the Phase-1 alignment reader non-zero.
    posting = t05ctx["storage"].postings.list_for_campaign(t05ctx["campaign_id"])[0]
    jd = f"{posting.title} {posting.description}"
    assert learning.converting_alignment(model, jd) > 0.0


# ===========================================================================
# #239 — criteria-keyed reuse (GREEN) + learning-aware cache key (PENDING)
# ===========================================================================
class _CountingEmbedding(LocalEmbedding):
    """LocalEmbedding that counts similarity() calls so we can prove reuse."""

    def __init__(self) -> None:
        self.similarity_calls = 0

    def similarity(self, a: str, b: str) -> float:
        self.similarity_calls += 1
        return super().similarity(a, b)


def _fixed_criteria(cid):
    return SearchCriteria(
        campaign_id=cid, titles=("Senior Python Engineer",), keywords=("python",)
    )


@given("a posting already scored against fixed criteria")
def posting_scored_fixed(t05ctx):
    storage = InMemoryStorage()
    embedding = _CountingEmbedding()
    cid = _seed_campaign(storage)
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Senior Python Engineer",
        company="Acme",
        source_url="https://acme.test/job",
        work_mode="remote",
        description="python backend",
        source_key="jobspy:indeed",
    )
    storage.postings.add(posting)
    storage.commit()
    scoring = ScoringService(storage, llm=None, embedding=embedding, threshold=0)
    criteria = _fixed_criteria(cid)
    first = scoring.score_for_digest(storage.postings.get(posting.id), criteria)
    t05ctx.update(
        storage=storage,
        embedding=embedding,
        campaign_id=cid,
        posting_id=posting.id,
        scoring=scoring,
        criteria=criteria,
        first_score=first.score,
    )


@when("the digest re-scores it with the same criteria")
def rescore_same_criteria(t05ctx):
    before = t05ctx["embedding"].similarity_calls
    posting = t05ctx["storage"].postings.get(t05ctx["posting_id"])
    t05ctx["second"] = t05ctx["scoring"].score_for_digest(posting, t05ctx["criteria"])
    t05ctx["calls_during_rescore"] = t05ctx["embedding"].similarity_calls - before


@then("the persisted score is reused without recomputation")
def reused_without_recompute(t05ctx):
    assert t05ctx["calls_during_rescore"] == 0
    assert t05ctx["second"].score == t05ctx["first_score"]


@when("the digest re-scores it after the criteria change")
def rescore_changed_criteria(t05ctx):
    before = t05ctx["embedding"].similarity_calls
    changed = SearchCriteria(
        campaign_id=t05ctx["campaign_id"],
        titles=("Staff Python Engineer",),
        keywords=("python", "kubernetes"),
    )
    posting = t05ctx["storage"].postings.get(t05ctx["posting_id"])
    t05ctx["changed_score"] = t05ctx["scoring"].score_for_digest(posting, changed)
    t05ctx["calls_during_rescore"] = t05ctx["embedding"].similarity_calls - before


@then("a fresh score is computed for the new criteria")
def fresh_score_computed(t05ctx):
    assert t05ctx["calls_during_rescore"] > 0


@given("a posting scored at cold start before any conversions")
def posting_cold_start(t05ctx):
    storage, embedding, learning = _wire_learning()
    cid = _seed_campaign(storage)
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Senior Python Engineer",
        company="Acme",
        source_url="https://acme.test/job",
        work_mode="remote",
        description="python backend distributed systems",
        source_key="jobspy:indeed",
    )
    storage.postings.add(posting)
    storage.commit()
    scoring = ScoringService(
        storage, llm=None, embedding=embedding, threshold=0, learning=learning
    )
    criteria = _fixed_criteria(cid)
    cold = scoring.score_for_digest(storage.postings.get(posting.id), criteria)
    t05ctx.update(
        storage=storage,
        embedding=embedding,
        learning=learning,
        campaign_id=cid,
        posting_id=posting.id,
        scoring=scoring,
        criteria=criteria,
        cold_score=cold.score,
    )


@when("the campaign learns a converting-role signature that aligns with the posting")
def learn_converting_signature(t05ctx):
    learning = t05ctx["learning"]
    model = learning.load_model(t05ctx["campaign_id"])
    # Fold the very role text the posting carries so the signature strongly aligns —
    # this should push a fresh score UP via _SIGNATURE_WEIGHT, if reuse were learning-aware.
    posting = t05ctx["storage"].postings.get(t05ctx["posting_id"])
    jd = f"{posting.title} {posting.description}"
    for _ in range(5):
        model = learning.record_converting_role(model, jd, title=posting.title)
    learning.persist_model(model)


@when("the digest re-scores it with unchanged criteria")
def rescore_after_learning(t05ctx):
    posting = t05ctx["storage"].postings.get(t05ctx["posting_id"])
    t05ctx["post_learning"] = t05ctx["scoring"].score_for_digest(
        posting, t05ctx["criteria"]
    )


@then(
    "the digest reflects the higher learning-biased score rather than the stale one"
)
def digest_reflects_learning(t05ctx):
    # #239: the digest cache key now folds a learning-state signature, so learning the
    # converting-role signature invalidates the stale cold score even with UNCHANGED
    # criteria — the re-score recomputes and reflects the higher learning-biased value.
    assert t05ctx["post_learning"].score > t05ctx["cold_score"]


# ===========================================================================
# #240 — swallow never breaks submit (GREEN) + warn-on-loss (PENDING)
# ===========================================================================
class _RaisingLearning:
    """AdvancedLearningService stand-in whose conversion record always raises."""

    def record_and_persist_conversion(self, *args, **kwargs):
        raise RuntimeError("campaign deleted mid-flight")


def _wire_submission(*, advanced):
    from applicant.application.services.submission_service import SubmissionService

    storage, embedding, learning = _wire_learning()
    cid = _seed_campaign(storage)
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Senior Python Engineer",
        company="Acme",
        source_url="https://acme.test/job",
        work_mode="remote",
        description="python",
        source_key="jobspy:indeed",
    )
    storage.postings.add(posting)
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=posting.id,
            status=ApplicationState.AWAITING_FINAL_APPROVAL,
        )
    )
    storage.commit()
    submission = SubmissionService(
        storage, browser=None, learning=learning, advanced_learning=advanced
    )
    return storage, submission, aid


@given("a submission service whose conversion learning always raises")
def submission_raising_learning(t05ctx):
    storage, submission, aid = _wire_submission(advanced=_RaisingLearning())
    t05ctx.update(storage=storage, submission=submission, application_id=aid)


@given("a submission service wired with no conversion learning")
def submission_no_learning(t05ctx):
    storage, submission, aid = _wire_submission(advanced=None)
    t05ctx.update(storage=storage, submission=submission, application_id=aid)


@when("an approved application is submitted")
def submit_approved_application(t05ctx, caplog):
    app = t05ctx["storage"].applications.get(t05ctx["application_id"])
    with caplog.at_level(logging.WARNING):
        t05ctx["event"] = t05ctx["submission"].record_submission(
            app, source=OutcomeSource.AUTO
        )
    t05ctx["log_text"] = caplog.text


@then("the submission is still recorded with an outcome event")
def submission_recorded(t05ctx):
    assert t05ctx["event"] is not None
    assert t05ctx["event"].type == "submitted"
    outcomes = t05ctx["storage"].outcomes.list_for_application(t05ctx["application_id"])
    assert any(o.type == "submitted" for o in outcomes)


@then("a warning is logged that the conversion could not be recorded")
def conversion_loss_logged(t05ctx):
    # Today _close_conversion_loop returns silently when no AdvancedLearningService is
    # wired (and swallows failures without a log). A warning naming the lost conversion
    # is the residual gap — genuine red for @pending.
    text = t05ctx["log_text"].lower()
    assert "conversion" in text and ("warn" in text or "could not" in text or "no learning" in text)
