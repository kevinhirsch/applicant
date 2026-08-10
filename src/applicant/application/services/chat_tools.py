"""Chat tool surface — the tools the assistant may call mid-conversation (FR-MIND-6).

A small, SAFE set of tools a tool-capable chat model can *choose* to use, instead of
only receiving memory/skills/recall as passive context:

* ``remember(text)`` / ``forget(substr)`` — curated memory (``memory.*``);
* ``save_playbook(...)`` / ``update_playbook(...)`` — procedural skills (``skill_manage``);
* ``recall(query)`` — read-only cross-session recall;
* ``desktop(action, ...)`` — a bounded desktop action, **only** registered when a
  desktop-assist driver is operable.

Every call is routed through the EXISTING guards (this module owns no policy of its own):

* each tool is gated by :meth:`ToolRegistry.ensure_enabled` (FR-UI-4 on/off toggles);
* memory/skill writes are STAGED for review via the curation service — the tool reports
  "noted, pending your approval"; it does not silently persist (FR-MIND-9);
* content that *claims* a safety-gated authority is refused as a write (FR-MIND-11) — the
  core ``claims_authority`` rule is the ground truth, never a caller flag;
* desktop actions go through the FR-CUA core guards + the pre-fill stop-boundary, so the
  assistant still cannot self-authorize an account-create / CAPTCHA / final submit.

The dispatcher returns a short, first-person, white-labeled result string per call. It
NEVER raises into the chat loop: a disabled/blocked/failed tool yields a polite refusal
string the model sees as the tool result, so the conversation degrades gracefully.
"""

from __future__ import annotations

import json
from typing import Any

from applicant.core.rules.agent_memory import claims_authority
from applicant.core.rules.computer_use import DesktopAction
from applicant.observability.logging import get_logger
from applicant.ports.driven.memory_store import KIND_ENVIRONMENT, KIND_USER, MemoryEntry
from applicant.ports.driven.skill_store import Skill

log = get_logger(__name__)

#: The FR-UI-4 registry key these chat-initiated tools are gated under. They are the
#: assistant's own (chat) capability, so they share the "chat" toggle — turning Chat off
#: disables the whole assistant, tool calls included.
_REGISTRY_KEY = "chat"

#: Hard cap on dispatch rounds (defense in depth; the loop in chat_service also caps).
MAX_TOOL_ROUNDS = 4

#: RUX-6 campaign-chat action tools. The criteria fields the assistant may steer, and
#: which of them are INTEGRAL (a change shifts the campaign's scope, so it can never be
#: silently committed — it is held for the user's confirmation, FR-FB-3). Kept in sync
#: with ``criteria_service._INTEGRAL_FIELDS`` (a private module constant we deliberately
#: do NOT import, to avoid a fragile cross-module private dependency).
_CRITERIA_INTEGRAL = frozenset({"titles", "locations", "salary_floor"})
_CRITERIA_FIELDS = frozenset(
    {"titles", "locations", "salary_floor", "work_modes", "keywords", "human_readable"}
)
#: Friendly labels for the criteria fields (used in the first-person result strings).
_CRITERIA_LABELS = {
    "titles": "target roles",
    "locations": "locations",
    "salary_floor": "salary floor",
    "work_modes": "work mode",
    "keywords": "key skills",
    "human_readable": "search description",
}


def _ok(text: str) -> str:
    return text


def _is_general_preference(text: str) -> bool:
    """Heuristic: a self-referential personal note vs a job-domain fact."""
    lower = text.lower().strip()
    # Personal / user preference signals
    if any(lower.startswith(p) for p in ("i ", "i'm ", "i am ", "my ", "me ", "i'd ", "i'll ", "i've ", "i") if len(lower) > 2):
        return True
    personal_signals = {"prefer", "like", "want", "need", "communication", "style", "nickname", "call me", "my name"}
    if personal_signals & set(lower.split()):
        return True
    # Job-domain signals: keep these going through curation
    job_signals = {"job", "role", "position", "company", "salary", "resume", "cover letter", "application"}
    if job_signals & set(lower.split()):
        return False
    # Default: ambiguous goes to curation (safer)
    return False


class ChatToolbox:
    """Builds the tool schemas + dispatches calls through the existing guards.

    All collaborators are optional/defaulted; a missing one simply means the
    corresponding tool is not offered (the schema list omits it) and, if somehow
    called anyway, the dispatcher returns a graceful "not available" result.
    """

    def __init__(
        self,
        *,
        campaign_id: Any,
        agent_memory=None,
        curation_service=None,
        tool_registry=None,
        computer_use=None,
        desktop_operable: bool = False,
        intake_service=None,
        criteria_service=None,
        digest_service=None,
        audit=None,
    ) -> None:
        self._campaign_id = campaign_id
        self._agent_memory = agent_memory
        self._curation = curation_service
        self._registry = tool_registry
        self._computer_use = computer_use
        # Desktop assist is offered ONLY when a driver is operable (FR-CUA). Default
        # off: the bounded ``desktop`` tool is not even advertised to the model.
        self._desktop_operable = bool(desktop_operable and computer_use is not None)
        self._intake = intake_service
        # RUX-6 campaign-chat action tools. Each is CAPABILITY-GATED (offered only when
        # its backing service is wired AND the FR-UI-4 "chat" toggle is on), REVERSIBLE
        # (an integral criteria change is held for the user's confirmation; a discard is
        # archived-with-reason, never a hard delete), and AUDITED (every successful action
        # is logged + forwarded to the optional ``audit`` sink; approve/decline are also
        # captured by the domain-event AuditLogService). None of them submits — the
        # never-auto-submit safety line holds.
        self._criteria = criteria_service
        self._digest = digest_service
        self._audit_sink = audit
        # WIRING: register these tools into the live campaign agent by having
        # ChatService._maybe_toolbox pass through the services it already holds:
        #   ChatToolbox(..., criteria_service=self._criteria, digest_service=self._digest,
        #               audit=<optional AuditLogService/log sink>)
        # (chat_service.py is a shared wiring point owned by the Integrate step; this
        # module stays additive.)

    # --- schema collection (FR-MIND-6) ------------------------------------
    def tool_schemas(self) -> list[dict[str, Any]]:
        """OpenAI-style function schemas for every AVAILABLE tool.

        A tool is offered only when its backing service is wired AND its FR-UI-4 toggle
        is on, so a disabled/absent capability is never dangled in front of the model.
        """
        schemas: list[dict[str, Any]] = []
        if self._memory_available():
            schemas.append(_fn(
                "remember",
                "Save a durable note or user preference to your curated memory. The "
                "note is STAGED for the user's approval before it persists; it is not "
                "applied silently.",
                {
                    "text": {"type": "string", "description": "The note to remember."},
                    "about_user": {
                        "type": "boolean",
                        "description": "True if this is the user's own preference or "
                        "communication style, false for an environment fact or lesson.",
                    },
                },
                ["text"],
            ))
            schemas.append(_fn(
                "forget",
                "Propose removing curated notes whose text contains a substring. This "
                "is STAGED for the user's approval before anything is removed.",
                {"substring": {"type": "string", "description": "Substring to match."}},
                ["substring"],
            ))
        if self._skills_available():
            schemas.append(_fn(
                "save_playbook",
                "Author a reusable playbook (a procedure you learned) for later. STAGED "
                "for the user's approval before it is saved.",
                {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "when_to_use": {"type": "string"},
                    "procedure": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered steps of the procedure.",
                    },
                },
                ["name", "procedure"],
            ))
            schemas.append(_fn(
                "update_playbook",
                "Improve an existing saved playbook. STAGED for the user's approval.",
                {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "when_to_use": {"type": "string"},
                    "procedure": {"type": "array", "items": {"type": "string"}},
                },
                ["name", "procedure"],
            ))
        if self._recall_available():
            schemas.append(_fn(
                "recall",
                "Search your own past runs and conversations for relevant context. "
                "Read-only.",
                {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "Max hits (default 5)."},
                },
                ["query"],
            ))
        if self._intake_available():
            schemas.append(_fn(
                "save_job",
                "Save a job posting URL into the campaign's intake pipeline. The engine "
                "will score and tag it; the result is reported honestly.",
                {
                    "url": {"type": "string", "description": "The job posting URL to save."},
                },
                ["url"],
            ))
        if self._criteria_available():
            schemas.append(_fn(
                "edit_criteria",
                "Adjust one field of the user's saved search criteria, which affects ALL "
                "future scoring and suggestions. Non-integral fields (work mode, key "
                "skills, search description) apply right away and are reversible. Integral "
                "fields (target roles, locations, salary floor) shift the scope of the "
                "search, so you CANNOT apply them yourself — they are held for the user's "
                "explicit confirmation.",
                {
                    "field": {
                        "type": "string",
                        "enum": sorted(_CRITERIA_FIELDS),
                        "description": "Which criteria field to change.",
                    },
                    "value": {
                        "type": "string",
                        "description": "The new value. For list fields (roles, locations, "
                        "work mode, skills) use a comma-separated string.",
                    },
                },
                ["field", "value"],
            ))
        if self._digest_available():
            schemas.append(_fn(
                "rescore",
                "Re-score the user's discovered roles against their CURRENT criteria and "
                "rebuild today's matches. Read-only re-ranking — it never drafts or submits "
                "anything.",
                {},
                [],
            ))
            schemas.append(_fn(
                "draft_application",
                "Start a draft for a specific role: tailor a resume and cover letter and "
                "get it ready to apply. It is held at the user's review line and is NEVER "
                "submitted without their explicit approval. Reversible — the user can still "
                "discard it.",
                {
                    "application_id": {
                        "type": "string",
                        "description": "The id of the posting/role to draft (from the "
                        "digest or pending reviews).",
                    },
                },
                ["application_id"],
            ))
            schemas.append(_fn(
                "discard_job",
                "Discard a role the user does not want, with a brief reason. The reason is "
                "REQUIRED (it teaches the next run to rank similar roles lower). The role is "
                "archived rather than deleted, so it is reversible.",
                {
                    "application_id": {
                        "type": "string",
                        "description": "The id of the posting/role to discard.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "A brief reason it is not a fit (required).",
                    },
                },
                ["application_id", "reason"],
            ))
        if self._desktop_operable:
            schemas.append(_fn(
                "desktop",
                "Take ONE bounded action on the assist desktop, or capture its current "
                "state. You cannot create accounts, solve CAPTCHAs, verify, or submit "
                "applications; those always wait for the user.",
                {
                    "action": {
                        "type": "string",
                        "enum": [
                            "capture", "click", "type_text", "key",
                            "scroll", "drag", "focus_app",
                        ],
                    },
                    "target": {
                        "type": "string",
                        "description": "Element token / app name, when the action needs one.",
                    },
                    "text": {"type": "string", "description": "Text for type_text."},
                    "keys": {"type": "string", "description": "Chord for key, e.g. 'ctrl+a'."},
                    "intent": {
                        "type": "string",
                        "description": "What the control does, e.g. 'next_page'. Never a "
                        "way to opt past a safety boundary.",
                    },
                },
                ["action"],
            ))
        return schemas

    # --- availability gates -----------------------------------------------
    def _registry_on(self) -> bool:
        if self._registry is None:
            return True  # no registry wired => default-enabled (no dead capability)
        try:
            self._registry.ensure_enabled(_REGISTRY_KEY)
            return True
        except Exception:
            return False

    def _memory_available(self) -> bool:
        return (
            self._agent_memory is not None
            and getattr(self._agent_memory, "memory", None) is not None
            and self._curation is not None
            and self._registry_on()
        )

    def _skills_available(self) -> bool:
        return (
            self._agent_memory is not None
            and getattr(self._agent_memory, "skills", None) is not None
            and self._curation is not None
            and self._registry_on()
        )

    def _recall_available(self) -> bool:
        return (
            self._agent_memory is not None
            and getattr(self._agent_memory, "recall", None) is not None
            and self._registry_on()
        )

    def _intake_available(self) -> bool:
        return self._intake is not None and self._registry_on()

    def _criteria_available(self) -> bool:
        return self._criteria is not None and self._registry_on()

    def _digest_available(self) -> bool:
        return self._digest is not None and self._registry_on()

    def has_tools(self) -> bool:
        """True when at least one tool is offerable (so the loop is worth entering)."""
        return bool(self.tool_schemas())

    # --- dispatch (FR-MIND-6) ---------------------------------------------
    def dispatch(self, name: str, arguments: str) -> str:
        """Run one tool call through its guards; return a first-person result string.

        Never raises into the chat loop — every failure path returns a polite string
        the model consumes as the tool result.
        """
        try:
            args = json.loads(arguments) if arguments else {}
            if not isinstance(args, dict):
                args = {}
        except (json.JSONDecodeError, ValueError):
            args = {}

        # FR-UI-4: enforce the toggle at dispatch for EVERY tool (authoritative).
        if self._registry is not None:
            try:
                self._registry.ensure_enabled(_REGISTRY_KEY)
            except Exception:
                return "I can't use that tool right now; it's turned off in settings."

        handler = {
            "remember": self._remember,
            "forget": self._forget,
            "save_playbook": self._save_playbook,
            "update_playbook": self._update_playbook,
            "recall": self._recall,
            "save_job": self._save_job,
            "edit_criteria": self._edit_criteria,
            "rescore": self._rescore,
            "draft_application": self._draft_application,
            "discard_job": self._discard_job,
            "desktop": self._desktop,
        }.get(name)
        if handler is None:
            return f"I don't have a tool called '{name}'."
        try:
            return handler(args)
        except Exception as exc:  # pragma: no cover - defensive: never break the loop
            log.warning("chat_tool_failed", tool=name, error=str(exc))
            return "I tried to do that but ran into a problem, so I left it untouched."

    # --- tool handlers -----------------------------------------------------
    def _remember(self, args: dict) -> str:
        if not self._memory_available():
            return "I can't save notes to memory right now."
        text = (args.get("text") or "").strip()
        if not text:
            return "There was nothing to remember."
        # FR-MIND-11: a note that CLAIMS a safety-gated authority is refused as a write
        # — the core rule is ground truth; a learned note can never grant authority.
        if claims_authority(text):
            return (
                "I won't save that as a standing instruction — a note can't grant me "
                "permission to submit, create accounts, or skip your review."
            )

        # D19 memory routing (AZ2-5 H1): classify the note and name the destination.
        # A note is a GENERAL PREFERENCE when the caller flags it as about the user
        # OR the heuristic says so; otherwise it is a JOB-SEARCH FACT.
        if args.get("about_user") or _is_general_preference(text):
            kind = KIND_USER
            campaign_id = None  # GLOBAL scope: A0 user memory (user/USER.md tier)
        else:
            kind = KIND_ENVIRONMENT
            campaign_id = self._campaign_str()  # CAMPAIGN scope: engine mind

        result = self._curation.stage_memory(
            text, kind=kind, campaign_id=campaign_id
        )
        if getattr(result, "auto_applied", 0):
            if kind == KIND_USER:
                return "Noted, and saved that to my own memory (your preferences)."
            return "Noted, and saved that with your job profile in the engine's memory."
        if kind == KIND_USER:
            return "Noted. I've put that in my own memory (your preferences), pending your approval."
        return "Noted. I've put that with your job profile in the engine's memory, pending your approval."

    def _forget(self, args: dict) -> str:
        if not self._memory_available():
            return "I can't change memory right now."
        substr = (args.get("substring") or "").strip()
        if not substr:
            return "I need to know what to forget."
        # Removal is staged the same way as a write would be, by proposing a note that
        # records the request; the actual removal happens on approval. To keep this
        # additive and review-gated we surface it as a pending request rather than
        # mutating the store directly here.
        result = self._curation.stage_memory(
            f"Forget notes containing: {substr}",
            kind=KIND_ENVIRONMENT,
            campaign_id=self._campaign_str(),
        )
        if getattr(result, "auto_applied", 0):
            removed = self._agent_memory.memory.remove(substr)
            return f"Done. I removed {removed} matching note(s)."
        return "Okay. I've queued that removal for your approval."

    def _save_playbook(self, args: dict) -> str:
        if not self._skills_available():
            return "I can't save playbooks right now."
        skill = self._build_skill(args)
        if skill is None:
            return "I need at least a name and a step to save a playbook."
        self._curation.stage_skill(skill, is_improvement=False)
        return (
            f"I've drafted a playbook called '{skill.name}' and put it up for your "
            "approval before saving it."
        )

    def _update_playbook(self, args: dict) -> str:
        if not self._skills_available():
            return "I can't update playbooks right now."
        skill = self._build_skill(args)
        if skill is None:
            return "I need the playbook name and the updated steps."
        self._curation.stage_skill(skill, is_improvement=True)
        return (
            f"I've drafted an update to '{skill.name}' and put it up for your approval."
        )

    def _recall(self, args: dict) -> str:
        if not self._recall_available():
            return "I don't have past runs to search right now."
        query = (args.get("query") or "").strip()
        if not query:
            return "I need something to search for."
        limit = args.get("limit")
        try:
            limit = int(limit) if limit is not None else 5
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, 10))
        hits = self._agent_memory.recall.search(
            query, limit=limit, campaign_id=self._campaign_str()
        )
        if not hits:
            return "I didn't find anything relevant in my past runs."
        lines = [f"- {(h.text or '').strip()[:200]}" for h in hits if (h.text or "").strip()]
        if not lines:
            return "I didn't find anything relevant in my past runs."
        return "Here's what I found in my past runs:\n" + "\n".join(lines)

    def _save_job(self, args: dict) -> str:
        """Save one job URL through the ENGINE intake use-case (the same service
        the /api/intake router calls) and report what the engine returned — never
        fabricating a save.

        Consequential job actions go through the engine gate (apply-readiness
        review); this only captures the URL into the campaign's reviewed intake
        pipeline, exactly like the direct-URL intake endpoint.
        """
        if not self._intake_available():
            return "I can't save jobs to your intake pipeline right now."
        url = (args.get("url") or "").strip()
        if not url:
            return "I need a job posting URL to save."
        campaign_id = self._campaign_str()
        if not campaign_id:
            return "I can't save that job without a campaign to attach it to."
        try:
            result = self._intake.save_url(campaign_id, url)
        except Exception as exc:
            log.info("chat_save_job_failed", url=url, error=str(exc))
            return "I couldn't save that job through the engine — I left it untouched."
        if not isinstance(result, dict):
            return "The engine didn't return a usable result for that save — I left it untouched."
        if result.get("duplicate"):
            title = result.get("title") or "the posting"
            company = result.get("company") or "that company"
            return f"That job is already in your pipeline — {title} at {company} is already tracked."
        if not result.get("saved"):
            return "The engine did not confirm that save — I left it untouched."
        title = result.get("title") or url
        company = result.get("company") or "that company"
        parts = [f"I saved '{title}' at {company} into your intake pipeline."]
        score = result.get("viability_score")
        if score is not None:
            parts.append(f"Engine viability score: {score}.")
        if result.get("fetched") is False:
            parts.append("The page itself wasn't read; the row was derived from the link alone.")
        note = result.get("note")
        if note:
            parts.append(str(note))
        return " ".join(parts)

    # --- RUX-6 campaign-chat action tools (gated + reversible + audited) ---
    def _edit_criteria(self, args: dict) -> str:
        """Adjust one criteria field via the EXISTING CriteriaService (FR-CRIT-2/3).

        Non-integral fields (work mode / key skills / search description) apply directly
        and are reversible. Integral fields (target roles / locations / salary floor)
        are NEVER self-committed here — the assistant proposes them and they wait for the
        user's explicit confirmation (FR-FB-3), exactly like the criteria refocus path.
        """
        if not self._criteria_available():
            return "I can't change your search criteria right now."
        campaign_id = self._campaign_str()
        if not campaign_id:
            return "I can't change criteria without a campaign to attach them to."
        field = (args.get("field") or "").strip().lower()
        if field not in _CRITERIA_FIELDS:
            return (
                "I can only change your target roles, locations, work mode, salary floor, "
                "search description, or key skills."
            )
        value = args.get("value")
        if value is None or (isinstance(value, str) and not value.strip()):
            return "I need a value to set for that."
        label = _CRITERIA_LABELS.get(field, field)
        if field in _CRITERIA_INTEGRAL:
            # Never self-confirm an integral change: hold it for the user (FR-FB-3).
            self._audit("edit_criteria_proposed", campaign_id=campaign_id, field=field)
            return (
                f"Changing your {label} shifts the scope of your search, so I won't apply "
                "it on my own — it's waiting for your confirmation. Just say the word and "
                "I'll set it (and it's reversible either way)."
            )
        try:
            self._criteria.edit_criteria(campaign_id, changes={field: value})
        except Exception as exc:
            log.info("chat_edit_criteria_failed", field=field, error=str(exc))
            return "I couldn't update that just now, so I left your criteria unchanged."
        self._audit(
            "edit_criteria", campaign_id=campaign_id, field=field, value=str(value)
        )
        return (
            f"Done. I've updated your {label}; it'll affect how I score and suggest roles "
            "from here on, and you can change it again anytime."
        )

    def _rescore(self, args: dict) -> str:
        """Re-score against current criteria via the EXISTING digest build path.

        Reuses ``DigestService.build_digest_payload`` (rebuild + re-score, no delivery /
        no notification side-effects). Read-mostly and idempotent; it never drafts or
        submits anything.
        """
        if not self._digest_available():
            return "I can't re-score your matches right now."
        campaign_id = self._campaign_str()
        if not campaign_id:
            return "I can't re-score without a campaign to work on."
        try:
            payload = self._digest.build_digest_payload(campaign_id)
        except Exception as exc:
            log.info("chat_rescore_failed", error=str(exc))
            return "I ran into a problem re-scoring, so nothing changed."
        rows = payload.get("rows") if isinstance(payload, dict) else None
        count = len(rows) if isinstance(rows, list) else 0
        self._audit("rescore", campaign_id=campaign_id, matches=count)
        if count == 0:
            return (
                "I re-scored against your current criteria. Nothing clears the bar right "
                "now, but I'll keep looking. (Re-scoring only re-ranks what I've found; it "
                "never submits anything.)"
            )
        noun = "match" if count == 1 else "matches"
        return (
            f"I re-scored against your current criteria — {count} {noun} in your digest "
            "now. Re-scoring only re-ranks what I've found; it never submits anything."
        )

    def _draft_application(self, args: dict) -> str:
        """Start a draft for a role via the EXISTING approve-to-draft path.

        Reuses ``DigestService.approve`` (the same gated path the landing page's "Draft
        this" button uses): it tailors materials and moves the role forward, but it stops
        at the review line — it NEVER submits. Reversible: the user can still discard it.
        """
        if not self._digest_available():
            return "I can't start a draft right now."
        application_id = (args.get("application_id") or "").strip()
        if not application_id:
            return "I need to know which role to draft — tell me the role and I'll start it."
        try:
            self._digest.approve(application_id)
        except Exception as exc:
            log.info("chat_draft_failed", application_id=application_id, error=str(exc))
            return "I couldn't start that draft, so I left it untouched."
        self._audit(
            "draft_application",
            campaign_id=self._campaign_str(),
            application_id=application_id,
        )
        return (
            "I've started a draft for that role — I'll tailor a resume and cover letter "
            "and hold everything at your review line. I never submit an application "
            "without your approval."
        )

    def _discard_job(self, args: dict) -> str:
        """Discard a role with a reason via the EXISTING decline path.

        Reuses ``DigestService.decline``: the reason is REQUIRED (FR-FB-1) and feeds a
        negative learning signal so similar roles rank lower; the role is archived rather
        than deleted, so the action is reversible.
        """
        if not self._digest_available():
            return "I can't discard a role right now."
        application_id = (args.get("application_id") or "").strip()
        if not application_id:
            return "I need to know which role to discard."
        reason = (args.get("reason") or "").strip()
        if not reason:
            return (
                "Tell me briefly why it's not a fit and I'll discard it — the reason helps "
                "me rank similar roles lower next time."
            )
        try:
            self._digest.decline(application_id, feedback_text=reason)
        except Exception as exc:
            log.info("chat_discard_failed", application_id=application_id, error=str(exc))
            return "I couldn't discard that just now, so I left it untouched."
        self._audit(
            "discard_job",
            campaign_id=self._campaign_str(),
            application_id=application_id,
        )
        return (
            "Done — I've discarded that role and noted your reason, so I'll rank similar "
            "roles lower. It's archived rather than deleted, so tell me if you want it back."
        )

    # --- audit trail (RUX-6: every gated action is recorded) --------------
    def _audit(self, action: str, **detail: Any) -> None:
        """Record one gated chat action.

        Always logs a structured line (the module's existing audit lane); additionally
        forwards to an injected ``audit`` sink when one is wired. approve/decline are also
        captured by the domain-event AuditLogService, so this is belt-and-suspenders for
        them and the primary record for edit_criteria/rescore. Never raises into a tool.
        """
        try:
            log.info("chat_tool_action", tool=action, **detail)
        except Exception:  # pragma: no cover - logging must never break a tool
            pass
        if self._audit_sink is not None:
            try:
                self._audit_sink(action, dict(detail))
            except Exception:  # pragma: no cover - a bad sink must never break a tool
                pass

    def _desktop(self, args: dict) -> str:
        if not self._desktop_operable:
            return "Desktop assist isn't available right now."
        action_raw = (args.get("action") or "").strip().lower()
        try:
            action = DesktopAction(action_raw)
        except ValueError:
            return f"I don't recognize the desktop action '{action_raw}'."
        cu = self._computer_use
        try:
            if action is DesktopAction.CAPTURE:
                cap = cu.capture()
                return f"I captured the desktop ({cap.element_count} elements visible)."
            if action is DesktopAction.CLICK:
                cu.click(args.get("target") or "")
            elif action is DesktopAction.TYPE_TEXT:
                cu.type_text(args.get("text") or "")
            elif action is DesktopAction.KEY:
                cu.key(args.get("keys") or "")
            elif action is DesktopAction.SCROLL:
                cu.scroll(args.get("target") or "")
            elif action is DesktopAction.DRAG:
                cu.drag(args.get("target") or "", args.get("text") or "")
            elif action is DesktopAction.FOCUS_APP:
                cu.focus_app(args.get("target") or "")
            else:  # pragma: no cover - vocabulary is exhaustive above
                return "I can't take that desktop action."
        except Exception as exc:
            # The FR-CUA core guards raise here for a blocked/boundary action; surface
            # the refusal plainly. A stop-boundary step (account-create / CAPTCHA /
            # submit) is denied here exactly as in the browser path.
            log.info("chat_desktop_blocked", action=action_raw, error=str(exc))
            return (
                "I can't do that on the desktop — it's either blocked for safety or it "
                "would cross a step that waits for you (like creating an account, a "
                "CAPTCHA, or a final submit)."
            )
        return f"Done. I performed a '{action_raw}' on the desktop."

    # --- helpers ----------------------------------------------------------
    def _build_skill(self, args: dict) -> Skill | None:
        name = (args.get("name") or "").strip()
        procedure = args.get("procedure") or []
        if isinstance(procedure, str):
            procedure = [procedure]
        procedure = tuple(str(s).strip() for s in procedure if str(s).strip())
        if not name or not procedure:
            return None
        scope = "campaign" if self._campaign_str() else "global"
        return Skill(
            name=name,
            description=(args.get("description") or "").strip(),
            when_to_use=(args.get("when_to_use") or "").strip(),
            procedure=procedure,
            scope=scope,
            campaign_id=self._campaign_str(),
            source="taught",
        )

    def _campaign_str(self) -> str | None:
        if self._campaign_id is None:
            return None
        return str(self._campaign_id)


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict[str, Any]:
    """Build one OpenAI-style function/tool schema entry."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }
