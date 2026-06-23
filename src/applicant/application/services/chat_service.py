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
#: "hybrid" — partly-remote work mode (criteria, FR-CRIT).
_HYBRID = re.compile(r"\bhybrid\b", re.IGNORECASE)
#: "on-site" / "onsite" / "in office" / "in-person" — on-site work mode (criteria).
_ONSITE = re.compile(r"\b(?:on[-\s]?site|in[-\s]?office|in[-\s]?person)\b", re.IGNORECASE)
#: "raise the salary floor to N" / "minimum salary N" — set the salary floor (integral).
_SALARY = re.compile(
    r"(?:salary|pay|comp(?:ensation)?|base)\b.*?(?:floor|min(?:imum)?|at least|above|over|to)?"
    r"\s*\$?\s*(\d[\d,]{2,})(?:\s*k\b)?",
    re.IGNORECASE,
)
#: A trailing "k" on the salary number multiplies by 1000 ("120k" -> 120000).
_SALARY_K = re.compile(r"(\d[\d,]*)\s*k\b", re.IGNORECASE)
#: A bare dollar amount ("$150k", "$150,000", "150k+") — recognized as a salary floor
#: even without the word "salary", because the user answering "what's your salary floor?"
#: often replies with just a number. Requires a "$" or a trailing "k"/"+" so a plain
#: integer (e.g. a throughput "5") is never mistaken for a salary.
_BARE_SALARY = re.compile(
    r"\$\s*(\d[\d,]*)\s*(k)?\b|\b(\d[\d,]*)\s*k\s*\+?", re.IGNORECASE
)
#: Verbs that mark a refocus/steer directive (so plain mention of "remote" in a
#: question is not treated as a criteria edit).
_REFOCUS_LEAD = re.compile(
    r"\b(?:focus|prioriti[sz]e|refocus|narrow|only|restrict|limit|target|search for|"
    r"look for|switch to|raise|lower|set|bump|increase|decrease|require|"
    r"want|looking for|interested in|apply (?:to|for)|find me|i'?d like|i want)\b",
    re.IGNORECASE,
)
#: "I want <X> roles/positions/jobs" — a free-text role/criteria statement the user
#: describes in their own words. Captured as the criteria ``human_readable`` statement
#: (which the apply-readiness gate accepts for BOTH target roles and key skills), so a
#: chat-only setup can satisfy the gate without the typed forms. Non-integral on its own.
_ROLE_STATEMENT = re.compile(
    r"\b(?:want|looking for|interested in|find me|i'?d like|apply (?:to|for)|"
    r"search for|look for|target)\b.{0,120}?\b(?:role|roles|position|positions|job|"
    r"jobs|work|opening|openings|engineer|developer|manager|designer|analyst|"
    r"scientist|lead|director|architect)\b",
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
        agent_run_service=None,
        scheduler=None,
        pending_actions=None,
        admin_query=None,
        identity_text=None,
        run_control=None,
        curation_service=None,
        tool_registry=None,
        computer_use=None,
        desktop_operable=False,
        chat_tools="off",
        onboarding=None,
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
        # The assistant IS the autonomous agent (FR-MIND-4 identity tier + FR-AGENT-7
        # /FR-OBS-2 activity awareness). These read-only sources let it narrate its own
        # work truthfully — what it has been doing, is doing now, and will do next:
        #   - ``agent_run_service``: latest per-run intent sentence + today's applied
        #     count vs the daily budget (``status(campaign_id)``); FR-AGENT-7.
        #   - ``scheduler``: live tick heartbeat — running now / last tick / next-tick
        #     estimate (``state()``); FR-OBS-2.
        #   - ``pending_actions``: what is awaiting the user right now (FR-UI-3).
        #   - ``admin_query``: recent application history / outcomes (FR-OBS-2).
        # All optional/defaulted: absent => the chat behaves exactly as before (the
        # status block is simply omitted). Truthfulness (FR-AGENT-5): the block is built
        # only from these real sources and is never invented; if a source is missing or
        # empty, that fact is omitted rather than fabricated.
        self._agent_run_service = agent_run_service
        self._scheduler = scheduler
        self._pending_actions = pending_actions
        self._admin_query = admin_query
        # FR-MIND-4: optional user-tunable identity/voice text. Prompt-injection-scanned
        # before use; when unsafe or unset, the built-in white-labeled voice is used.
        self._identity_text = identity_text
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
        # FR-MIND-6: the tool-call surface. When ``chat_tools`` is "auto" AND the
        # configured model advertises tool calling, ``_reply_text`` runs a bounded
        # tool-dispatch loop so the assistant can CHOOSE to remember/recall/save a
        # playbook (or take a bounded desktop action). All writes route through the
        # curation staging gate (FR-MIND-9) and the FR-UI-4 registry; nothing here can
        # bypass review-before-write or the stop-boundary. Default "off" + a non-tool
        # model is byte-identical to the prior single-shot path. ``curation_service``
        # stages memory/skill writes; ``computer_use``/``desktop_operable`` gate the
        # bounded desktop tool (offered only when a driver is operable).
        self._curation_service = curation_service
        self._tool_registry = tool_registry
        self._computer_use = computer_use
        self._desktop_operable = bool(desktop_operable)
        self._chat_tools = (chat_tools or "off").strip().lower()
        # The single source of "what's still missing before I can apply": the onboarding
        # service's ``apply_readiness(campaign_id)`` (the apply-readiness gate). OPTIONAL /
        # defaulted — when wired, the assistant PROACTIVELY asks for the missing essentials
        # (target roles, work mode, locations, salary floor, key skills, a résumé) and is
        # explicit that it can't begin applying until they're all present. The "missing"
        # set is read from here per turn (FR-MIND-10); it is never fabricated. Duck-typed
        # to ``apply_readiness(campaign_id) -> ApplyReadiness``; absent ⇒ the chat behaves
        # exactly as before (no essentials prompting, no gate copy).
        self._onboarding = onboarding

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

    # --- apply-readiness essentials (the hard gate on autonomous applying) ---
    def _apply_readiness(self, campaign_id: CampaignId):
        """The campaign's apply-readiness snapshot, or ``None`` when not wired.

        Reads from the onboarding service's single source of truth (the apply-readiness
        gate). Best-effort: any failure degrades to ``None`` so a turn is never broken
        by the readiness read; an absent service is a clean no-op (behaves as before).
        """
        if self._onboarding is None:
            return None
        reader = getattr(self._onboarding, "apply_readiness", None)
        if not callable(reader):
            return None
        try:
            return reader(str(campaign_id))
        except Exception:  # pragma: no cover - never let the gate read break a turn
            return None

    def _essentials_context(self, campaign_id: CampaignId) -> str:
        """A bounded "apply-readiness" block so the assistant proactively gathers gaps.

        Built fresh per turn from :meth:`_apply_readiness` (the real gate). When
        essentials are still missing, instructs the assistant to ASK for the next one
        or two (a focused, friendly nudge — never a wall of fields) and to be explicit
        that it can't start applying yet. When everything is in place, tells it that it
        can now begin. Truthful: the missing list is the gate's own, never invented;
        returns "" (block omitted) when no readiness source is wired.
        """
        readiness = self._apply_readiness(campaign_id)
        if readiness is None:
            return ""
        if readiness.ready:
            return (
                "Apply-readiness: every essential I need to start applying is now in "
                "place. You may tell the user you can begin applying (discovery and "
                "pre-fill); every final submit still waits for their approval. Do not "
                "claim you have already submitted anything."
            )
        missing = list(readiness.missing)
        # Ask for the next one or two only, so the prompt is a friendly nudge, not a form.
        ask_for = ", ".join(missing[:2])
        resume_note = ""
        if any("résumé" in m or "resume" in m for m in missing):
            resume_note = (
                " A résumé can't be sent through chat — if that's still missing, point "
                "the user to the profile/upload step to add it."
            )
        return (
            "Apply-readiness: I can't start applying yet. The essentials still missing "
            "are: " + ", ".join(missing) + ". Proactively and warmly ask the user for "
            f"the next one or two ({ask_for}) in your reply — one focused question, not "
            "a wall of fields. Be explicit that I can't begin applying until these are "
            "in place, and never claim I have started." + resume_note
        )

    def _essentials_missing(self, campaign_id: CampaignId) -> list[str]:
        """The still-missing apply essentials (plain labels), or [] when ready/unwired."""
        readiness = self._apply_readiness(campaign_id)
        if readiness is None or readiness.ready:
            return []
        return list(readiness.missing)

    def _essentials_followup(self, campaign_id: CampaignId) -> str:
        """A truthful one-liner after a capture: what's still missing, or "I can begin".

        Recomputed from the apply-readiness gate AFTER an essential was applied, so it
        reflects real state. Returns "" when no readiness source is wired (so a chat
        without onboarding behaves exactly as before — just the bare confirmation).
        """
        readiness = self._apply_readiness(campaign_id)
        if readiness is None:
            return ""
        if readiness.ready:
            return (
                "That's everything I need — I can start applying now. I'll hold every "
                "final submit for your approval."
            )
        missing = list(readiness.missing)
        resume_note = ""
        if any("résumé" in m or "resume" in m for m in missing):
            resume_note = " You can add your résumé from your profile."
        return (
            "Before I can start applying I still need: " + ", ".join(missing) + "."
            + resume_note
        )

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
        essentials = self._essentials_missing(campaign_id)
        deterministic = self._deterministic_reply(gaps, essentials_missing=essentials)
        if self._llm is None or not getattr(self._llm, "is_configured", lambda: False)():
            return deterministic
        try:
            system = self._identity_prompt()
            prompt = message
            profile_ctx = self._profile_context(campaign_id)
            if profile_ctx:
                prompt += f"\n\n{profile_ctx}"
            if gaps:
                prompt += f"\n\n(Known missing details: {', '.join(gaps)}.)"
            # The apply-readiness gate: when essentials are missing, the assistant
            # proactively gathers them; when complete, it may say it can begin. Read
            # fresh per turn from the gate's own "what's missing" (never fabricated).
            essentials_ctx = self._essentials_context(campaign_id)
            if essentials_ctx:
                prompt += f"\n\n{essentials_ctx}"
            # FR-AGENT-7 / FR-OBS-2: a bounded, freshly-assembled "current status" block
            # so "what have you been doing / are you doing / will you do next" answer from
            # real state. Read per reply (FR-MIND-10); omitted entirely when no sources
            # are wired or nothing is known (truthful, never invented — FR-AGENT-5).
            status_ctx = self._status_context(campaign_id)
            if status_ctx:
                prompt += f"\n\n{status_ctx}"
            interview_ctx = self._interview_context()
            if interview_ctx:
                prompt += f"\n\n{interview_ctx}"
            # FR-MIND-5: a bounded curated-memory + relevant-skills block, read fresh
            # per call (never cached — FR-MIND-10), advisory only (FR-MIND-11).
            memory_ctx = self._memory_context(campaign_id, message)
            if memory_ctx:
                prompt += f"\n\n{memory_ctx}"
            # FR-MIND-6: when the feature is on AND the model advertises tool calling,
            # run the bounded tool-dispatch loop so the assistant can CHOOSE to use its
            # memory/recall/playbook tools. Otherwise (the default), the single-shot
            # path below runs exactly as before — byte-identical.
            toolbox = self._maybe_toolbox(campaign_id)
            if toolbox is not None:
                tooled = self._reply_with_tools(system, prompt, toolbox)
                if tooled is not None:
                    return tooled.strip() or deterministic
            result = self._llm.complete(
                [ChatMessage(role="system", content=system), ChatMessage(role="user", content=prompt)],
                max_tokens=256,
            )
            text = (result.text or "").strip()
            return text or deterministic
        except Exception:
            # Any LLM failure degrades to the deterministic reply (offline-safe).
            return deterministic

    # --- tool-call loop (FR-MIND-6; capability-gated, additive) -----------
    def _maybe_toolbox(self, campaign_id: CampaignId):
        """Build a :class:`ChatToolbox` only when tool-calling is ON and SUPPORTED.

        Returns ``None`` (so ``_reply_text`` stays on the single-shot path, unchanged)
        unless: ``CHAT_TOOLS`` is "auto", the configured model advertises tool calling
        (``supports_tools()``), and at least one tool is actually offerable. Any of
        these false ⇒ today's behavior, byte-for-byte.
        """
        if self._chat_tools != "auto":
            return None
        supports = getattr(self._llm, "supports_tools", None)
        if not callable(supports):
            return None
        try:
            if not supports():
                return None
        except Exception:
            return None
        if not callable(getattr(self._llm, "complete_with_tools", None)):
            return None
        from applicant.application.services.chat_tools import ChatToolbox

        toolbox = ChatToolbox(
            campaign_id=campaign_id,
            agent_memory=self._agent_memory,
            curation_service=self._curation_service,
            tool_registry=self._tool_registry,
            computer_use=self._computer_use,
            desktop_operable=self._desktop_operable,
        )
        return toolbox if toolbox.has_tools() else None

    def _reply_with_tools(self, system: str, prompt: str, toolbox) -> str | None:
        """Run the bounded tool-dispatch loop; return the final text, or None to fall back.

        Caps the rounds (defense in depth alongside the toolbox cap). Each round: ask
        the model with the tool schemas, dispatch any tool calls it requested through
        the guarded toolbox, feed the results back, and repeat until it returns plain
        text or the cap is hit. Returns ``None`` on the first round if the model never
        used a tool, so the caller's single-shot completion is used unchanged.
        """
        from applicant.application.services.chat_tools import MAX_TOOL_ROUNDS

        schemas = toolbox.tool_schemas()
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=prompt),
        ]
        used_a_tool = False
        for _ in range(MAX_TOOL_ROUNDS):
            result = self._llm.complete_with_tools(messages, schemas, max_tokens=256)
            calls = tuple(getattr(result, "tool_calls", ()) or ())
            if not calls:
                text = (getattr(result, "text", "") or "").strip()
                # If the model never used a tool at all, fall back to the single-shot
                # path (None) for byte-identical behavior; otherwise return its text.
                return text if used_a_tool else (text or None)
            used_a_tool = True
            # Echo the assistant's tool-call message back, then append each result.
            messages.append(
                ChatMessage(role="assistant", content="", tool_calls=calls)
            )
            for call in calls:
                tool_result = toolbox.dispatch(call.name, call.arguments)
                messages.append(
                    ChatMessage(role="tool", content=tool_result, tool_call_id=call.id)
                )
        # Round cap hit: ask once more for a plain-text wrap-up (no tools).
        try:
            final = self._llm.complete(messages, max_tokens=256)
            return (getattr(final, "text", "") or "").strip() or None
        except Exception:
            return None

    # --- identity tier (FR-MIND-4) ----------------------------------------
    #: The built-in, white-labeled voice (FR-MIND-4 identity tier, slot #1), sourced
    #: from docs/voice-and-truthfulness.md: first person, warm but direct, conversational
    #: professional, demonstrate rather than state, truthful above all. The assistant IS
    #: the autonomous agent that runs the user's job search 24/7 — one identity, one
    #: persona. No codenames, no jargon (principle #3). No em-dashes (FR-RESUME-5).
    _BUILTIN_IDENTITY = (
        "You are Applicant, the autonomous agent that runs this person's job search "
        "around the clock. You are not a separate help desk; you are the same agent that "
        "discovers roles, scores them, tailors materials, pre-fills applications, and "
        "holds everything at the review line for their approval. Speak in the first "
        "person about your own work (\"I found\", \"I'm doing\", \"I'll do next\"). "
        "Voice: warm but direct, conversational and professional, active voice. Show, "
        "do not boast. Be concise. "
        "Truthfulness comes first: only state what the provided context actually says. "
        "If you do not have a fact, say you do not have it rather than guessing. Never "
        "invent activity, numbers, or progress you were not given. Answer using the "
        "candidate's saved profile and search criteria below, and do not ask for details "
        "already present there. Never claim to have changed any integral detail without "
        "the user's confirmation, and never claim to have submitted an application "
        "yourself: every final submit waits for the user."
    )

    #: Markers that, in user-supplied identity text, signal an attempt to override the
    #: agent's instructions or persona (a prompt-injection attempt). When any match, the
    #: user text is rejected and the built-in voice is used instead (FR-MIND-4).
    _IDENTITY_INJECTION = re.compile(
        r"ignore (?:all |the )?(?:previous|prior|above) instructions|disregard (?:all |the )?"
        r"(?:previous|prior|above)|you are now|new instructions:|system prompt|"
        r"reveal (?:your |the )?(?:system )?prompt|act as (?:a |an )?(?:dan|jailbreak)",
        re.IGNORECASE,
    )

    def _identity_prompt(self) -> str:
        """The system-prompt identity tier (FR-MIND-4).

        Returns the user-tunable identity text when one is configured AND it passes a
        prompt-injection scan; otherwise the built-in white-labeled voice. User text is
        appended to (never replaces) the built-in voice so the truthfulness/safety
        clauses cannot be tuned away.
        """
        from applicant.core.rules.agent_memory import claims_authority

        extra = (self._identity_text or "").strip()
        if not extra:
            return self._BUILTIN_IDENTITY
        # FR-MIND-4 / FR-MIND-11: untrusted text — reject an override/injection attempt
        # or an authority claim; fall back to the built-in voice unchanged.
        if self._IDENTITY_INJECTION.search(extra) or claims_authority(extra):
            return self._BUILTIN_IDENTITY
        if len(extra) > 800:
            extra = extra[:800]
        return self._BUILTIN_IDENTITY + "\n\nTone preferences from the user: " + extra

    # --- current-status context (FR-AGENT-7 / FR-OBS-2; truthful) ---------
    def _status_context(self, campaign_id: CampaignId) -> str:
        """A BOUNDED "current status" block the agent answers its own-work questions from.

        Assembled fresh per reply (FR-MIND-10) from read-only sources, in three parts:
        what I've been doing (recent applications + outcomes), what I'm doing now (the
        scheduler tick heartbeat + today's applied count), and what's next (the latest
        single-sentence next-action intent, the next-tick estimate, and what's pending).

        Truthfulness (FR-AGENT-5): every line comes from real state. A source that is
        absent or empty contributes nothing — it is never replaced with an invented
        value. When no source yields anything, returns "" and the block is omitted, so a
        chat with none of these wired behaves exactly as before.
        """
        recent: list[str] = []  # past
        now_lines: list[str] = []  # present
        next_lines: list[str] = []  # future

        # --- what I've been doing (recent applications + outcomes) ---------
        if self._admin_query is not None:
            try:
                history = self._admin_query.application_history(campaign_id, limit=5)
            except TypeError:  # adapters without the ``limit`` kwarg
                try:
                    history = (self._admin_query.application_history(campaign_id) or [])[:5]
                except Exception:
                    history = []
            except Exception:
                history = []
            for row in history or []:
                title = (row.get("job_title") or row.get("role_name") or "a role").strip()
                status = (row.get("status") or "").replace("_", " ").strip()
                outs = [
                    (o.get("type") or "").strip()
                    for o in (row.get("outcomes") or [])
                    if o.get("type")
                ]
                bit = title
                if status:
                    bit += f" ({status})"
                if outs:
                    bit += ", outcomes: " + ", ".join(outs[:3])
                recent.append("- " + bit)

        # --- what I'm doing now + what's next (run status: intent + counts) -
        run_status = None
        if self._agent_run_service is not None:
            try:
                run_status = self._agent_run_service.status(campaign_id)
            except Exception:
                run_status = None
        if run_status is not None:
            if run_status.get("paused"):
                now_lines.append("My automated work is paused right now.")
            applied = run_status.get("applied_today")
            budget = run_status.get("daily_budget")
            if applied is not None:
                count_line = f"Applications I've started today: {applied}"
                if budget:
                    count_line += f" of a daily budget of {budget}"
                now_lines.append(count_line + ".")
            intent = (run_status.get("latest_intent") or "").strip()
            if intent:
                next_lines.append(f"My stated next step: {intent}")

        # --- what I'm doing now (scheduler heartbeat) ----------------------
        if self._scheduler is not None:
            try:
                sched = self._scheduler.state()
            except Exception:
                sched = None
            if sched is not None:
                if sched.get("running"):
                    now_lines.append("I'm running a work cycle at this moment.")
                last = sched.get("last_tick")
                if last:
                    now_lines.append(f"My last work cycle ran at {last}.")
                nxt = sched.get("next_tick")
                if nxt:
                    next_lines.append(f"My next work cycle is due around {nxt}.")

        # --- what's next (pending actions awaiting the user) ---------------
        if self._pending_actions is not None:
            try:
                pending = self._pending_actions.list_pending(campaign_id)
            except Exception:
                pending = []
            pending = list(pending or [])
            if pending:
                titles = [
                    (getattr(p, "title", "") or "").strip()
                    for p in pending[:5]
                ]
                titles = [t for t in titles if t]
                head = (
                    f"There are {len(pending)} item(s) waiting for you"
                    if len(pending) != 1
                    else "There is 1 item waiting for you"
                )
                if titles:
                    head += ": " + "; ".join(titles)
                next_lines.append(head + ".")

        sections: list[str] = []
        if recent:
            sections.append("What I've been doing recently:\n" + "\n".join(recent[:5]))
        if now_lines:
            sections.append("What I'm doing now:\n" + "\n".join(f"- {x}" for x in now_lines))
        if next_lines:
            sections.append("What I'll do next:\n" + "\n".join(f"- {x}" for x in next_lines))
        if not sections:
            return ""
        return (
            "My current status (answer questions about your own work truthfully from "
            "this; if something is not here, say you don't have that detail rather than "
            "guessing):\n" + "\n\n".join(sections)
        )

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
    def _deterministic_reply(
        gaps: list[str], *, essentials_missing: list[str] | None = None
    ) -> str:
        # The apply-readiness essentials take precedence: while any is missing the agent
        # cannot start applying, so it proactively names them and asks for the next one
        # or two (truthful — these come straight from the gate). When all are present it
        # says it can begin.
        essentials_missing = essentials_missing or []
        if essentials_missing:
            ask_for = ", ".join(essentials_missing[:2])
            line = (
                "Before I can start applying, I still need: "
                + ", ".join(essentials_missing)
                + ". Could you tell me your " + ask_for + "?"
            )
            if any("résumé" in m or "resume" in m for m in essentials_missing):
                line += (
                    " You can add your résumé from your profile — I can't take a file "
                    "through chat."
                )
            return line
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
        # When a control turn actually APPLIED a criteria essential, append a truthful,
        # gate-derived "here's what's still missing / I can begin" line (recomputed AFTER
        # the apply, so it reflects the new state) — so the agent confirms what it
        # captured and what remains. Read from the apply-readiness gate; never fabricated.
        if control_reply and any(
            c.kind == "criteria" and c.applied for c in controls
        ):
            follow_up = self._essentials_followup(campaign_id)
            if follow_up:
                control_reply = (control_reply + " " + follow_up).strip()
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

        # work mode (non-integral -> applies directly). Detect any combination the user
        # named — remote / hybrid / on-site — so an answer like "remote or hybrid" is
        # captured in one go and counts toward the apply-readiness work-mode essential.
        modes: list[str] = []
        if _REMOTE.search(text):
            modes.append("remote")
        if _HYBRID.search(text):
            modes.append("hybrid")
        if _ONSITE.search(text):
            modes.append("on-site")
        if modes:
            label = ", ".join(modes)
            try:
                self._criteria.edit_criteria(
                    campaign_id, changes={"work_modes": modes}
                )
                out.append((
                    ControlAction(
                        kind="criteria", applied=True,
                        detail={"work_modes": modes},
                    ),
                    f"I've set your work mode to {label}.",
                ))
            except Exception:
                out.append((
                    ControlAction(kind="criteria", ok=False, applied=False),
                    f"I couldn't set your work mode to {label} just now.",
                ))

        # target roles / search criteria described in the user's own words. Captured as
        # the criteria ``human_readable`` statement, which the apply-readiness gate accepts
        # for both target-roles AND key-skills — so a chat-only setup satisfies the gate
        # without the typed forms. ``human_readable`` is NOT an integral criteria field, so
        # this applies directly (no confirmation needed) — the user is stating their intent.
        if _ROLE_STATEMENT.search(text):
            statement = text.rstrip(".")
            try:
                self._criteria.edit_criteria(
                    campaign_id, changes={"human_readable": statement}
                )
                out.append((
                    ControlAction(
                        kind="criteria", applied=True,
                        detail={"human_readable": statement},
                    ),
                    "Got it. I've captured what you're looking for in roles.",
                ))
            except Exception:
                out.append((
                    ControlAction(kind="criteria", ok=False, applied=False),
                    "I couldn't capture your target roles just now.",
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
        if m is not None:
            try:
                return int(m.group(1).replace(",", ""))
            except (TypeError, ValueError):  # pragma: no cover
                return None
        # Bare amount answering "what's your floor?" — "$150k", "150k+", "$150,000".
        bm = _BARE_SALARY.search(text)
        if bm is None:
            return None
        # group(1)+group(2) is the "$NNN[k]" branch; group(3) is the "NNNk[+]" branch.
        dollars, dollar_k, kform = bm.group(1), bm.group(2), bm.group(3)
        try:
            if dollars is not None:
                val = int(dollars.replace(",", ""))
                return val * 1000 if dollar_k else val
            if kform is not None:
                return int(kform.replace(",", "")) * 1000
        except (TypeError, ValueError):  # pragma: no cover
            return None
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
