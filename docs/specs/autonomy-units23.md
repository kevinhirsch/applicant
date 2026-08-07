# Work order: autonomy UNIT 2 (auto-draft keystone) + UNIT 3 (no-SAFe positioning) + tiny digest cosmetic

**Branch:** `claude/refactor-agent-zero-applicant-xn7xoc`. Commit locally, NO push. Prerequisite UNIT 1 (screening-answer upsert) is already committed. You MAY use subordinate agents to parallelize UNIT 2 vs UNIT 3 (disjoint files) but SERIALIZE commits (one clean commit per unit). Make UNIT 2 and UNIT 3 (and the cosmetic) SEPARATE commits.

## UNIT 2 (KEYSTONE) — tick auto-DRAFTS materials for top-N viable roles. File: `src/applicant/application/services/agent_loop.py` (+ companion fix in `digest_service.py`).
Goal: on each tick, auto-generate tailored materials (resume variant + cover letter + screening answers) for the top-N freshest VIABLE roles, leaving apps in DIGESTED status so they sit in the review queue — WITHOUT ever calling approve() (approve triggers the live camoufox browser pipeline; NEVER auto-call it). Reuse the existing safe `AgentLoop._prepare_material_for(campaign, app)` for resume+cover-letter (it only touches storage+material, safe on a DIGESTED app; `_deferred_questions` returns [] pre-prefill). For screening answers, call `MaterialService.generate_screening_answer` directly for a few generic questions (work-auth is now stored, so it auto-answers).

- Module constants near `_APPROVAL_START_FAILURE_CAP`:
```python
_AUTO_DRAFT_TOP_N_DEFAULT = 3   # campaign.schedule["auto_draft_top_n"] overrides; 0 = kill switch
_AUTO_DRAFT_SCREENING_QUESTIONS = (
    "Why are you interested in the {title} role at {company}?",
    "How many years of relevant professional experience do you have?",
    "Are you legally authorized to work in the United States?",
)
```
- `TickResult` (~line 275): add `auto_drafted: list[str] = field(default_factory=list)`.
- New `_auto_draft_top_viable(campaign, result, now)` called in `_tick` IMMEDIATELY AFTER `_discover_and_digest` and BEFORE `_process_approvals`. Logic: if `self._material` or `self._digest` is None → return; `top_n = campaign.schedule.get("auto_draft_top_n", _AUTO_DRAFT_TOP_N_DEFAULT)`; `limit = min(top_n, self.remaining_budget(campaign, now))` (ceiling only — do NOT call `_record_acted`, drafting must not consume the daily pipeline-start cap); iterate `self._digest.build_digest(campaign.id, self._criteria_for(campaign.id))`; skip rows with `row.get("warnings")`; skip if `self._storage.applications.get_by_posting(campaign.id, posting_id) is not None` (idempotent); for each up to `limit`, call `_auto_draft_one`; per-role try/except with `self._storage.rollback()` on failure (isolation); append posting_ids to `result.auto_drafted`.
- `_auto_draft_one(campaign, posting_id)`: load posting; create `Application(id=ApplicationId(new_id()), campaign_id, posting_id, status=ApplicationState.DIGESTED, job_title=posting.title, work_mode=posting.work_mode, root_url=posting.source_url)`; `add` + `commit`; call `self._prepare_material_for(campaign, app)`; then for each screening template (formatted with posting.title/company) call `self._material.generate_screening_answer(campaign.id, app.id, question, self._true_source(campaign, app, posting))` in its own try/except+rollback. (Match the REAL signatures of _prepare_material_for / _true_source / generate_screening_answer / remaining_budget / _criteria_for — grep them; don't invent.)
- Optional: fold `result.auto_drafted` count into `_intent_sentence`.

### COMPANION FIX (critical, in `digest_service.py`) — `_application_for` must ADVANCE status on an existing app.
Currently `_application_for(target_id, status=...)` returns an EXISTING application's id WITHOUT changing its status (status is only set at new-row creation). Once auto-draft creates DIGESTED apps, a later human `approve()` hits this path and the app stays DIGESTED forever (`_process_approvals` skips non-APPROVED) — so approving a drafted role would silently do nothing. Fix: when an existing application is found (by id OR by get_by_posting), advance it via a legal transition:
```python
def _advance_if_legal(self, app, status):
    if app.status is status: return
    try:
        updated = app.with_status(status)   # validates via core/state_machine (DIGESTED->APPROVED/DECLINED legal)
    except IllegalStateTransition:
        return
    self._storage.applications.update(updated); self._storage.commit()
```
Call it in `_application_for` for BOTH existing-by-id and existing-by-posting branches (import IllegalStateTransition from applicant.core.errors). Leave new-row creation unchanged.

### Tests (tests/unit/test_agent_loop.py + test_digest_delivery.py): top-N drafted; idempotent re-run (no dupes); warnings skipped; budget bound; kill switch (0); one-role-failure isolated; and approve-after-auto-draft flips DIGESTED->APPROVED and _process_approvals picks it up.

## UNIT 3 — positioning directive (foreground LeSS/Kanban, de-emphasize SAFe) from learned likes/dislikes. Files: `learning_service.py`, `core/rules/materials.py`, `material_service.py`.
The learning model already has `like:LeSS/Kanban` + `dislike:SAFe/Scaled Agile` (backfilled). Make material generation USE them (currently it never reads likes/dislikes).
- `learning_service.py`: add `top_likes(model, limit=5)` + `top_dislikes(model, limit=5)` reading `like:`/`dislike:` feature_stats keys (mirror `decline_reasons` ranking; factor a shared `_top_tagged(prefix, bucket_suffix)` helper).
- `core/rules/materials.py`: add pure `positioning_directive(likes, dislikes) -> str` — "Lead with / foreground, when truthfully supported: <likes>. Give minimal space to (never deny/omit/falsify if directly asked): <dislikes>." Empty string if both empty. NEVER a license to omit truthful résumé facts (fabrication guard unchanged).
- `material_service._generate_text` (~line 2354, after `aggressiveness_directive`): if `self._learning` and `campaign_id`, load model, append `positioning_directive(self._learning.top_likes(model), self._learning.top_dislikes(model))` to the system prompt. Wrap in try/except pass. Only affects cover_letter/essay paths.
- Tests: `test_materials_rules.py` (positioning_directive cases) + learning_service top_likes/top_dislikes + optionally a _generate_text test asserting the directive appears when dislike:SAFe present.

## COSMETIC (tiny, separate commit) — digest.html duplicate title
In `a0-applicant/webui/digest.html` the row now shows the title twice (a `.title` div AND a `.role` div both `x-text="row.title"`). Remove the redundant `.role` line (keep `.title`). One-line change.

## Verify each unit
`cd /a0/usr/projects/applicant && uv run python -m pytest tests/unit/test_agent_loop.py tests/unit/test_digest_delivery.py tests/unit/test_materials_rules.py tests/unit/test_az2_digest_panel.py -q --tb=short` then the FULL suite (`uv run python -m pytest tests/unit -q --tb=line`) — expect only the 2 known pre-existing failures.
Commits: UNIT2 `feat(engine): hands-off autonomy — tick auto-drafts materials for top-N viable roles (DIGESTED, review-gated, never auto-approve) + advance existing-app status on approve/decline [FR-AUTO]`; UNIT3 `feat(engine): material positioning from learned likes/dislikes (foreground LeSS/Kanban, de-emphasize SAFe; no fabrication) [FR-LEARN]`; cosmetic `fix(ui): drop duplicate title in digest row`.
Report each commit's files + test counts. (Engine src → I handle the api rebuild.)
