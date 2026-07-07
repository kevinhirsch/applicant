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
import math
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
            # Full shape check (not just work_history): a decoy/partial object
            # missing any required section is skipped, not accepted.
            if not all(isinstance(out.get(k), list) for k in ("work_history", "education", "skills")):
                continue  # decoy/partial object — keep scanning
            conf = out.get("confidence")
            if not isinstance(conf, dict) or not conf:
                continue
            # Confidence is PER-AREA: every content section must be scored by
            # SOME key — a lone {"contact": x} must not vouch for work/
            # education/skills it never scored. Key NAMES stay stem-flexible
            # because live models rename the areas despite the schema (a
            # tier-2 smoke reported "work_history_titles_companies" and
            # "education_certifications"); a model that conforms to neither
            # the schema nor the stems is escalation material, not trusted.
            keys = " ".join(k.lower() for k in conf if isinstance(k, str))
            if not all(stem in keys for stem in ("work", "educat", "skill")):
                continue
            try:
                vals = [float(v) for v in conf.values()]
            except Exception:
                continue
            # Values must be sane self-reports: finite (NaN compares False
            # against the floor and would slip through) and inside [0, 1].
            if not all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in vals):
                continue
            if min(vals) < self._floor:
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

        def _seq_in(needle: list[str], hay: list[str]) -> bool:
            n = len(needle)
            return 0 < n <= len(hay) and any(
                hay[i : i + n] == needle for i in range(len(hay) - n + 1)
            )

        # ── grounding hole-fill ─────────────────────────────────────────────
        # Grounding can punch a HOLE in a corrected entry: the title grounds,
        # a hallucinated company/issuer is dropped, and a half-entry survives.
        # The draft twin — anchored on the SAME surviving field, by strict
        # token-sequence containment either way — refills the hole in place
        # with deterministic source text (grounded by construction). Without
        # this, the restore pass below would append the full draft entry NEXT
        # TO its half-corrected twin (a duplicate role), and a degree-only
        # correction would silently shed the draft's institution.
        def _anchored(a: str, b: str) -> bool:
            ta, tb = _tokens(a), _tokens(b)
            return _seq_in(ta, tb) or _seq_in(tb, ta)

        for i, r in enumerate(roles):
            if bool(r.title) == bool(r.company):
                continue  # complete — nothing to fill
            for w in parsed.work_history:
                if not (w.title and w.company):
                    continue
                if _anchored(r.title, w.title) if r.title else _anchored(r.company, w.company):
                    roles[i] = WorkHistoryEntry(
                        title=r.title or w.title,
                        company=r.company or w.company,
                        location=r.location or w.location,
                        start_date=r.start_date or w.start_date,
                        end_date=r.end_date or w.end_date,
                        achievements=r.achievements or w.achievements,
                    )
                    break

        for i, g in enumerate(education):
            if bool(g.degree) == bool(g.institution):
                continue  # complete — nothing to fill
            for e in parsed.education:
                if not (e.degree and e.institution):
                    continue
                if _anchored(g.degree, e.degree) if g.degree else _anchored(g.institution, e.institution):
                    education[i] = EducationEntry(
                        degree=g.degree or e.degree,
                        institution=g.institution or e.institution,
                        end_year=g.end_year or e.end_year,
                    )
                    break

        # ── silent-omission guard ────────────────────────────────────────────
        # A shape-valid, confident response may simply OMIT items the
        # deterministic parse recovered; replacing the section wholesale would
        # silently erase real history at ingest. But the draft is not clean
        # either — the deterministic parser emits split artifacts (a "degree"
        # carved out of a role title mid-line; a school parsed as a job), so
        # restoration is gated hard, three ways:
        #   * only STRONG entries qualify (work: title AND company; education:
        #     a degree). Half-empty artifacts stay prunable.
        #   * an entry ONE corrected entry accounts for — re-slotted into
        #     another section, kept under a corrected name — is not restored.
        #     Coverage is judged per corrected ENTRY (identity fields joined),
        #     cross-section: a school mis-parsed as a job is covered by the
        #     education entry that now holds it, but the same title or company
        #     merely appearing SOMEWHERE never suppresses (two roles at one
        #     company, one title at two companies — omitting one restores it).
        #   * an education degree must START a source line. The split parser
        #     carves degrees out mid-line (the pre-keyword text lands in
        #     institution), so its artifacts never do; real credential lines
        #     ("BS Computer Science, State University") always do.
        # Every restoration is surfaced in the verify metadata (H2: nothing
        # silent). Deterministic skills come from an explicit skills-section
        # parse, so they are cheap to keep: union them in.
        restored: list[str] = []

        entry_pool: list[list[str]] = [
            toks
            for joined in (
                [f"{r.title} {r.company}" for r in roles]
                + [f"{g.degree} {g.institution}" for g in education]
            )
            if (toks := _tokens(joined))
        ]

        def _seq_in(needle: list[str], hay: list[str]) -> bool:
            n = len(needle)
            return 0 < n <= len(hay) and any(
                hay[i : i + n] == needle for i in range(len(hay) - n + 1)
            )

        def _field_in(field: str, entry: list[str]) -> bool:
            toks = _tokens(field)
            if not toks:
                return True  # an empty field can't argue against coverage
            if _seq_in(toks, entry):
                return True
            # A corrected rename keeps part of the original ("Wells Fargo (via
            # TEKsystems)" → "Wells Fargo"): a shared run of 2+ tokens counts.
            return any(_seq_in(toks[i : i + 2], entry) for i in range(len(toks) - 1))

        def _entry_accounted(*fields: str) -> bool:
            live = [f for f in fields if _tokens(f)]
            if not live:
                return True
            return any(
                all(_field_in(f, entry) for f in live) for entry in entry_pool
            )

        source_lines = parsed.raw_text.splitlines()
        cline_list = [_collapse(ln) for ln in source_lines]
        clines = [c for c in cline_list if c]

        def _line_initial(value: str) -> bool:
            cv = _collapse(value)
            return bool(cv) and any(ln.startswith(cv) for ln in clines)

        def _under_nonwork_heading(value: str) -> bool:
            """True when ``value``'s source line sits under an unambiguous
            non-work section heading (EDUCATION / CERTIFICATIONS / SKILLS…).

            The deterministic work parser ignores headings, so a bullet-less
            "role" filed under one of these is a mis-sectioned non-job line —
            prunable, not a lost role. Deliberately conservative: a heading
            must be short (≤4 words), shouty (≥60% uppercase letters), and
            name a non-work section without any work word — anything less
            certain answers False and the entry stays restorable, because a
            visibly-noisy restoration beats silently losing a real role.
            """
            cv = _collapse(value)
            idx = next((i for i, cl in enumerate(cline_list) if cv and cv in cl), None)
            if idx is None:
                return False
            for i in range(idx - 1, -1, -1):
                raw = source_lines[i].strip()
                if not raw or len(raw.split()) > 4:
                    continue
                alpha = [c for c in raw if c.isalpha()]
                if not alpha or sum(c.isupper() for c in alpha) / len(alpha) < 0.6:
                    continue
                low = raw.lower()
                nonwork = any(k in low for k in (
                    "educat", "certif", "training", "skill", "award", "honor", "license",
                ))
                work = any(k in low for k in (
                    "experience", "employment", "work", "career", "professional",
                ))
                if nonwork or work:
                    return nonwork and not work
            return False

        for w in parsed.work_history:
            if not (w.title and w.company):
                continue  # weak/junk draft entry — the correction may prune it
            if len(roles) >= _MAX_ROLES:
                break
            # Suppression needs title AND company carried by one corrected entry.
            if _entry_accounted(w.title, w.company):
                continue
            if not w.achievements and _under_nonwork_heading(w.title):
                continue  # a bullet-less "role" from the education/certs section
            roles.append(w)
            restored.append(f"role:{w.title[:40]} @ {w.company[:30]}")

        for e in parsed.education:
            if not e.degree or not _line_initial(e.degree):
                continue  # split artifact or half-empty — the correction may prune it
            if len(education) >= _MAX_EDU:
                break
            # The credential NAME is the identity — an institution kept under a
            # different credential is a different credential.
            if not _entry_accounted(e.degree):
                education.append(e)
                restored.append(f"education:{e.degree[:40]}")

        for s in parsed.skills:
            key = _collapse(s)
            if key and key not in seen and len(skills) < _MAX_SKILLS:
                seen.add(key)
                skills.append(s)
                restored.append(f"skill:{s[:30]}")

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
            # Draft data the correction omitted but this layer kept (visible in
            # review, H2: a restoration is never silent — so never truncated;
            # the section caps above already bound this list).
            "restored_from_draft": restored,
        }
        return replace(
            parsed,
            full_name=full_name,
            email=email,
            phone=phone,
            # A corrected section replaces the draft only when it survived grounding
            # with content; an empty correction never erases deterministic data, and
            # the silent-omission guard above restores strong entries it left out.
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
