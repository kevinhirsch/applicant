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
from applicant.core.ids import CampaignId
from applicant.core.rules.confirmation_gate import requires_confirmation
from applicant.core.rules.sensitive_fields import is_sensitive_field
from applicant.ports.driven.llm import ChatMessage

#: Core attributes a campaign needs before it can apply confidently (FR-CHAT-1 gaps).
CORE_ATTRIBUTES: tuple[str, ...] = (
    "first name",
    "last name",
    "email address",
    "phone",
    "current job title",
)

#: "my <attr> is <value>" / "<attr>: <value>" statement parser (FR-FB-2 input).
_STATEMENT = re.compile(
    r"^\s*(?:my\s+)?(?P<name>[a-z][a-z0-9 _-]{1,48}?)\s+(?:is|are|=|:)\s+(?P<value>.+?)\s*$",
    re.IGNORECASE,
)

#: Attribute names treated as integral (a change needs confirmation, FR-FB-3).
_INTEGRAL_NAMES = frozenset(
    {"first name", "last name", "legal name", "email address", "phone"}
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
class ChatTurnResult:
    """The result of one conversational turn."""

    message: str
    gaps: list[str] = field(default_factory=list)
    proposed_changes: list[ProposedChange] = field(default_factory=list)


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
    ) -> None:
        self._attrs = attribute_service
        self._criteria = criteria_service
        self._llm = llm
        # Optional LearningService so a chat taste statement folds a cheap signal into
        # the per-campaign learning model (FR-LEARN-3: every input feeds learning).
        self._learning = learning
        self._storage = storage

    # --- gap finding (FR-CHAT-1) ------------------------------------------
    def identify_gaps(self, campaign_id: CampaignId) -> list[str]:
        """Which core attributes / criteria are still missing for the campaign."""
        have = {a.name.lower() for a in self._attrs.list_attributes(campaign_id)}
        gaps = [c for c in CORE_ATTRIBUTES if c not in have]
        if self._criteria is not None:
            crit = self._criteria.get_criteria(campaign_id)
            if not crit.titles and not crit.human_readable:
                gaps.append("target roles / search criteria")
        return gaps

    # --- proposal parsing (FR-FB-2/3) -------------------------------------
    def _parse_proposal(self, message: str) -> ProposedChange | None:
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
                "You are the Applicant assistant. Help the user fill in their job-"
                "application profile. Be concise. Never claim to have changed any "
                "integral detail without confirmation."
            )
            prompt = message
            if gaps:
                prompt += f"\n\n(Known missing details: {', '.join(gaps)}.)"
            result = self._llm.complete(
                [ChatMessage(role="system", content=system), ChatMessage(role="user", content=prompt)],
                max_tokens=256,
            )
            text = (result.text or "").strip()
            return text or deterministic
        except Exception:
            # Any LLM failure degrades to the deterministic reply (offline-safe).
            return deterministic

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
        parsed = self._parse_proposal(message)
        if parsed is not None:
            proposals.append(self._maybe_autoapply(campaign_id, parsed))
        reply = self._reply_text(campaign_id, message, gaps)
        # FR-LEARN-3: fold a cheap chat taste signal so every input feeds learning.
        self._fold_chat_taste(campaign_id, message)
        return ChatTurnResult(message=reply, gaps=gaps, proposed_changes=proposals)

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
