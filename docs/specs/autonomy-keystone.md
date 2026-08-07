# Work order: KEYSTONE autonomy — auto-advance top-N freshest viable roles into drafting (hands-off)

**Branch:** `claude/refactor-agent-zero-applicant-xn7xoc`. Commit locally, **do NOT push**. This is the single change that makes Applicant run hands-off: today the tick discovers→scores→delivers the digest but NEVER auto-creates an APPROVE decision, so `_process_approvals` has nothing to process → 0 applications ever. Fix: inside the tick, auto-approve the top-N freshest viable roles by calling the EXISTING `DigestService.approve()` (identical to a human clicking Approve). All downstream plumbing (Application creation, presubmit safety, pipeline → material generation → MATERIAL_REVIEW/AWAITING_FINAL_APPROVAL review gate, budget, notifications, learning fold) already works — do NOT change it.

**File:** `src/applicant/application/services/agent_loop.py` ONLY (+ a new unit test). Verify all line numbers/signatures against the ACTUAL current file — the references below are approximate.

## Change 1 — module constant (near other tick constants, e.g. by `_APPROVAL_START_FAILURE_CAP` ~line 70)
```python
#: Default number of top freshest-viable roles the tick auto-advances into drafting
#: per campaign (hands-off autonomy). Bounded further by remaining daily budget.
#: Override per campaign via campaign.schedule["auto_advance_top_n"]; set 0 to disable.
_DEFAULT_AUTO_ADVANCE_TOP_N = 5
```

## Change 2 — `TickResult` gets an `auto_approved` field (dataclass ~line 274)
```python
    auto_approved: list[str] = field(default_factory=list)
```

## Change 3 — new method `_auto_advance_top_viable` on `AgentLoop`
Reuse the EXISTING helpers exactly as the rest of the class does: `self._digest.build_digest(campaign.id, criteria)` (already sorted fit+recency desc, cache-backed), `self._criteria_for(campaign.id)` (or however the class already fetches criteria — match existing call sites), `self._storage.applications.get_by_posting(campaign_id, posting_id)` (idempotency check, used in `_ensure_application`), `self.remaining_budget(campaign, now)` (or the exact existing signature), and `self._digest.approve(posting_id)` (the same call the manual endpoint uses).
```python
    def _auto_advance_top_viable(self, campaign, result, now):
        """Hands-off autonomy: auto-approve the top-N freshest VIABLE, non-flagged,
        not-yet-decided roles so the tick advances them into drafting (materials +
        review gate) without a human click. Bounded by remaining daily budget;
        idempotent; skips rows carrying presubmit warnings (scam/dup/volume-cap)."""
        if self._digest is None:
            return
        top_n = int((campaign.schedule or {}).get("auto_advance_top_n", _DEFAULT_AUTO_ADVANCE_TOP_N))
        if top_n <= 0:
            return
        n = min(top_n, self.remaining_budget(campaign, now))
        if n <= 0:
            return
        criteria = self._criteria_for(campaign.id)
        rows = self._digest.build_digest(campaign.id, criteria)
        picked = 0
        for row in rows:
            if picked >= n:
                break
            if row.get("warnings"):
                continue  # flagged rows (scam/dup/volume-cap) stay manual-only
            posting_id = row.get("posting_id")
            if not posting_id:
                continue
            if self._storage.applications.get_by_posting(campaign.id, posting_id) is not None:
                continue  # already approved/declined/in-flight — idempotent skip
            try:
                self._digest.approve(posting_id)
                picked += 1
                result.auto_approved.append(str(posting_id))
            except Exception as exc:  # one bad posting must not abort the batch
                log.warning("auto_advance_approve_failed", posting_id=str(posting_id), error=str(exc))
```
(Match the real logger name/style used in this file for the warning. Match the real `build_digest`/`approve`/`get_by_posting`/`remaining_budget`/criteria-fetch signatures — do not invent; grep the file.)

## Change 4 — call it in `_tick`, BETWEEN `_discover_and_digest` and `_process_approvals`
So newly auto-approved postings are picked up by `_process_approvals` in the SAME tick:
```python
        self._discover_and_digest(campaign, result, now)      # existing
        self._auto_advance_top_viable(campaign, result, now)  # NEW — auto-approve top-N
        self._process_approvals(campaign, result, now)        # existing (now has decisions to process)
```
(Use the real arg names the existing calls use.)

## Change 5 — optional intent line (`_intent_sentence` ~line 2423)
If `result.auto_approved`, add a clause like `f"auto-advanced {len(result.auto_approved)} fresh role(s) into drafting"` alongside the existing sentence parts, matching the existing style.

## Tests — add `tests/unit/test_auto_advance.py` (or extend an existing agent_loop test)
Use the same fakes/fixtures the existing agent_loop tests use. Cover:
1. A tick with several viable digest rows and `remaining_budget >= top_n` auto-approves exactly `top_n` (or budget, whichever smaller) → that many Applications created and advanced; `result.auto_approved` has the right count.
2. **Idempotent:** running the tick again does NOT re-approve the same postings (get_by_posting excludes them) — no duplicate applications.
3. Rows with `warnings` are skipped (never auto-approved).
4. `auto_advance_top_n = 0` (kill switch) approves nothing.
5. Respects `remaining_budget` (budget < top_n → approves only budget-many).

## Verify + commit
```
cd /a0/usr/projects/applicant && uv run python -m pytest tests/unit/test_auto_advance.py tests/unit/test_s4_flow_fixes.py tests/unit/test_phase5_safety_gates.py -q --tb=short
```
Then the FULL suite must still be green except the 2 known pre-existing failures:
```
cd /a0/usr/projects/applicant && uv run python -m pytest tests/unit -q --tb=line
```
(expect only `test_prod_compose_env_file.py::...` and `test_deploy_hardening_lens04.py::test_chromadb...` failing.)

ONE commit on the branch (NO push):
`feat(engine): hands-off autonomy — tick auto-advances top-N freshest viable roles into drafting via existing approve+pipeline (bounded, idempotent, review-gate preserved) [FR-AUTO]`

Report exact files changed + test counts. This is engine (src) code → requires an api rebuild to deploy (I handle deploy).
