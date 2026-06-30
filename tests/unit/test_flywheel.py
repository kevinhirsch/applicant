"""Hermetic tests for the #306 self-improvement flywheel.

Covers, with the LLM/planner fully mocked and no live browser:

* **AWM workflow-induction** — a successful planner-driven pre-fill induces a
  reusable routine keyed by the page's domain into the process-lived RoutineStore.
* **Prior injection** — a second run on the same domain injects the stored routine
  into the planner's ``PlannerInput.prior_routine``.
* **Process-lived persistence** — the RoutineStore survives across simulated
  scheduler ticks (a fresh PrefillService per tick sharing the SAME injected store),
  proving it is not reset per tick.
* **Reflexion self-healing** — a broken selector triggers a reflective re-plan; the
  reflection reaches the NEXT planner input rather than dead-stopping.
* **ACE curation** — a routine that fails on reuse past the prune threshold is
  removed and no longer injected.

Safety: every assertion runs through the planner path's existing STOP boundary; the
flywheel only influences PLANNING priors + re-plan. No new submit authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.routine.in_memory import InMemoryRoutineStore
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.prefill_service import PrefillService
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.plan import FillOp, Plan, StopOp
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    JobPostingId,
    new_id,
)
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.browser_automation import PageState
from applicant.ports.driven.routine_store import Routine, RoutineStep, RoutineStore
from applicant.ports.driving.planner import PlannerInput

APPLY_URL = "https://acme.myworkdayjobs.com/job/999"
DOMAIN = "acme.myworkdayjobs.com"


# ── Fakes ──────────────────────────────────────────────────────────────────


@dataclass
class RecordingPlanner:
    """Stub PlannerPort that records every PlannerInput and replays a plan queue.

    ``plans`` is consumed front-to-back; the last plan is reused once exhausted, so
    a single-plan queue behaves like a fixed planner. ``inputs`` captures every
    ``PlannerInput`` so tests can assert on priors / reflections.
    """

    plans: list[Plan]
    inputs: list[PlannerInput] = field(default_factory=list)

    def plan(self, input_: PlannerInput) -> Plan:
        self.inputs.append(input_)
        idx = min(len(self.inputs) - 1, len(self.plans) - 1)
        return self.plans[idx]

    def plan_many(self, goal, pages, facts):
        return [self.plan(PlannerInput(goal=goal)) for _ in pages]


class _PlannerBrowser:
    """Minimal fake browser for the planner path; ``fill_field`` may be made to fail.

    A single page (the form + submit). ``fail_refs`` is a set of refs whose
    ``fill_field`` raises (simulating a broken selector) for the FIRST attempt only;
    after a re-plan they succeed, modelling a self-healed locator.
    """

    def __init__(self, *, fail_refs=None, heal_after=True):
        self._filled: dict[str, str] = {}
        self._fail_refs = set(fail_refs or ())
        self._heal_after = heal_after
        self._attempts: dict[str, int] = {}

    def open(self, aid, url, **kwargs):
        pass

    def enter_application(self, aid):
        pass

    def current_state(self, aid):
        return PageState(url=APPLY_URL, fields=(), body="<form>...</form>")

    def detect_fields(self, aid):
        return []

    def fill_field(self, aid, selector, value):
        self._attempts[selector] = self._attempts.get(selector, 0) + 1
        if selector in self._fail_refs and not (
            self._heal_after and self._attempts[selector] > 1
        ):
            raise RuntimeError(f"selector {selector!r} not found")
        self._filled[selector] = value

    def click(self, aid, selector):
        pass

    def upload_file(self, aid, selector, path):
        pass

    def advance(self, aid):
        return None

    def is_account_create_page(self, aid):
        return False

    def is_account_gate(self, aid):
        return False

    def is_final_submit_page(self, aid):
        return False

    def screenshot(self, aid):
        return "fake://shot"

    def tenant_key(self, aid):
        return DOMAIN


def _app(cid):
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        root_url=APPLY_URL,
    )


def _attr(cid, name, value):
    return Attribute(id=AttributeId(new_id()), campaign_id=cid, name=name, value=value)


def _service(browser, planner, routine_store, *, max_replans=2):
    return PrefillService(
        storage=InMemoryStorage(),
        browser=browser,
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
        notification=None,
        planner=planner,
        use_planner=True,
        routine_store=routine_store,
        max_replans=max_replans,
    )


def _good_plan():
    # A schema-valid plan that fills two known fields then stops at final submit.
    return Plan(ops=(
        FillOp(ref="r1", attribute_id="first_name"),
        FillOp(ref="r2", attribute_id="email"),
        StopOp(reason="final_submit"),
    ))


# ── Port / adapter unit behaviour ───────────────────────────────────────────


class TestRoutineStoreAdapter:
    def test_in_memory_store_satisfies_port(self):
        assert isinstance(InMemoryRoutineStore(), RoutineStore)

    def test_induce_and_get(self):
        store = InMemoryRoutineStore()
        steps = (RoutineStep(kind="fill", ref="r1", attribute_id="first_name"),)
        store.induce(DOMAIN, steps)
        got = store.get(DOMAIN)
        assert got is not None
        assert got.steps == steps
        assert got.successes == 1

    def test_empty_steps_not_induced(self):
        store = InMemoryRoutineStore()
        assert store.induce(DOMAIN, ()) is None
        assert store.get(DOMAIN) is None

    def test_reinduce_upweights(self):
        store = InMemoryRoutineStore()
        steps = (RoutineStep(kind="fill", ref="r1", attribute_id="first_name"),)
        store.induce(DOMAIN, steps)
        store.induce(DOMAIN, steps)
        assert store.get(DOMAIN).successes == 2

    def test_prior_text_is_data_only(self):
        r = Routine(domain=DOMAIN, steps=(
            RoutineStep(kind="fill", ref="r1", attribute_id="first_name"),
            RoutineStep(kind="click", ref="next"),
        ))
        text = r.as_prior_text()
        assert "attribute_id=first_name" in text
        assert "ref=r1" in text
        # No literal values leak — only ids/locators/op-kinds.
        assert "Alice" not in text


# ── AWM induction + prior injection ─────────────────────────────────────────


class TestInductionAndPriorInjection:
    def test_success_induces_routine_keyed_by_domain(self):
        store = InMemoryRoutineStore()
        planner = RecordingPlanner(plans=[_good_plan()])
        svc = _service(_PlannerBrowser(), planner, store)
        cid = CampaignId(new_id())
        attrs = [_attr(cid, "first_name", "Alice"), _attr(cid, "email", "a@b.com")]

        svc.prefill_application(_app(cid), APPLY_URL, attrs)

        routine = store.get(DOMAIN)
        assert routine is not None, "a routine should be induced for the domain"
        kinds = [s.kind for s in routine.steps]
        assert kinds == ["fill", "fill"], "only the ops that worked are induced"
        assert [s.attribute_id for s in routine.steps] == ["first_name", "email"]

    def test_second_run_injects_prior_into_planner(self):
        store = InMemoryRoutineStore()
        cid = CampaignId(new_id())
        attrs = [_attr(cid, "first_name", "Alice"), _attr(cid, "email", "a@b.com")]

        # First run induces.
        p1 = RecordingPlanner(plans=[_good_plan()])
        _service(_PlannerBrowser(), p1, store).prefill_application(_app(cid), APPLY_URL, attrs)
        assert p1.inputs[0].prior_routine is None, "no prior on the very first encounter"

        # Second run on the SAME domain injects the stored routine as a prior.
        p2 = RecordingPlanner(plans=[_good_plan()])
        _service(_PlannerBrowser(), p2, store).prefill_application(_app(cid), APPLY_URL, attrs)
        assert p2.inputs[0].prior_routine is not None, "second run injects the prior"
        assert "attribute_id=first_name" in p2.inputs[0].prior_routine


class TestProcessLivedAcrossTicks:
    """The RoutineStore survives across simulated scheduler ticks (process-lived).

    Each 'tick' builds a FRESH PrefillService (as container._build_tick_services
    does) but injects the SAME process-lived store. The routine induced on tick 1
    must still be present — and injected as a prior — on tick 2's fresh service.
    """

    def test_store_not_reset_per_tick(self):
        store = InMemoryRoutineStore()  # ONE process-lived store
        cid = CampaignId(new_id())
        attrs = [_attr(cid, "first_name", "Alice"), _attr(cid, "email", "a@b.com")]

        def tick():
            # Fresh service per tick — mirrors the per-tick rebuild.
            planner = RecordingPlanner(plans=[_good_plan()])
            svc = _service(_PlannerBrowser(), planner, store)
            svc.prefill_application(_app(cid), APPLY_URL, attrs)
            return planner

        tick()  # tick 1 — induces
        assert store.get(DOMAIN) is not None
        successes_after_t1 = store.get(DOMAIN).successes

        p2 = tick()  # tick 2 — a brand-new service still sees the routine
        assert p2.inputs[0].prior_routine is not None, (
            "the routine must persist across the per-tick service rebuild"
        )
        # Reuse up-weighted it (ACE) — proof it's the same object, not a fresh one.
        assert store.get(DOMAIN).successes > successes_after_t1


# ── Reflexion self-healing ──────────────────────────────────────────────────


class TestReflexionReplan:
    def test_broken_selector_triggers_reflective_replan(self):
        store = InMemoryRoutineStore()
        # r1 fails on the first attempt, heals on the re-plan.
        browser = _PlannerBrowser(fail_refs={"r1"}, heal_after=True)
        planner = RecordingPlanner(plans=[_good_plan(), _good_plan()])
        svc = _service(browser, planner, store, max_replans=2)
        cid = CampaignId(new_id())
        attrs = [_attr(cid, "first_name", "Alice"), _attr(cid, "email", "a@b.com")]

        svc.prefill_application(_app(cid), APPLY_URL, attrs)

        # The planner was called at least twice — a re-plan happened.
        assert len(planner.inputs) >= 2, "a broken selector must trigger a re-plan"
        # The reflection reached the NEXT planner input (Reflexion), not a dead stop.
        replan_input = planner.inputs[1]
        assert replan_input.reflection is not None
        assert "r1" in replan_input.reflection
        assert "broken" in replan_input.reflection or "stale" in replan_input.reflection

    def test_first_input_has_no_reflection(self):
        store = InMemoryRoutineStore()
        browser = _PlannerBrowser(fail_refs={"r1"}, heal_after=True)
        planner = RecordingPlanner(plans=[_good_plan(), _good_plan()])
        svc = _service(browser, planner, store)
        cid = CampaignId(new_id())
        attrs = [_attr(cid, "first_name", "Alice"), _attr(cid, "email", "a@b.com")]
        svc.prefill_application(_app(cid), APPLY_URL, attrs)
        assert planner.inputs[0].reflection is None


# ── ACE curation ────────────────────────────────────────────────────────────


class TestAceCuration:
    def test_failing_reused_routine_pruned_and_no_longer_injected(self):
        # Threshold 2: two net failures on reuse prunes the routine.
        store = InMemoryRoutineStore(prune_threshold=2)
        # Seed a routine as if a prior run induced it.
        store.induce(DOMAIN, (RoutineStep(kind="fill", ref="r1", attribute_id="first_name"),))
        assert store.get(DOMAIN) is not None
        base_successes = store.get(DOMAIN).successes

        cid = CampaignId(new_id())
        attrs = [_attr(cid, "first_name", "Alice"), _attr(cid, "email", "a@b.com")]

        # Each run: r1 stays broken (heal_after=False) so the prior mis-grounds and
        # the planner can't recover within budget → ACE down-weights the routine.
        def failing_run():
            browser = _PlannerBrowser(fail_refs={"r1"}, heal_after=False)
            planner = RecordingPlanner(plans=[_good_plan(), _good_plan(), _good_plan()])
            svc = _service(browser, planner, store, max_replans=2)
            svc.prefill_application(_app(cid), APPLY_URL, attrs)
            return planner

        # Drive enough failing reuses to cross the prune threshold (each run records
        # at least one failure against the prior). With base successes the margin
        # needs failures - successes >= threshold, so run until pruned.
        for _ in range(base_successes + 4):
            failing_run()
            if store.get(DOMAIN) is None:
                break

        assert store.get(DOMAIN) is None, "a persistently-failing routine is pruned (ACE)"

        # A subsequent run no longer injects a prior (the routine is gone).
        final = failing_run()
        assert final.inputs[0].prior_routine is None

    def test_record_failure_prunes_at_threshold(self):
        store = InMemoryRoutineStore(prune_threshold=1)
        store.induce(DOMAIN, (RoutineStep(kind="fill", ref="r1"),))  # successes=1
        # Need failures - successes >= 1 → 2 failures.
        assert store.record_failure(DOMAIN) is not None  # failures=1, margin 0
        assert store.record_failure(DOMAIN) is None       # failures=2, margin 1 -> pruned
        assert store.get(DOMAIN) is None


# ── STOP boundary still intact under the flywheel ───────────────────────────


class TestStopBoundaryUntouched:
    def test_final_submit_still_routes_to_awaiting_final_approval(self):
        store = InMemoryRoutineStore()
        planner = RecordingPlanner(plans=[_good_plan()])
        svc = _service(_PlannerBrowser(), planner, store)
        cid = CampaignId(new_id())
        attrs = [_attr(cid, "first_name", "Alice"), _attr(cid, "email", "a@b.com")]

        result = svc.prefill_application(_app(cid), APPLY_URL, attrs)
        # The flywheel never grants submit authority: the final_submit StopOp still
        # lands AWAITING_FINAL_APPROVAL, exactly as without it.
        assert result.state == ApplicationState.AWAITING_FINAL_APPROVAL
