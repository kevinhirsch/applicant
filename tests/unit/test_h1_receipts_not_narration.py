"""H1 — receipts, not narration (Phase 1.5 honesty invariant; engine half).

DoD: every number/claim the owner reads (Today "what I did", the Activity
feed, Tracker counts, the digest/weekly recap) is a projection of RECORDED
actions — never an LLM describing what it thinks it did. "An audit confirms
no claim-path narrates; a test pins it." This module IS that pin, in two
layers:

1. **Behavioral pins** — the sentences/claims are pure, deterministic
   projections of the recorded counters they cite (the intent sentence from a
   tick's own counts, the daily status update from the persisted run status,
   the weekly recap from the submission-snapshot log).

2. **The audit, machine-checked** — every claim-path callable enumerated in
   the audit (``docs/design/audits/h1-receipts-audit.md``) is source-scanned
   for model-invocation tokens: none may build a prompt, reach a tier ladder,
   or call a completion API. A canary asserts the scanner would catch a real
   LLM path (``ChatService._reply_text``), so the token list can't silently
   rot into a vacuous check.

The front-door half (per-run receipts in Activity, the Today count linking to
its run trail) is pinned in ``workspace/tests/test_applicant_h1_receipts.py``.
The weekly recap's projection behavior is additionally covered in depth by
``tests/unit/test_cov_round2_weeklyrecap.py`` (counts only recorded
submissions; never fabricates interview/offer counts).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from applicant.app.routers import agent_status as agent_status_router
from applicant.application.services.agent_loop import AgentLoop, TickResult
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.chat_service import ChatService
from applicant.application.services.cost_service import CostService
from applicant.application.services.digest_service import DigestService
from applicant.application.services.status_update import StatusUpdateService

# ── 1. behavioral pins: claims are projections of recorded counts ───────────


def _tick(**kw) -> TickResult:
    return TickResult(campaign_id="c1", **kw)


class TestIntentSentenceIsAProjection:
    """The per-run intent sentence (what the Activity feed/strip shows) is a
    deterministic template over the tick's OWN counters — same input, same
    sentence, counters quoted verbatim. ``_intent_sentence`` reads nothing but
    the ``TickResult`` (calling it unbound with ``self=None`` proves it can't
    consult an LLM or any other instance state)."""

    def test_counts_flow_verbatim_into_the_sentence(self):
        result = _tick(pipelines_started=["a", "b"], digest_rows=3)
        sentence = AgentLoop._intent_sentence(None, None, result)
        assert "2" in sentence and "3" in sentence
        assert "Pre-filling" in sentence

    def test_digest_only_tick_reports_its_own_row_count(self):
        sentence = AgentLoop._intent_sentence(None, None, _tick(digest_rows=7))
        assert "7" in sentence and "digest" in sentence.lower()

    def test_no_work_yet_reads_as_scanning_not_as_invented_output(self):
        sentence = AgentLoop._intent_sentence(None, None, _tick())
        assert "Scanning" in sentence
        # No number is fabricated for a tick that did nothing countable.
        assert not any(ch.isdigit() for ch in sentence)

    def test_budget_exhausted_wins_and_is_deterministic(self):
        result = _tick(budget_exhausted=True, digest_rows=5)
        first = AgentLoop._intent_sentence(None, None, result)
        second = AgentLoop._intent_sentence(None, None, result)
        assert first == second
        assert "budget" in first.lower()


class TestDailyStatusUpdateClaimsEqualRecordedCounts:
    """The once-daily "Since yesterday I …" push counts only what the persisted
    run status actually recorded, and says NOTHING when no source can answer
    (the absence of data must never render as activity)."""

    def test_started_count_is_the_recorded_applied_today(self):
        runs = SimpleNamespace(
            status=lambda cid: {
                "applied_today": 3,
                "daily_budget": 15,
                "paused": False,
                "latest_intent": "",
            }
        )
        svc = StatusUpdateService(agent_run_service=runs)
        msg = svc.build_message("c1", datetime.now(UTC))
        assert msg is not None
        assert "started 3 applications toward today's budget of 15" in msg

    def test_no_sources_means_no_message_not_an_invented_one(self):
        assert StatusUpdateService().build_message("c1", datetime.now(UTC)) is None


class TestWeeklyRecapCountsOnlyRecordedSubmissions:
    """"This week I sent N" — N is the count of submission snapshots captured
    in the window (the durable stop-boundary evidence of what was actually
    sent), quoted verbatim in the body."""

    def _service(self, snapshots):
        storage = SimpleNamespace(
            submission_snapshots=SimpleNamespace(
                list_for_campaign=lambda cid: list(snapshots)
            )
        )
        return DigestService(storage, None)

    def test_recap_body_quotes_the_snapshot_count(self):
        now = datetime.now(UTC)
        snaps = [
            SimpleNamespace(captured_at=now - timedelta(days=1)),
            SimpleNamespace(captured_at=now - timedelta(days=2)),
            # Outside the 7-day window: recorded, but not THIS week's claim.
            SimpleNamespace(captured_at=now - timedelta(days=30)),
        ]
        svc = self._service(snaps)
        recap = svc.build_weekly_recap("c1", now=now)
        assert recap["applications_sent"] == 2
        message = svc.render_weekly_recap_message("c1", recap=recap)
        assert "I sent 2 applications" in message["body"]

    def test_zero_sent_is_said_plainly_never_padded(self):
        svc = self._service([])
        message = svc.render_weekly_recap_message(
            "c1", recap=svc.build_weekly_recap("c1", now=datetime.now(UTC))
        )
        assert "didn't send any new applications" in message["body"]


# ── 2. the audit, machine-checked: no claim path can invoke a model ─────────
#
# The claim-path callables behind each surface named in the H1 DoD. Every
# entry is source-scanned for model-invocation tokens. Keep this list in sync
# with docs/design/audits/h1-receipts-audit.md (the audit record).

CLAIM_PATH_CALLABLES = [
    # Activity feed / status strip: the recorded intent sentence + run status.
    AgentLoop._intent_sentence,
    AgentLoop._record_intent,
    AgentLoop._record_skip_reason,
    AgentRunService.status,
    AgentRunService.latest_intent,
    # Activity "Right now / Up next" snapshot sentences.
    agent_status_router._now_sentence,
    agent_status_router._next_sentence,
    agent_status_router.agent_status,
    # The once-daily status update push.
    StatusUpdateService.build_message,
    StatusUpdateService._past_lines,
    StatusUpdateService._present_lines,
    StatusUpdateService._future_lines,
    # Today "what I did" (the cost & pace guardrails numbers).
    CostService.today_summary,
    CostService.monthly_projection,
    # Digest claims: the "what I searched" line + the weekly recap.
    DigestService._searched_summary,
    DigestService.build_weekly_recap,
    DigestService._applications_sent_between,
    DigestService._best_source_for_recap,
    DigestService.render_weekly_recap_message,
]

#: Substrings that mark code as building/dispatching a model call. Chosen to
#: hit real invocation sites (prompt assembly, the tier ladder, completion
#: calls) without false-positiving on RECORDED usage counters like the
#: ``"llm_calls"`` stats key (which is bookkeeping about calls that already
#: happened elsewhere — exactly the receipt H1 wants kept).
MODEL_INVOCATION_TOKENS = ("prompt", "ladder", ".complete(", ".generate(", "tier")


def _source(fn) -> str:
    return inspect.getsource(fn)


def test_no_claim_path_narrates():
    """The audit's core assertion: none of the enumerated claim-path callables
    contains a model-invocation token — every claim is a projection of stored
    rows, with no way to ask a model what happened."""
    offenders = {}
    for fn in CLAIM_PATH_CALLABLES:
        src = _source(fn).lower()
        hits = [tok for tok in MODEL_INVOCATION_TOKENS if tok in src]
        if hits:
            offenders[f"{fn.__qualname__}"] = hits
    assert not offenders, (
        "claim-path callable(s) reference model invocation — a user-facing "
        f"claim about work done may now be narration, not a receipt: {offenders}"
    )


def test_the_scanner_catches_a_real_llm_path():
    """Canary: the token list must flag a genuine narration-capable path
    (``ChatService._reply_text`` builds a prompt and calls ``.complete(``), so
    ``test_no_claim_path_narrates`` can never rot into a vacuous pass."""
    src = _source(ChatService._reply_text).lower()
    assert any(tok in src for tok in MODEL_INVOCATION_TOKENS)


def test_claim_path_list_matches_the_audit_doc():
    """The audit record and the machine check enumerate the same callables, so
    neither can drift without the other noticing."""
    import pathlib

    doc = (
        pathlib.Path(__file__).resolve().parents[2]
        / "docs"
        / "design"
        / "audits"
        / "h1-receipts-audit.md"
    ).read_text(encoding="utf-8")
    for fn in CLAIM_PATH_CALLABLES:
        name = fn.__qualname__.split(".")[-1]
        assert name in doc, f"audit doc is missing claim-path callable {name}"
