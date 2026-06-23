"""ChatService — the assistant chatbot (FR-CHAT-1, FR-FB-2/3).

A real conversational surface that:

* assists the user in providing input (a natural-language reply, LLM-backed when a
  model is configured, degrading gracefully to a deterministic reply offline);
* identifies gaps in the campaign's attribute cloud / criteria (which core
  attributes are missing, whether criteria are still empty) — FR-CHAT-1;
* proposes attribute/criteria updates parsed from the message, **routed through the
  confirmation gate** (FR-FB-3): integral changes are surfaced as proposals that
  require explicit confirmation and are never auto-committed; non-integral changes
  may auto-apply.

The chatbot itself NEVER commits an integral change on its own. It is composed
from the LLM port + the attribute/criteria services so it reuses the same gates as
the rest of the system (no bypass).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import THROUGHPUT_HARD_CAP, clamp_throughput
from applicant.core.ids import CampaignId
from applicant.core.rules.confirmation_gate import requires_confirmation
from applicant.core.rules.sensitive_fields import is_sensitive_field
from applicant.ports.driven.llm import ChatMessage

#: Core needs a campaign must cover before it can apply confidently (FR-CHAT-1 gaps).
#: Each is (display label, accepted attribute keys). Onboarding stores CANONICAL keys
#: (``full_name`` / ``email`` / ``title`` / ``phone``) while the chat historically
#: used spaced display labels; a need is a gap only when NONE of its synonyms is
#: present, so a fully-onboarded profile is never falsely reported as "still missing".
_CORE_NEEDS: tuple[tuple[str, frozenset[str]], ...] = (
    ("first name", frozenset(
        {"first name", "name", "full name", "full_name", "legal name",
         "full_legal_name", "preferred_name", "preferred name"})),
    ("last name", frozenset(
        {"last name", "name", "full name", "full_name", "legal name", "full_legal_name"})),
    ("email address", frozenset({"email address", "email"})),
    ("phone", frozenset({"phone", "phone number", "phone_number"})),
    ("current job title", frozenset(
        {"current job title", "title", "titles", "job title", "job_title", "current_title"})),
)
#: Back-compat: the bare display labels (used for the user-facing gap list + parsing).
CORE_ATTRIBUTES: tuple[str, ...] = tuple(label for label, _ in _CORE_NEEDS)

#: "my <attr> is <value>" / "<attr>: <value>" statement parser (FR-FB-2 input).
_STATEMENT = re.compile(
    r"^\s*(?:my\s+)?(?P<name>[a-z][a-z0-9 _-]{1,48}?)\s+(?:is|are|=|:)\s+(?P<value>.+?)\s*$",
    re.IGNORECASE,
)

#: A message starting with one of these leads (or ending in "?") is a QUESTION, not an
#: attribute statement. Without this guard "What is my salary range?" parsed as setting
#: an attribute named "what" and was silently auto-applied, polluting the attribute
#: cloud with garbage derived from the user's own questions.
_QUESTION_LEAD = re.compile(
    r"^(?:what|whats|who|whom|whose|which|when|where|why|how|is|are|am|was|were|"
    r"do|does|did|can|could|will|would|should|shall|may|might)\b",
    re.IGNORECASE,
)

#: Attribute names treated as integral (a change needs confirmation, FR-FB-3).
_INTEGRAL_NAMES = frozenset(
    {"first name", "last name", "legal name", "email address", "phone"}
)

# --- loop-control intent parsing (FR-AGENT-1/2, FR-CRIT) -------------------
# A small, EXPLICIT set of directives that steer the autonomous loop. The chatbot
# only routes a matched intent to the existing run-control / criteria services; it
# never free-form mutates arbitrary config (those services own the gates + clamps).

#: "pause" / "stop applying" / "hold off" — pause automated work (FR-AGENT-2).
_PAUSE = re.compile(
    r"\b(?:pause|stop|halt|hold off|hold on|suspend|freeze)\b"
    r"(?!.*\b(?:resume|unpause|continue|restart)\b)",
    re.IGNORECASE,
)
#: "resume" / "unpause" / "start again" / "keep going" — resume automated work.
_RESUME = re.compile(
    r"\b(?:resume|unpause|un-?pause|continue|carry on|keep going|start (?:again|up)|"
    r"get going|pick (?:it |things )?back up)\b",
    re.IGNORECASE,
)
#: "apply to N a day" / "set throughput to N" / "do N per day" — daily target (FR-AGENT-1).
_THROUGHPUT = re.compile(
    r"(?:throughput|daily (?:target|cap|limit|budget|throughput)|"
    r"(?:apply|application|applications)|per day|a day|each day|/day)",
    re.IGNORECASE,
)
#: A bare integer in the message (used to read off the requested throughput number).
_INT = re.compile(r"(?<![\w.])(\d{1,4})(?![\w.])")
#: "focus on remote roles" / "remote only" — refocus to remote work (criteria, FR-CRIT).
_REMOTE = re.compile(r"\bremote(?:\s+(?:only|roles|jobs|work|positions))?\b", re.IGNORECASE)
#: "raise the salary floor to N" / "minimum salary N" — set the salary floor (integral).
_SALARY = re.compile(
    r"(?:salary|pay|comp(?:ensation)?|base)\b.*?(?:floor|min(?:imum)?|at least|above|over|to)?"
    r"\s*\$?\s*(\d[\d,]{2,})(?:\s*k\b)?",
    re.IGNORECASE,
)
#: A trailing "k" on the salary number multiplies by 1000 ("120k" -> 120000).
_SALARY_K = re.compile(r"(\d[\d,]*)\s*k\b", re.IGNORECASE)
#: Verbs that mark a refocus/steer directive (so plain mention of "remote" in a
#: question is not treated as a criteria edit).
_REFOCUS_LEAD = re.compile(
    r"\b(?:focus|prioriti[sz]e|refocus|narrow|only|restrict|limit|target|search for|"
    r"look for|switch to|raise|lower|set|bump|increase|decrease|require)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ProposedChange:
    """A change the chatbot proposes; integral ones are confirmation-gated (FR-FB-3)."""

    kind: str  # "attribute" | "criteria"
    name: str
    value: str
    is_integral: bool
    is_sensitive: bool
    requires_confirmation: bool
    applied: bool = False

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "value": self.value,
            "is_integral": self.is_integral,
            "is_sensitive": self.is_sensitive,
            "requires_confirmation": self.requires_confirmation,
            "applied": self.applied,
        }


@dataclass(frozen=True)
class ControlAction:
    """A loop-control action the user steered via chat (FR-AGENT-1/2, FR-CRIT).

    Mirrors :class:`ProposedChange`'s confirmation contract (FR-FB-3): a non-integral
    control (pause/resume, throughput within range) is applied directly and reported
    with ``applied=True``; an integral one (a criteria change that shifts campaign
    scope) is surfaced as a proposal with ``requires_confirmation=True`` and is NOT
    committed until the user confirms it. ``ok=False`` marks an action the agent could
    not take (out-of-range value, or the control isn't wired) so the reply stays truthful.
    """

    kind: str  # "pause" | "resume" | "throughput" | "criteria"
    applied: bool = False
    requires_confirmation: bool = False
    ok: bool = True
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "applied": self.applied,
            "requires_confirmation": self.requires_confirmation,
            "ok": self.ok,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class ChatTurnResult:
    """The result of one conversational turn."""

    message: str
    gaps: list[str] = field(default_factory=list)
    proposed_changes: list[ProposedChange] = field(default_factory=list)
    control_actions: list[ControlAction] = field(default_factory=list)


class ChatService:
    """``ChatPort`` adapter backed by the LLM + attribute/criteria services."""

    def __init__(
        self,
        *,
        attribute_service,
        criteria_service=None,
        llm=None,
        learning=None,
        storage=None,
        workspace=None,
        agent_memory=None,
        run_control=None,
    ) -> None:
        self._attrs = attribute_service
        self._criteria = criteria_service
        self._llm = llm
        # Optional LearningService so a chat taste statement folds a cheap signal into
        # the per-campaign learning model (FR-LEARN-3: every input feeds learning).
        self._learning = learning
        self._storage = storage
        # Stage 2.5: optional WorkspacePort. When the engine->workspace callback
        # channel is configured (``available()``), the assistant injects a short,
        # owner-scoped "upcoming interviews" context block so its answers/material
        # guidance are interview-aware. Degrades silently when off/empty.
        self._workspace = workspace
        # FR-MIND-5: optional agent-memory trio (``.memory`` / ``.skills`` / ``.recall``).
        # When wired, the reasoning prompt gains a BOUNDED "what the assistant remembers"
        # block (curated-memory snapshot, read fresh per call — FR-MIND-10) plus a few
        # relevant saved-playbook hints. ``None`` (the default) is byte-identical to the
        # prior behavior, so every existing call site keeps working unchanged. The
        # injected content is ADVISORY context only — it never authorizes anything
        # (FR-MIND-11); the confirmation/safety gates derive their own ground truth.
        self._agent_memory = agent_memory
        # Run-control seam (FR-AGENT-1/2): the existing run-control service the chat
        # routes loop-steering intents to (pause/resume + daily throughput). The engine
        # OWNS the logic + the hard cap; the chat only matches an explicit intent and
        # calls the existing gated operation. Optional/defaulted: when absent the chat
        # politely declines a control request rather than crashing or fabricating. The
        # expected surface (duck-typed so a read-only status double still works for the
        # rest of the chat) is:
        #   - ``set_active(campaign_id, active: bool)`` -> pause/resume
        #   - ``configure_run(campaign_id, throughput_target=int)`` -> daily target
        self._run_control = run_control

    # --- gap finding (FR-CHAT-1) ------------------------------------------
    def identify_gaps(self, campaign_id: CampaignId) -> list[str]:
        """Which core attributes / criteria are still missing for the campaign."""
        have = {a.name.lower() for a in self._attrs.list_attributes(campaign_id)}
        # A core need is satisfied by ANY of its synonyms (canonical key or label),
        # so a profile stored as full_name/email/title isn't falsely flagged.
        gaps = [label for label, synonyms in _CORE_NEEDS if not (synonyms & have)]
        if self._criteria is not None:
            crit = self._criteria.get_criteria(campaign_id)
            if not crit.titles and not crit.human_readable:
                gaps.append("target roles / search criteria")
        return gaps

    # --- proposal parsing (FR-FB-2/3) -------------------------------------
    def _parse_proposal(self, message: str) -> ProposedChange | None:
        # A question is never an attribute statement — guard before the loose "X is Y"
        # match so "What is my salary range?" is not committed as an attribute "what".
        text = message.strip()
        if text.endswith("?") or _QUESTION_LEAD.match(text):
            return None
        m = _STATEMENT.match(message)
        if m is None:
            return None
        name = m.group("name").strip().lower()
        value = m.group("value").strip().rstrip(".")
        if not name or not value:
            return None
        is_sensitive = is_sensitive_field(name)
        is_integral = name in _INTEGRAL_NAMES or is_sensitive
        return ProposedChange(
            kind="attribute",
            name=name,
            value=value,
            is_integral=is_integral,
            is_sensitive=is_sensitive,
            requires_confirmation=requires_confirmation(is_integral=is_integral),
        )

    def _maybe_autoapply(
        self, campaign_id: CampaignId, proposal: ProposedChange
    ) -> ProposedChange:
        """Auto-apply a non-integral, non-sensitive proposal (FR-LEARN-4 / FR-FB-3)."""
        if proposal.requires_confirmation or proposal.is_sensitive:
            return proposal  # leave for explicit confirmation
        self._attrs.ai_add_attribute(campaign_id, proposal.name, proposal.value)
        return ProposedChange(
            kind=proposal.kind,
            name=proposal.name,
            value=proposal.value,
            is_integral=proposal.is_integral,
            is_sensitive=proposal.is_sensitive,
            requires_confirmation=proposal.requires_confirmation,
            applied=True,
        )

    # --- LLM reply (FR-CHAT-1; degrade gracefully offline) ----------------
    def _reply_text(
        self, campaign_id: CampaignId, message: str, gaps: list[str]
    ) -> str:
        deterministic = self._deterministic_reply(gaps)
        if self._llm is None or not getattr(self._llm, "is_configured", lambda: False)():
            return deterministic
        try:
            system = (
                "You are the Applicant assistant. You help the user with their job "
                "search and their application profile. Answer using the candidate's "
                "saved profile and search criteria provided below — do NOT ask the user "
                "for details that are already present there. Be concise. Never claim to "
                "have changed any integral detail without confirmation."
            )
            prompt = message
            profile_ctx = self._profile_context(campaign_id)
            if profile_ctx:
                prompt += f"\n\n{profile_ctx}"
            if gaps:
                prompt += f"\n\n(Known missing details: {', '.join(gaps)}.)"
            interview_ctx = self._interview_context()
            if interview_ctx:
                prompt += f"\n\n{interview_ctx}"
            # FR-MIND-5: a bounded curated-memory + relevant-skills block, read fresh
            # per call (never cached — FR-MIND-10), advisory only (FR-MIND-11).
            memory_ctx = self._memory_context(campaign_id, message)
            if memory_ctx:
                prompt += f"\n\n{memory_ctx}"
            result = self._llm.complete(
                [ChatMessage(role="system", content=system), ChatMessage(role="user", content=prompt)],
                max_tokens=256,
            )
            text = (result.text or "").strip()
            return text or deterministic
        except Exception:
            # Any LLM failure degrades to the deterministic reply (offline-safe).
            return deterministic

    # --- saved-profile context (FR-CHAT-1) --------------------------------
    def _profile_context(self, campaign_id: CampaignId) -> str:
        """A compact block of the candidate's SAVED profile (criteria + attributes).

        Injected into the LLM prompt so the assistant answers from what is already on
        file instead of asking the user for details they already provided — the
        front-door chat otherwise saw only the *missing* gaps and re-requested stored
        data like target titles and salary floor. Bounded to keep the prompt lean;
        degrades to "" when nothing is on file (offline-safe, like interview context).
        """
        lines: list[str] = []
        if self._criteria is not None:
            try:
                crit = self._criteria.get_criteria(campaign_id)
            except Exception:
                crit = None
            if crit is not None:
                cbits: list[str] = []
                if crit.titles:
                    cbits.append("target titles: " + ", ".join(crit.titles))
                if getattr(crit, "work_modes", ()):
                    cbits.append("work modes: " + ", ".join(crit.work_modes))
                if getattr(crit, "locations", ()):
                    cbits.append("locations: " + ", ".join(crit.locations))
                if getattr(crit, "salary_floor", None):
                    cbits.append(f"salary floor: {crit.salary_floor}")
                if crit.keywords:
                    cbits.append("skills/keywords: " + ", ".join(crit.keywords))
                if crit.human_readable:
                    cbits.append("in their words: " + crit.human_readable)
                if cbits:
                    lines.append("Search criteria — " + "; ".join(cbits))
        try:
            attrs = self._attrs.list_attributes(campaign_id)
        except Exception:
            attrs = []
        shown = 0
        for a in attrs:
            name = getattr(a, "name", "")
            value = getattr(a, "value", "")
            if not name or value in (None, ""):
                continue
            # NEVER send EEO/sensitive attributes (race, gender, veteran/disability,
            # date of birth, …) to the external LLM (FR-ATTR-6, NFR-PRIV-1). Mirror the
            # material path's guard and check BOTH the stored flag and the field-name
            # classifier (defense in depth, in case the flag was never set on the row).
            if getattr(a, "is_sensitive", False) or is_sensitive_field(name):
                continue
            val = str(value)
            if len(val) > 160:
                val = val[:157] + "…"
            lines.append(f"- {name}: {val}")
            shown += 1
            if shown >= 50:
                lines.append("- … (more attributes on file)")
                break
        if not lines:
            return ""
        return (
            "The candidate's saved profile (answer from this; do NOT ask for details "
            "already present here):\n" + "\n".join(lines)
        )

    # --- upcoming-interview context (Stage 2.5; degrade silently) ---------
    def _interview_context(self, owner: str | None = None) -> str:
        """A short, owner-scoped "upcoming interviews" block for the LLM prompt.

        Pulls auto-detected interviews from the front-door workspace via the
        callback channel (``container.workspace.calendar_interviews``) ONLY when
        the channel is configured (``available()``). Any failure / empty result
        degrades silently to "" so the chat turn is never broken by a flaky or
        absent workspace. Bounded to a handful of lines to keep the prompt lean.
        """
        ws = self._workspace
        if ws is None:
            return ""
        try:
            if not ws.available():
                return ""
            payload = ws.calendar_interviews(owner=owner)
        except Exception:
            return ""
        interviews = (payload or {}).get("interviews") or []
        if not interviews:
            return ""
        lines: list[str] = []
        for iv in interviews[:5]:
            title = (iv.get("title") or "").strip() or "Interview"
            when = (iv.get("start") or "").strip()
            company = (iv.get("detected_company") or "").strip()
            bits = [title]
            if company:
                bits.append(f"({company})")
            if when:
                bits.append(f"— {when}")
            lines.append("- " + " ".join(bits))
        if not lines:
            return ""
        return (
            "Upcoming interviews the candidate has scheduled (use to make "
            "answers/materials interview-aware; do not invent details):\n"
            + "\n".join(lines)
        )

    # --- curated-memory + skills context (FR-MIND-5; advisory only) -------
    def _memory_context(self, campaign_id: CampaignId, message: str) -> str:
        """A BOUNDED "what the assistant remembers" + saved-playbook block (FR-MIND-5).

        Read fresh from the agent-memory trio on every call (never cached on the
        instance — FR-MIND-10): a curated-memory snapshot (already clipped to the
        store's char budget) plus a few relevant saved-playbook hints (L0 metadata,
        cheap — FR-MIND-2/-13). Degrades silently to "" when no ``agent_memory`` is
        wired (byte-identical to the prior behavior) or nothing is on file.

        Advisory only (FR-MIND-11): this is context the model MAY use; it confers no
        authority. A playbook that *claims* submit/account/CAPTCHA authority is flagged
        and dropped here so it can never read as an instruction the assistant must obey.
        """
        am = self._agent_memory
        if am is None:
            return ""
        from applicant.core.rules.agent_memory import claims_authority

        lines: list[str] = []
        # (a) curated memory snapshot — bounded by the store, read per call.
        try:
            snap = am.memory.snapshot(campaign_id=str(campaign_id))
        except Exception:
            snap = None
        if snap is not None:
            mem_lines: list[str] = []
            for e in (tuple(snap.environment) + tuple(snap.user))[:12]:
                txt = getattr(e, "text", "")
                if not txt or claims_authority(txt):
                    continue  # advisory-only: never surface an authority claim as fact
                mem_lines.append(f"- {txt}")
            if mem_lines:
                lines.append("What you remember (background only):")
                lines.extend(mem_lines)
        # (b) a few relevant saved playbooks (L0 metadata — cheap, no bodies).
        try:
            metas = am.skills.list_skills(campaign_id=str(campaign_id))
        except Exception:
            metas = ()
        if metas:
            q = {w for w in (message or "").lower().split() if len(w) > 3}
            scored = []
            for m in metas:
                hay = f"{getattr(m, 'description', '')} {getattr(m, 'when_to_use', '')}".lower()
                if claims_authority(hay):
                    continue  # advisory-only: drop a playbook that claims authority
                overlap = len(q & set(hay.split())) if q else 0
                scored.append((overlap, m))
            scored.sort(key=lambda t: t[0], reverse=True)
            skill_lines = [
                f"- {getattr(m, 'name', '')}: {getattr(m, 'when_to_use', '') or getattr(m, 'description', '')}"
                for _, m in scored[:3]
            ]
            skill_lines = [s for s in skill_lines if s.strip(" -:")]
            if skill_lines:
                lines.append("Saved playbooks you may consult (advice only):")
                lines.extend(skill_lines)
        if not lines:
            return ""
        return "\n".join(lines)

    @staticmethod
    def _deterministic_reply(gaps: list[str]) -> str:
        if gaps:
            return (
                "Thanks. I still need a few details to apply confidently: "
                + ", ".join(gaps)
                + ". I will not change anything integral without your confirmation."
            )
        return (
            "Got it. Anything I propose that is integral will be confirmed before it "
            "commits."
        )

    # --- conversational turn (FR-CHAT-1) ----------------------------------
    def converse(self, campaign_id: CampaignId, message: str) -> ChatTurnResult:
        gaps = self.identify_gaps(campaign_id)
        proposals: list[ProposedChange] = []
        # FR-AGENT-1/2, FR-CRIT: route loop-steering directives (pause/resume, daily
        # throughput, criteria refocus) to the existing run-control / criteria services.
        # When the turn IS a control directive, the agent reports back in the first person
        # what it actually did (or could not do), and we skip the attribute-statement
        # parser so e.g. "pause" is never mis-read as setting an attribute.
        controls, control_reply = self._handle_controls(campaign_id, message)
        if not controls:
            parsed = self._parse_proposal(message)
            if parsed is not None:
                proposals.append(self._maybe_autoapply(campaign_id, parsed))
        reply = control_reply or self._reply_text(campaign_id, message, gaps)
        # FR-LEARN-3: fold a cheap chat taste signal so every input feeds learning.
        self._fold_chat_taste(campaign_id, message)
        return ChatTurnResult(
            message=reply,
            gaps=gaps,
            proposed_changes=proposals,
            control_actions=controls,
        )

    # --- loop-control routing (FR-AGENT-1/2, FR-CRIT, FR-FB-3) -------------
    def _handle_controls(
        self, campaign_id: CampaignId, message: str
    ) -> tuple[list[ControlAction], str]:
        """Detect + apply loop-control directives; return (actions, first-person reply).

        Only an EXPLICIT matched intent is acted on (no free-form config mutation). The
        engine owns the logic and the gates: pause/resume + throughput go through the
        run-control service (throughput clamped to the hard cap, FR-AGENT-1); a criteria
        refocus goes through ``criteria_service.edit_criteria`` so an integral scope
        change still requires the user's confirmation (FR-FB-3). When a needed control is
        not wired, the agent says so plainly instead of pretending it acted.
        """
        text = message.strip()
        is_question = text.endswith("?") or bool(_QUESTION_LEAD.match(text))
        actions: list[ControlAction] = []
        replies: list[str] = []

        # --- pause / resume (FR-AGENT-2) -----------------------------------
        # A question ("can you pause?") is informational, not an imperative.
        if not is_question:
            if _RESUME.search(text):
                act, line = self._do_pause_resume(campaign_id, resume=True)
                actions.append(act)
                replies.append(line)
            elif _PAUSE.search(text):
                act, line = self._do_pause_resume(campaign_id, resume=False)
                actions.append(act)
                replies.append(line)

        # --- daily throughput (FR-AGENT-1) ---------------------------------
        if not is_question and _THROUGHPUT.search(text):
            n = self._read_throughput_number(text)
            if n is not None:
                act, line = self._do_throughput(campaign_id, n)
                actions.append(act)
                replies.append(line)

        # --- criteria refocus (FR-CRIT, gated by FR-FB-3) ------------------
        if _REFOCUS_LEAD.search(text):
            for act, line in self._do_criteria_refocus(campaign_id, text):
                actions.append(act)
                replies.append(line)

        return actions, " ".join(replies).strip()

    def _run_control_target(self):
        """The object that performs run-control writes, or ``None`` if unavailable.

        Prefers the explicitly-injected ``run_control`` service; degrades to ``None``
        when it (or the specific method) is missing so the caller declines gracefully.
        """
        return self._run_control

    def _do_pause_resume(
        self, campaign_id: CampaignId, *, resume: bool
    ) -> tuple[ControlAction, str]:
        target = self._run_control_target()
        verb = "resume" if resume else "pause"
        set_active = getattr(target, "set_active", None) if target is not None else None
        if set_active is None:
            return (
                ControlAction(kind=verb, ok=False, applied=False),
                f"I can't {verb} my automated work from here right now.",
            )
        try:
            set_active(campaign_id, resume)
        except Exception:
            return (
                ControlAction(kind=verb, ok=False, applied=False),
                f"I wasn't able to {verb} my automated work just now.",
            )
        if resume:
            line = "Okay, I've resumed. I'll start picking up new applications again."
        else:
            line = (
                "Okay, I've paused. I'll hold off on starting new applications until you "
                "tell me to resume."
            )
        return ControlAction(kind=verb, applied=True), line

    @staticmethod
    def _read_throughput_number(text: str) -> int | None:
        m = _INT.search(text)
        if m is None:
            return None
        try:
            return int(m.group(1))
        except (TypeError, ValueError):  # pragma: no cover - regex guarantees digits
            return None

    def _do_throughput(
        self, campaign_id: CampaignId, requested: int
    ) -> tuple[ControlAction, str]:
        # Reject an out-of-range request with a clear message; never silently exceed the
        # hard cap (FR-AGENT-1). 0/negative is a floor violation; above the cap is rejected.
        if requested < 1 or requested > THROUGHPUT_HARD_CAP:
            return (
                ControlAction(
                    kind="throughput",
                    ok=False,
                    applied=False,
                    detail={"requested": requested, "hard_cap": THROUGHPUT_HARD_CAP},
                ),
                (
                    f"I can apply to between 1 and {THROUGHPUT_HARD_CAP} roles a day, so "
                    f"{requested} a day is outside what I can do. Pick a number in that "
                    "range and I'll set it."
                ),
            )
        target = self._run_control_target()
        configure = getattr(target, "configure_run", None) if target is not None else None
        if configure is None:
            return (
                ControlAction(
                    kind="throughput", ok=False, applied=False,
                    detail={"requested": requested},
                ),
                "I can't change my daily application target from here right now.",
            )
        applied_value = clamp_throughput(requested)
        try:
            configure(campaign_id, throughput_target=applied_value)
        except Exception:
            return (
                ControlAction(
                    kind="throughput", ok=False, applied=False,
                    detail={"requested": requested},
                ),
                "I wasn't able to change my daily application target just now.",
            )
        return (
            ControlAction(
                kind="throughput", applied=True,
                detail={"throughput_target": applied_value},
            ),
            (
                f"Done. I'll aim for up to {applied_value} applications a day from here on."
            ),
        )

    def _do_criteria_refocus(
        self, campaign_id: CampaignId, text: str
    ) -> list[tuple[ControlAction, str]]:
        """Refocus the search via the existing criteria edit path (FR-CRIT, FR-FB-3).

        Returns one (action, reply) per matched facet. A non-integral facet (work mode:
        remote) applies directly; an integral facet (salary floor — campaign scope) is
        surfaced as a confirmation-gated PROPOSAL and is NOT committed here. The criteria
        service owns the gate, so the chat never bypasses it.
        """
        out: list[tuple[ControlAction, str]] = []
        if self._criteria is None:
            return out

        # work mode: remote (non-integral -> applies directly)
        if _REMOTE.search(text):
            try:
                self._criteria.edit_criteria(
                    campaign_id, changes={"work_modes": ["remote"]}
                )
                out.append((
                    ControlAction(
                        kind="criteria", applied=True,
                        detail={"work_modes": ["remote"]},
                    ),
                    "I've refocused the search on remote roles.",
                ))
            except Exception:
                out.append((
                    ControlAction(kind="criteria", ok=False, applied=False),
                    "I couldn't refocus the search on remote roles just now.",
                ))

        # salary floor (integral -> needs confirmation, FR-FB-3)
        floor = self._read_salary_floor(text)
        if floor is not None:
            out.append((
                ControlAction(
                    kind="criteria",
                    applied=False,
                    requires_confirmation=True,
                    detail={"salary_floor": floor},
                ),
                (
                    f"Setting the salary floor to {floor} changes the scope of the search, "
                    "so I'll hold off until you confirm. Want me to apply it?"
                ),
            ))
        return out

    @staticmethod
    def _read_salary_floor(text: str) -> int | None:
        km = _SALARY_K.search(text)
        if km is not None and re.search(r"salary|pay|comp|base", text, re.IGNORECASE):
            try:
                return int(km.group(1).replace(",", "")) * 1000
            except (TypeError, ValueError):  # pragma: no cover
                return None
        m = _SALARY.search(text)
        if m is None:
            return None
        try:
            return int(m.group(1).replace(",", ""))
        except (TypeError, ValueError):  # pragma: no cover
            return None

    def confirm_criteria_refocus(
        self, campaign_id: CampaignId, *, changes: dict
    ):
        """Commit a confirmation-gated criteria refocus the user approved (FR-FB-3).

        Routes to ``criteria_service.edit_criteria`` with ``confirm=True`` so the
        integral-change gate is satisfied — the chat never sets ``confirm`` on its own;
        the user's explicit confirmation drives it, exactly like ``confirm_change``.
        """
        if self._criteria is None:
            raise RuntimeError("criteria control is not available")
        return self._criteria.edit_criteria(campaign_id, changes=changes, confirm=True)

    # --- chat taste folding (FR-LEARN-3) ----------------------------------
    def _fold_chat_taste(self, campaign_id: CampaignId, message: str) -> None:
        """Fold a cheap, local taste signal from the chat message (best-effort)."""
        if self._learning is None:
            return
        features = {
            f"chat:{tok}": tok
            for tok in message.lower().split()
            if len(tok) > 3
        }
        if not features:
            return
        try:
            atomic = getattr(self._learning, "fold_decision_atomic", None)
            if atomic is not None:
                atomic(campaign_id, approved=True, features=features)
            else:  # pragma: no cover - all wired learning services expose the atomic API
                model = self._learning.load_model(campaign_id)
                model = self._learning.record_decision(
                    model, approved=True, features=features
                )
                self._learning.persist_model(model)
        except Exception:  # pragma: no cover - learning must never break the chat turn
            pass

    # --- confirmation commit (FR-FB-3) ------------------------------------
    def confirm_change(
        self, campaign_id: CampaignId, name: str, value: str
    ) -> Attribute:
        """Commit an integral change the user has explicitly confirmed (FR-FB-3)."""
        is_integral = name.lower() in _INTEGRAL_NAMES or is_sensitive_field(name)
        return self._attrs.upsert(
            campaign_id,
            name,
            value,
            is_integral=is_integral,
            confirm=True,
        )
