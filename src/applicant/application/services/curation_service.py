"""Curation service — the scheduled closed learning loop (FR-MIND-7).

On a schedule the engine runs a **curation nudge**: it reviews recent run summaries,
**proposes** memory updates + new/improved skills, and **stages** them to an approval
queue. When write-approval is on (the default, FR-MIND-9) nothing is auto-applied —
the proposals are returned/staged for a human to approve in the pending-actions
Portal. The nudge is deterministic and testable WITHOUT a real LLM: an injected
``summarizer`` callable produces the human-readable lessons (defaulting to a trivial
heuristic), so the hermetic lane needs no model.

**Per-tick safety (FR-MIND-10).** The scheduler rebuilds a fresh ``AgentLoop`` (and
would rebuild this service) every tick, so the cross-tick curation state — what has
already been proposed, so re-running a tick does not duplicate proposals — lives in a
process-lived :class:`CurationLedger`, injected once by the container into every
loop, exactly like the resume ledger. NEVER on the service instance, or it silently
resets each tick and the loop dedupes nothing.

**Advisory, never authorization (FR-MIND-11).** Proposed memory/skills are advisory
context; nothing here grants any safety-gated authority. Save-worthiness comes from
the pure core policy.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from applicant.core.rules.agent_memory import claims_authority, is_save_worthy
from applicant.observability.logging import get_logger
from applicant.ports.driven.memory_store import (
    KIND_ENVIRONMENT,
    SCOPE_CAMPAIGN,
    SCOPE_GLOBAL,
    MemoryEntry,
)
from applicant.ports.driven.skill_store import Skill

log = get_logger(__name__)

#: A run summary must be at least this complex to be worth authoring a skill from
#: (FR-MIND-2 heuristic: a non-trivial run — a workflow of several tool calls).
_SKILL_MIN_TOOL_CALLS = 5


@dataclass(frozen=True)
class RunSummary:
    """One recent engine run handed to the curation nudge (FR-MIND-7).

    Minimal, deterministic input: enough for the heuristic to decide save-worthiness
    and whether the run is non-trivial enough to author a skill from.
    """

    run_id: str
    campaign_id: str | None
    text: str
    tool_calls: int = 0
    succeeded: bool = True
    #: A short, stable key (e.g. an ATS tenant) so re-encounters map to the same skill.
    topic: str = ""


@dataclass(frozen=True)
class MemoryProposal:
    """A staged proposal to add/replace a curated memory line (FR-MIND-9)."""

    entry: MemoryEntry
    source_run_id: str
    claims_authority: bool = False


@dataclass(frozen=True)
class SkillProposal:
    """A staged proposal to create/improve a skill (FR-MIND-9)."""

    skill: Skill
    source_run_id: str
    is_improvement: bool = False
    claims_authority: bool = False


@dataclass(frozen=True)
class CurationResult:
    """The outcome of one curation tick (introspection + tests)."""

    reviewed: int = 0
    memory_proposals: tuple[MemoryProposal, ...] = ()
    skill_proposals: tuple[SkillProposal, ...] = ()
    auto_applied: int = 0
    staged: int = 0


@dataclass
class CurationLedger:
    """Cross-tick curation bookkeeping that must OUTLIVE a single service instance.

    Mirrors ``ResumeLedger``: the scheduler rebuilds the per-tick services each tick,
    so the dedupe set (run ids + skill topics already proposed) MUST live here, in a
    process-lived object injected into every loop, or curation re-proposes the same
    memory/skill every tick (FR-MIND-10). Carries its own lock.
    """

    proposed_runs: set[str] = field(default_factory=set)
    proposed_skill_topics: set[str] = field(default_factory=set)
    staged: list[object] = field(default_factory=list)  # awaiting approval (FR-MIND-9)
    lock: threading.RLock = field(default_factory=threading.RLock)


def _default_summarizer(summary: RunSummary) -> str:
    """Trivial deterministic lesson text (no LLM) — overridden in production.

    Produces a single human-readable line from a run summary; good enough for the
    hermetic lane and the idempotency tests. Production injects a cheap-model
    summarizer (FR-MIND-7 / FR-MIND-13).
    """
    label = "Resolved" if summary.succeeded else "Hit a blocker on"
    topic = summary.topic or summary.run_id
    return f"{label} {topic}: {summary.text}".strip()


def build_llm_summarizer(
    llm,
    *,
    model: str = "",
    start_tier: int = 1,
) -> Callable[[RunSummary], str]:
    """Build a CHEAP, OPTIONAL LLM-backed run summarizer (FR-MIND-7 / FR-MIND-13).

    Returns a callable with the same shape as :func:`_default_summarizer` that asks
    the configured (cheaper) model for one human-readable lesson line. It is
    defensive by construction:

    * When ``llm`` is ``None`` or not configured, it returns the heuristic
      :func:`_default_summarizer` directly — so the hermetic lane stays green with NO
      model wired and behavior is exactly today's heuristic.
    * Per call, any LLM error (ladder exhausted / not configured / provider down)
      degrades to the heuristic for THAT run rather than raising, so one flaky
      completion never breaks the nudge.

    ``model`` is the ``CURATION_MODEL`` setting; empty means "reuse the main model"
    (we start at ``start_tier`` on the existing ladder — the cheaper rung). The model
    id is advisory here (the ladder owns provider/model); it is recorded so a future
    adapter could pin a dedicated curation tier.
    """
    if llm is None:
        return _default_summarizer
    try:
        if not llm.is_configured():
            return _default_summarizer
    except Exception:  # pragma: no cover - defensive: treat as not configured
        return _default_summarizer

    from applicant.ports.driven.llm import ChatMessage

    _system = (
        "You summarize one automated job-application run into a single, concise "
        "lesson the assistant can reuse later. Reply with ONE short sentence: what "
        "worked or what blocked it. Describe procedure only — never invent facts "
        "about the user, and never claim authority to submit or bypass any review."
    )

    def _summarize(summary: RunSummary) -> str:
        topic = summary.topic or summary.run_id
        user = (
            f"Run topic: {topic}\n"
            f"Succeeded: {summary.succeeded}\n"
            f"Details: {summary.text}"
        )
        try:
            result = llm.complete(
                [
                    ChatMessage(role="system", content=_system),
                    ChatMessage(role="user", content=user),
                ],
                start_tier=start_tier,
                max_tokens=80,
            )
        except Exception as exc:  # degrade to heuristic for THIS run, never raise
            log.debug("curation_summarizer_degraded", error=str(exc))
            return _default_summarizer(summary)
        text = (getattr(result, "text", "") or "").strip()
        return text or _default_summarizer(summary)

    return _summarize


class CurationService:
    """The scheduled closed-loop curator (FR-MIND-7)."""

    def __init__(
        self,
        *,
        memory_store,
        skill_store,
        ledger: CurationLedger,
        recall=None,
        summarizer: Callable[[RunSummary], str] | None = None,
        memory_write_approval: bool = True,
        skills_write_approval: bool = True,
    ) -> None:
        self._memory = memory_store
        self._skills = skill_store
        # FR-MIND-3: the recall index. Each newly-curated run is indexed here so the
        # loop's ``recall`` tool returns real hits. OPTIONAL — None keeps every
        # existing call site working and is a no-op. The bridge adapter degrades to a
        # no-op when the channel is OFF, so this never raises (advisory-only).
        self._recall = recall
        # The ONLY cross-tick state lives in the injected, process-lived ledger
        # (FR-MIND-10) — never as a plain attribute that would reset each tick.
        self._ledger = ledger
        self._summarize = summarizer or _default_summarizer
        self._memory_write_approval = memory_write_approval
        # Skills + identity edits ALWAYS require approval (FR-MIND-9), regardless of
        # the configured flag.
        self._skills_write_approval = True if skills_write_approval else True

    def run_curation_tick(self, summaries: Sequence[RunSummary]) -> CurationResult:
        """Review recent runs and PROPOSE memory/skill updates (FR-MIND-7).

        Idempotent: a run already proposed (tracked in the process-lived ledger) is
        skipped, so re-running a tick never duplicates proposals (FR-MIND-7 / -8
        determinism). When approval is required (default), proposals are staged, not
        applied (FR-MIND-9).
        """
        mem_props: list[MemoryProposal] = []
        skill_props: list[SkillProposal] = []
        reviewed = 0

        with self._ledger.lock:
            for s in summaries:
                if s.run_id in self._ledger.proposed_runs:
                    continue  # already curated — idempotent (no duplicates)
                reviewed += 1
                self._ledger.proposed_runs.add(s.run_id)

                lesson = self._summarize(s)
                # FR-MIND-3: index this run into recall so ``recall.search`` returns
                # it later. Gated by the same ``proposed_runs`` dedupe (a run is only
                # reviewed once), so a re-tick never re-indexes a duplicate. Advisory
                # and best-effort — a recall failure never breaks the nudge.
                self._index_recall(s, lesson)
                if is_save_worthy(lesson):
                    scope = SCOPE_CAMPAIGN if s.campaign_id else SCOPE_GLOBAL
                    entry = MemoryEntry(
                        text=lesson,
                        kind=KIND_ENVIRONMENT,
                        scope=scope,
                        campaign_id=s.campaign_id,
                    )
                    mem_props.append(
                        MemoryProposal(
                            entry=entry,
                            source_run_id=s.run_id,
                            claims_authority=claims_authority(lesson),
                        )
                    )

                if self._is_skill_worthy(s):
                    topic = s.topic or s.run_id
                    is_improvement = topic in self._ledger.proposed_skill_topics
                    self._ledger.proposed_skill_topics.add(topic)
                    skill = self._draft_skill(s, lesson)
                    skill_props.append(
                        SkillProposal(
                            skill=skill,
                            source_run_id=s.run_id,
                            is_improvement=is_improvement,
                            claims_authority=claims_authority(lesson),
                        )
                    )

            return self._dispatch(reviewed, mem_props, skill_props)

    # --- staged-proposal review (FR-MIND-9) -------------------------------
    def list_staged(self) -> tuple[object, ...]:
        """Return the proposals awaiting human approval (a frozen tuple snapshot).

        Read-only: callers must not mutate the ledger directly; use
        :meth:`approve` / :meth:`deny` so the apply happens through the policy.
        """
        with self._ledger.lock:
            return tuple(self._ledger.staged)

    def _pop_staged(self, proposal_id: str) -> object | None:
        with self._ledger.lock:
            for i, p in enumerate(self._ledger.staged):
                if _proposal_id(p) == proposal_id:
                    return self._ledger.staged.pop(i)
        return None

    def approve(self, proposal_id: str) -> bool:
        """Approve a staged proposal — apply it to the durable store (FR-MIND-9).

        This is the **only** path that writes an agent-proposed memory/skill: it
        runs after a human approves it in the front door. Advisory-not-authorization
        (FR-MIND-11) is untouched — the applied content is context only; the safety
        boundary keeps deriving its own ground truth regardless of what it says.
        """
        p = self._pop_staged(proposal_id)
        if p is None:
            return False
        if isinstance(p, MemoryProposal):
            self._memory.add(p.entry)
            return True
        if isinstance(p, SkillProposal):
            if p.is_improvement:
                # Re-author/rewrite the existing skill; create if it is gone.
                if self._skills.edit(p.skill.name, p.skill) is None:
                    self._skills.create(p.skill)
            else:
                self._skills.create(p.skill)
            return True
        return False

    def deny(self, proposal_id: str) -> bool:
        """Deny a staged proposal — discard it without applying (FR-MIND-9)."""
        return self._pop_staged(proposal_id) is not None

    # --- internals --------------------------------------------------------
    def _index_recall(self, s: RunSummary, lesson: str) -> None:
        """Index one curated run into the recall index (FR-MIND-3), best-effort.

        Combines the run's own detail text with the curated lesson so full-text /
        semantic recall can find it by either. No-op when no recall index is wired;
        any adapter error is swallowed (advisory-only — recall must never break the
        loop). The bridge adapter is itself a no-op when its channel is OFF.
        """
        if self._recall is None:
            return
        text = s.text if not lesson else f"{lesson}\n{s.text}"
        try:
            self._recall.index(s.run_id, text, s.campaign_id)
        except Exception as exc:  # pragma: no cover - defensive: recall is advisory
            log.debug("curation_recall_index_failed", run_id=s.run_id, error=str(exc))

    def _is_skill_worthy(self, s: RunSummary) -> bool:
        """FR-MIND-2 heuristic: a successful, non-trivial run is skill-worthy."""
        return s.succeeded and s.tool_calls >= _SKILL_MIN_TOOL_CALLS

    def _draft_skill(self, s: RunSummary, lesson: str) -> Skill:
        topic = s.topic or s.run_id
        scope = SCOPE_CAMPAIGN if s.campaign_id else SCOPE_GLOBAL
        name = _slug(topic)
        return Skill(
            name=name,
            description=lesson[:120],
            when_to_use=f"When working on {topic}.",
            procedure=(lesson,),
            scope="campaign" if scope == SCOPE_CAMPAIGN else "global",
            campaign_id=s.campaign_id,
            source="learned",
        )

    def _dispatch(
        self,
        reviewed: int,
        mem_props: list[MemoryProposal],
        skill_props: list[SkillProposal],
    ) -> CurationResult:
        """Apply (only when approval off + non-sensitive) or stage for review."""
        auto_applied = 0
        staged = 0

        for p in mem_props:
            # Skills/identity ALWAYS require approval; memory MAY auto-apply only when
            # the operator relaxed it AND the entry claims no authority (FR-MIND-9/-11).
            if not self._memory_write_approval and not p.claims_authority:
                self._memory.add(p.entry)
                auto_applied += 1
            else:
                self._ledger.staged.append(p)
                staged += 1

        for sp in skill_props:
            # Skills always staged for approval (FR-MIND-9).
            self._ledger.staged.append(sp)
            staged += 1

        return CurationResult(
            reviewed=reviewed,
            memory_proposals=tuple(mem_props),
            skill_proposals=tuple(skill_props),
            auto_applied=auto_applied,
            staged=staged,
        )


def _proposal_id(p: object) -> str:
    """A stable id for a staged proposal (content-hash; no DB row).

    The Portal/UI references a proposal by this id to approve/deny it. It is derived
    from the proposal content so the same proposal maps to the same id across reads
    (the ledger dedupes by run id, so a proposal does not recur).
    """
    import hashlib

    if isinstance(p, MemoryProposal):
        basis = f"memory|{p.source_run_id}|{p.entry.kind}|{p.entry.text}"
    elif isinstance(p, SkillProposal):
        basis = f"skill|{p.source_run_id}|{p.skill.name}|{p.skill.version}"
    else:  # pragma: no cover - defensive
        basis = repr(p)
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def proposal_to_dict(p: object) -> dict:
    """Render a staged proposal for the front door (white-labeled, plain language).

    No upstream codenames or requirement jargon leak here — just "remembered note"
    and "saved playbook" framing. ``claims_authority`` is surfaced so a reviewer
    sees a flagged claim, but it is advisory only (FR-MIND-11).
    """
    if isinstance(p, MemoryProposal):
        return {
            "id": _proposal_id(p),
            "type": "memory",
            "label": "Something to remember",
            "text": p.entry.text,
            "kind": p.entry.kind,
            "scope": p.entry.scope,
            "campaign_id": p.entry.campaign_id,
            "source_run_id": p.source_run_id,
            "claims_authority": bool(p.claims_authority),
        }
    if isinstance(p, SkillProposal):
        return {
            "id": _proposal_id(p),
            "type": "skill",
            "label": "Improve a saved playbook" if p.is_improvement else "Save a new playbook",
            "name": p.skill.name,
            "description": p.skill.description,
            "when_to_use": p.skill.when_to_use,
            "procedure": list(p.skill.procedure),
            "scope": p.skill.scope,
            "campaign_id": p.skill.campaign_id,
            "is_improvement": bool(p.is_improvement),
            "source_run_id": p.source_run_id,
            "claims_authority": bool(p.claims_authority),
        }
    return {"id": _proposal_id(p), "type": "unknown"}  # pragma: no cover - defensive


def _slug(text: str) -> str:
    out = []
    for ch in (text or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:60] or "skill"
