"""LLM parse-verify layer over the deterministic résumé parser (P1-1a).

The deterministic parser anticipates layouts; real résumés are a "dynamic sheet
of paper". This decorator adapter keeps the deterministic pass as the draft and
asks the configured LLM to *slot* every value into the right field — correcting
splits, misfiled sections, and missed entries — then merges the corrected parse
back into the port's :class:`ParsedResume`.

Grounding — the slotting contract (owner policy, P1-13 adjacent): slotting is
re-filing, not writing. Every corrected value must trace to the source text;
a corrected value that does not appear in the source is DROPPED (and counted in
``extra["verify"]["unsourced_dropped"]``) rather than trusted — re-filing never
introduces facts. The tier study that sized this layer (all four tier models
produced a perfect corrected parse with zero invented strings; the local floor
was fastest once reasoning was off) lives at
``docs/studies/2026-07-07-parse-verify-tier-study.md``.

Escalation: one verify call at the ladder floor; on malformed output or
confidence below the floor, ONE retry starting a tier higher. On any failure
(no model, ladder exhausted, still-malformed) the deterministic parse is
returned unchanged with ``extra["verify"]["verified"] = False`` and a reason
code — the caller surfaces "not verified" honestly (H2: no silent degrade).

Deployment note from the study: reasoning-mode output can consume the whole
completion budget and return nothing. The engine's ladder has no reasoning
toggle, so this layer compensates: a generous ``max_tokens``, a hard
"output ONLY the JSON object" instruction, and empty/malformed output treated
as the escalation signal.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from typing import Any

from applicant.adapters.llm.openai_compatible import balanced_object_spans
from applicant.ports.driven.llm import ChatMessage, LLMError, LLMNotConfigured
from applicant.ports.driven.resume_parser import (
    EducationEntry,
    ParsedResume,
    ResumeParserPort,
    WorkHistoryEntry,
)

log = logging.getLogger(__name__)

#: Escalate when any per-area confidence lands below this (study: clean inputs
#: self-report 0.9-1.0; the gap below ~0.8 is where a second opinion pays).
CONFIDENCE_FLOOR = 0.8
#: Generous completion budget — the study's "reasoning burned the whole budget"
#: trap means a tight cap turns a thinking model into an empty answer.
VERIFY_MAX_TOKENS = 6000
#: Defensive caps on merged collections (a runaway model can't flood the cloud).
_MAX_ROLES = 20
_MAX_EDU = 20
_MAX_SKILLS = 100
_MAX_ACHIEVEMENTS = 15

_SYSTEM = (
    "You verify and correct a DRAFT parse of a résumé against its SOURCE text.\n"
    "HARD RULES:\n"
    "1) Output ONLY a JSON object matching the SCHEMA - no prose, no markdown "
    "fences, no thinking out loud.\n"
    "2) Every string you output MUST appear in SOURCE (as an exact substring, "
    "ignoring case, whitespace and punctuation). Never invent, infer, or "
    "embellish anything.\n"
    "3) If information is absent from SOURCE, use an empty string - do not guess.\n"
    "4) Fix DRAFT mistakes: wrong title/company splits, entries that are really "
    "locations or section noise, missing roles, education/certifications/schools "
    "mis-parsed or missing, missing skills, achievement bullets under the wrong "
    "role. Education includes degrees, certifications, and schools.\n"
    "5) Report a confidence 0.0-1.0 per area and list the corrections you made."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "full_name": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "work_history": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "location": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "achievements": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "issuer": {"type": "string"},
                    "year": {"type": "string"},
                },
            },
        },
        "skills": {"type": "array", "items": {"type": "string"}},
        "confidence": {
            "type": "object",
            "properties": {
                "contact": {"type": "number"},
                "work_history": {"type": "number"},
                "education": {"type": "number"},
                "skills": {"type": "number"},
            },
        },
        "corrections": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["work_history", "education", "skills", "confidence"],
}


def _collapse(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 2]


_MONTH3 = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}
_DATE_WORDS = {"present", "current", "now", "to", "through", "until", "ongoing",
               "spring", "summer", "fall", "winter"}


def _source_windows(raw: str, max_window: int = 3) -> list[str]:
    """Every run of 1..``max_window`` consecutive non-empty source lines.

    The grounding check matches values against these LOCAL windows instead of the
    whole document collapsed to one string. Windows tolerate what real extraction
    does to real résumés — a value hard-wrapped across adjacent lines, a
    title|company pair split by the layout — while refusing document-flattening
    artifacts: a blank line is a HARD boundary (section break), so a phrase can
    never be assembled from parts of different sections, and nothing beyond a few
    adjacent lines ever concatenates. Deliberate tolerance: a phrase spanning
    adjacent lines *within* one block (one visual entry) still grounds — that is
    a mis-slot at worst, never an invented fact from elsewhere in the document.
    """
    blocks: list[list[str]] = [[]]
    for ln in (raw or "").splitlines():
        if ln.strip():
            blocks[-1].append(ln)
        elif blocks[-1]:
            blocks.append([])
    windows: list[str] = []
    for block in blocks:
        n = len(block)
        for i in range(n):
            for w in range(1, max_window + 1):
                if i + w <= n:
                    windows.append(" ".join(block[i : i + w]))
    return windows


def _is_date_like(value: str) -> bool:
    """True when ``value`` reads as a date/date-range (months, years, 'Present').

    Gates the lenient token-subsumption fallback in the grounding check: ONLY a
    date may match token-by-token ("Jun 2021" ~ source "June 2021"). Any other
    value must appear contiguously in the source, otherwise a model could
    recombine scattered résumé tokens ("Data" + "Engineer" + a company name from
    another entry) into a phrase that never existed and have it accepted.
    """
    toks = _tokens(value)
    if not toks:
        return False
    saw_datey = False
    for t in toks:
        if t.isdigit():
            saw_datey = True
            continue
        if t in _DATE_WORDS or t[:3] in _MONTH3:
            saw_datey = True
            continue
        return False
    return saw_datey


class LLMVerifiedResumeParser:
    """Decorator over :class:`ResumeParserPort` adding LLM verify-and-correct.

    Built before the LLM ladder exists in the container, so the model is
    late-bound via :meth:`bind_llm` (the container's usual ``set_*`` wiring
    style). Until bound — or when disabled / unconfigured / failing — ``parse``
    degrades to the inner deterministic parse with an honest not-verified marker.
    """

    def __init__(
        self,
        inner: ResumeParserPort,
        llm: Any = None,
        *,
        enabled: bool = True,
        confidence_floor: float = CONFIDENCE_FLOOR,
        max_tokens: int = VERIFY_MAX_TOKENS,
    ) -> None:
        self._inner = inner
        self._llm = llm
        self._enabled = enabled
        self._floor = confidence_floor
        self._max_tokens = max_tokens

    @property
    def inner(self) -> ResumeParserPort:
        return self._inner

    def bind_llm(self, llm: Any, *, enabled: bool = True) -> None:
        """Late-bind the tier ladder (the container builds it after the parser)."""
        self._llm = llm
        self._enabled = enabled

    # ── port surface ────────────────────────────────────────────────────────
    def parse(self, document_path: str) -> ParsedResume:
        parsed = self._inner.parse(document_path)
        if not self._enabled:
            return self._mark(parsed, verified=False, reason="disabled")
        if self._llm is None:
            return self._mark(parsed, verified=False, reason="no_model")
        if not parsed.raw_text.strip():
            return self._mark(parsed, verified=False, reason="empty_source")
        try:
            return self._verify_and_merge(parsed)
        except LLMNotConfigured:
            # The ladder singleton exists before any model is connected; treat that
            # as the ordinary "no model yet" state, not an error.
            return self._mark(parsed, verified=False, reason="no_model")
        except LLMError as ex:
            log.warning("parse-verify unavailable (%s); returning deterministic parse", ex)
            return self._mark(parsed, verified=False, reason="model_error")
        except Exception:  # pragma: no cover - defensive: verify must never break ingest
            log.exception("parse-verify failed unexpectedly; returning deterministic parse")
            return self._mark(parsed, verified=False, reason="verify_error")

    # ── verify call + escalation ───────────────────────────────────────────
    def _verify_and_merge(self, parsed: ParsedResume) -> ParsedResume:
        draft = {
            "full_name": parsed.full_name,
            "email": parsed.email,
            "phone": parsed.phone,
            "work_history": [
                {
                    "title": w.title,
                    "company": w.company,
                    "location": w.location,
                    "start_date": w.start_date,
                    "end_date": w.end_date,
                    "achievements": list(w.achievements),
                }
                for w in parsed.work_history
            ],
            "education": [
                {"name": e.degree, "issuer": e.institution, "year": e.end_year or e.start_year}
                for e in parsed.education
            ],
            "skills": list(parsed.skills),
        }
        user = (
            "SOURCE (résumé text):\n-----\n"
            + parsed.raw_text
            + "\n-----\n\nDRAFT (deterministic parse, may contain errors):\n"
            + json.dumps(draft, ensure_ascii=False)
            + "\n\nReturn the corrected JSON now."
        )
        messages = [
            ChatMessage(role="system", content=_SYSTEM),
            ChatMessage(role="user", content=user),
        ]

        attempts: list[dict[str, Any]] = []
        out = None
        result = None
        escalated = False
        for start_tier in (1, 2):
            result = self._llm.complete(
                messages,
                start_tier=start_tier,
                json_schema=_SCHEMA,
                max_tokens=self._max_tokens,
            )
            out, problem = self._validated(result)
            attempts.append(
                {
                    "start_tier": start_tier,
                    "answered_tier": getattr(result, "tier", start_tier),
                    "model": getattr(result, "model", ""),
                    "ok": problem is None,
                    **({"problem": problem} if problem else {}),
                }
            )
            if problem is None:
                break
            if start_tier == 1:
                escalated = True
                log.info("parse-verify escalating a tier: %s", problem)
        if out is None or attempts[-1].get("problem"):
            return self._mark(
                parsed,
                verified=False,
                reason=str(attempts[-1].get("problem", "malformed_output")),
                attempts=attempts,
            )
        return self._merge(parsed, out, attempts=attempts, escalated=escalated)

    def _json_candidates(self, result: Any):
        """Yield candidate dicts from a completion, most-authoritative first.

        The adapter already parses structured output when ``json_schema`` is given
        (``LLMResult.structured``) — that is tried first, no re-parsing. For plain
        text, mirror the adapter's defensive extraction: strip code fences, try the
        whole string, then every balanced ``{...}`` span in document order (via the
        adapter's brace-/string-aware scanner) — so a decoy object or brace-bearing
        prose before the real JSON never sinks the response; the shape check in
        :meth:`_validated` simply skips non-matching candidates.
        """
        structured = getattr(result, "structured", None)
        if isinstance(structured, dict):
            yield structured
        text = (getattr(result, "text", "") or "").strip()
        if not text:
            return
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if fence:
            text = fence.group(1).strip()
        try:
            whole = json.loads(text)
            if isinstance(whole, dict):
                yield whole
        except Exception:
            pass
        for span in balanced_object_spans(text):
            try:
                obj = json.loads(span)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj

    def _validated(self, result: Any) -> tuple[dict | None, str | None]:
        """Pick + sanity-check a verify response; (out, None) or (None, reason)."""
        for out in self._json_candidates(result):
            if not isinstance(out.get("work_history"), list):
                continue  # decoy/partial object — keep scanning
            conf = out.get("confidence")
            if not isinstance(conf, dict) or not conf:
                continue
            try:
                low = min(float(v) for v in conf.values())
            except Exception:
                continue
            if low < self._floor:
                return None, "low_confidence"
            return out, None
        return None, "malformed_output"

    # ── grounded merge (the slotting contract) ─────────────────────────────
    def _merge(
        self,
        parsed: ParsedResume,
        out: dict,
        *,
        attempts: list[dict[str, Any]],
        escalated: bool,
    ) -> ParsedResume:
        windows = _source_windows(parsed.raw_text)
        cwindows = [_collapse(w) for w in windows]
        wtokens = [set(_tokens(w)) for w in windows]
        dropped: list[str] = []

        def sourced(value: str) -> bool:
            """True when ``value`` traces to ONE local window of the source text.

            Grounding is window-scoped (see :func:`_source_windows`): a value must
            match inside a single run of a few adjacent lines — never against the
            whole document flattened, which would accept phrases assembled across
            section boundaries. Collapse-substring (exact modulo case/punct/
            whitespace) is the rule for titles/companies/skills/names. The ONLY
            lenient path is date-shaped values (:func:`_is_date_like`), where
            token-subsumption lets re-formatted dates pass ("Jun" ~ "June") — but
            all tokens must come from the SAME window (no "Jun 18" assembled from
            two different date lines) and numeric tokens must match a window token
            exactly (years never fuzzy-match).
            """
            cv = _collapse(value)
            if not cv:
                return False
            if any(cv in cw for cw in cwindows):
                return True
            if not _is_date_like(value):
                return False
            toks = _tokens(value)
            for wt in wtokens:
                ok = True
                for t in toks:
                    if t.isdigit():
                        if t not in wt:
                            ok = False
                            break
                    elif not any(s.startswith(t) or t.startswith(s) for s in wt):
                        ok = False
                        break
                if ok:
                    return True
            return False

        def keep(value: object, label: str) -> str:
            v = str(value or "").strip()
            if not v:
                return ""
            if sourced(v):
                return v
            dropped.append(f"{label}:{v[:60]}")
            return ""

        full_name = keep(out.get("full_name"), "full_name") or parsed.full_name
        email = keep(out.get("email"), "email") or parsed.email
        phone = keep(out.get("phone"), "phone") or parsed.phone

        roles: list[WorkHistoryEntry] = []
        for r in (out.get("work_history") or [])[:_MAX_ROLES]:
            if not isinstance(r, dict):
                continue
            title = keep(r.get("title"), "role.title")
            company = keep(r.get("company"), "role.company")
            if not (title or company):
                continue
            ach = tuple(
                a
                for a in (
                    keep(x, "role.achievement")
                    for x in (r.get("achievements") or [])[:_MAX_ACHIEVEMENTS]
                    if isinstance(x, str)
                )
                if a
            )
            roles.append(
                WorkHistoryEntry(
                    title=title,
                    company=company,
                    location=keep(r.get("location"), "role.location"),
                    start_date=keep(r.get("start_date"), "role.start"),
                    end_date=keep(r.get("end_date"), "role.end"),
                    achievements=ach,
                )
            )

        education: list[EducationEntry] = []
        for e in (out.get("education") or [])[:_MAX_EDU]:
            if not isinstance(e, dict):
                continue
            degree = keep(e.get("name"), "edu.name")
            issuer = keep(e.get("issuer"), "edu.issuer")
            if not (degree or issuer):
                continue
            year = keep(e.get("year"), "edu.year")
            education.append(
                EducationEntry(degree=degree, institution=issuer, end_year=year)
            )

        skills: list[str] = []
        seen: set[str] = set()
        for s in (out.get("skills") or [])[:_MAX_SKILLS]:
            if not isinstance(s, str):
                continue
            v = keep(s, "skill")
            key = _collapse(v)
            if v and key not in seen:
                seen.add(key)
                skills.append(v)

        last = attempts[-1]
        verify = {
            "verified": True,
            "model": last.get("model", ""),
            "tier": last.get("answered_tier"),
            "escalated": escalated,
            "attempts": attempts,
            "confidence": out.get("confidence") or {},
            "corrections": [c for c in (out.get("corrections") or []) if isinstance(c, str)][:20],
            "unsourced_dropped": dropped[:20],
        }
        return replace(
            parsed,
            full_name=full_name,
            email=email,
            phone=phone,
            # A corrected section replaces the draft only when it survived grounding
            # with content; an empty correction never erases deterministic data.
            work_history=tuple(roles) or parsed.work_history,
            education=tuple(education) or parsed.education,
            skills=tuple(skills) or parsed.skills,
            extra={**parsed.extra, "verify": verify},
        )

    def _mark(
        self,
        parsed: ParsedResume,
        *,
        verified: bool,
        reason: str = "",
        attempts: list[dict[str, Any]] | None = None,
    ) -> ParsedResume:
        verify: dict[str, Any] = {"verified": verified}
        if reason:
            verify["reason"] = reason
        if attempts:
            verify["attempts"] = attempts
        return replace(parsed, extra={**parsed.extra, "verify": verify})
