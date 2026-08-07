# Work order: UNIT 1 — real upsert for the screening-answer library (session-poisoning bug fix)

**Branch:** `claude/refactor-agent-zero-applicant-xn7xoc`. Commit locally, **do NOT push**. Fix CODE only. This is a prerequisite for safe multi-role auto-drafting (without it, the shared scheduler-tick session gets poisoned when two applications ask the same screening question).

FIRST: discard any uncommitted working-tree changes from the earlier halted keystone task before starting — `cd /a0/usr/projects/applicant && git checkout -- src/applicant/application/services/agent_loop.py` (only if it shows as modified & uncommitted; leave everything else). Base off current HEAD.

## Root cause (verified)
`MaterialService._save_to_screening_library` (`src/applicant/application/services/material_service.py` ~line 1467-1497) builds a FRESH `ScreeningAnswerLibraryEntry` with a NEW `id` every call and passes it to `repo.upsert()`. `ScreeningAnswerLibraryRepo.upsert` (`src/applicant/adapters/storage/repositories.py` ~line 975-985) does `self._s.merge(...)` — which upserts by PRIMARY KEY (`id`), not by the real unique key `(campaign_id, question_key)` (constraint `uq_screening_answer_library_campaign_key`, `models.py` ~450-453). Since `id` is new each call, `merge()` always stages an INSERT; the duplicate `(campaign_id, question_key)` violates the unique constraint at the NEXT `commit()` (inside an unrelated `_store_document`), with no `rollback()` anywhere → the shared SQLAlchemy session is left in Postgres aborted-transaction state and every later statement in that tick fails.

## Fix 1 — `src/applicant/adapters/storage/repositories.py` (`ScreeningAnswerLibraryRepo.upsert`, ~975-985)
Replace the blind `merge()` with a real select-then-write upsert keyed on `(campaign_id, question_key)`, reusing the existing row's id on update (portable across SQLite tests + Postgres prod — do NOT use dialect-specific ON CONFLICT):
```python
def upsert(self, entry: ScreeningAnswerLibraryEntry) -> None:
    existing = self._s.scalars(
        select(m.ScreeningAnswerLibraryModel)
        .where(m.ScreeningAnswerLibraryModel.campaign_id == entry.campaign_id)
        .where(m.ScreeningAnswerLibraryModel.question_key == entry.question_key)
    ).first()
    if existing is not None:
        existing.question_text = entry.question_text
        existing.answer_text = entry.answer_text
        existing.essay = entry.essay
        return
    self._s.add(m.ScreeningAnswerLibraryModel(
        id=entry.id, campaign_id=entry.campaign_id, question_key=entry.question_key,
        question_text=entry.question_text, answer_text=entry.answer_text, essay=entry.essay,
    ))
```
(Match the ACTUAL field names on the model + entity — grep `ScreeningAnswerLibraryModel` / `ScreeningAnswerLibraryEntry` and adjust if a field differs, e.g. `essay` may be named differently. Match the repo's existing `select`/session attribute style.)

## Fix 2 — defense-in-depth in `material_service.py` `_save_to_screening_library` (~1485-1497)
Flush+guard so a future regression can't poison a later unrelated commit:
```python
try:
    repo.upsert(ScreeningAnswerLibraryEntry(...))   # existing construction
    self._storage.commit()      # surface any error HERE, not at the next unrelated commit
except Exception:
    self._storage.rollback()    # was missing entirely
    self._note_silent_degradation("material_service.py")   # use the real degradation helper this class already has; if none, just log
```
(Use whatever silent-degradation/log helper this class already uses; don't invent a new one — match existing style.)

## Tests — add `tests/unit/test_screening_answer_library_upsert_dupe.py`
Use the REAL SQL repo (the bug does NOT reproduce on InMemoryStorage). Mirror the SQLite fixture in `tests/unit/test_bugsweep_batch_i.py` (~lines 47-60: `make_engine("sqlite:///...")` + `Base.metadata.create_all` + `SqlAlchemyStorage`). Cases:
1. Two `generate_screening_answer` calls (or two direct `repo.upsert` calls) with IDENTICAL question text across two different applications in the same campaign/session must NOT raise; `list_screening_answer_library` shows exactly ONE entry (updated, not duplicated).
2. A subsequent unrelated document generation / commit in the same session still succeeds (proves no poisoning).

## Verify + commit
```
cd /a0/usr/projects/applicant && uv run python -m pytest tests/unit/test_screening_answer_library_upsert_dupe.py tests/unit/test_screening_answer_library.py tests/unit/test_bugsweep_batch_i.py tests/unit/test_cov_backlog_screeninglibrary.py -q --tb=short
```
Then the FULL suite must remain green except the 2 known pre-existing failures:
```
cd /a0/usr/projects/applicant && uv run python -m pytest tests/unit -q --tb=line
```
ONE commit on the branch (NO push):
`fix(engine): real (campaign_id,question_key) upsert for screening-answer library — stop session-poisoning on duplicate questions [FR-FIX]`
Report exact files changed + test counts. (Engine src → I handle the api rebuild/deploy.)
