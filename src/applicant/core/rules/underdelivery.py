"""Item-level underdelivery statements (H2 — no silent underdelivery).

The honesty invariants (CLAUDE.md principle #6 / Phase 1.5 H2) require that when
the engine did LESS than asked — a discovery source that returned nothing or
errored, a pre-fill that left fields blank or failed to fill some — the shortfall
is stated **at the item level**, never shipped as a quiet generic result that
reads as success.

This module is the pure vocabulary for those statements: given the raw facts a
run recorded (per-source outcomes, per-field fill accounting), it produces the
structured, plain-language shortfall records the digest / pending-action
surfaces attach to the item itself. Pure, deterministic, no IO — enforced in the
core so a caller cannot opt the honesty out.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Per-source outcome statuses a discovery run can record (see
#: ``JobSpySearxngDiscovery.search``'s ``last_source_outcomes``).
SOURCE_OK = "ok"
SOURCE_EMPTY = "empty"
SOURCE_ERROR = "error"
SOURCE_RATE_LIMITED = "rate_limited"

#: Statuses that constitute an underdelivery worth a per-item statement.
SHORTFALL_STATUSES = frozenset({SOURCE_EMPTY, SOURCE_ERROR, SOURCE_RATE_LIMITED})

#: Cap on how many field labels one shortfall summary names inline (the full
#: list still travels in the structured record).
_MAX_NAMED_FIELDS = 5


def source_label(source_key: str) -> str:
    """A plain-language label for a discovery source key.

    ``"jobspy:indeed"`` -> ``"Indeed"``, ``"searxng"`` -> ``"Web search"``,
    ``"rss:hn-hiring"`` -> ``"Hn-hiring feed"`` — mirrors the front-door's own
    source labelling so the same source reads the same everywhere. Never returns
    an empty string for a non-empty key.
    """
    key = (source_key or "").strip()
    if not key:
        return "an unnamed source"
    prefix, _, tail = key.partition(":")
    if not tail:
        prefix, tail = "", prefix
    if tail.lower() == "searxng":
        return "Web search"
    label = tail[:1].upper() + tail[1:]
    if prefix.lower() == "rss":
        return f"{label} feed"
    return label


def source_shortfall_message(
    source_key: str, status: str, *, error: str | None = None
) -> str | None:
    """One plain-language sentence for a source that underdelivered, else ``None``.

    ``SOURCE_OK`` (and any unknown status) yields ``None`` — only a real
    shortfall gets a statement, so an absent message is a real "this source
    delivered" and never a swallowed degrade.
    """
    label = source_label(source_key)
    if status == SOURCE_EMPTY:
        return f"{label} returned nothing on the last check."
    if status == SOURCE_ERROR:
        detail = f" ({error})" if error else ""
        return f"{label} could not be searched on the last check{detail}."
    if status == SOURCE_RATE_LIMITED:
        return f"{label} was skipped on the last check to avoid over-asking — it will be retried."
    return None


def discovery_shortfalls(outcomes: Sequence[dict]) -> list[dict]:
    """Filter per-source run outcomes down to the ones that underdelivered.

    ``outcomes`` rows are ``{"source_key": str, "status": str, "found": int,
    "error": str | None}`` (extra keys tolerated). Returns one structured record
    per shortfall — source key, status, count, and the ready-made plain-language
    ``message`` — in input order. Sources that delivered (``ok``) produce
    nothing, so an empty result is a genuinely clean run.
    """
    shortfalls: list[dict] = []
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        key = str(outcome.get("source_key") or "")
        status = str(outcome.get("status") or "")
        error = outcome.get("error")
        message = source_shortfall_message(
            key, status, error=str(error) if error else None
        )
        if message is None:
            continue
        try:
            found = int(outcome.get("found") or 0)
        except (TypeError, ValueError):
            found = 0
        shortfalls.append(
            {
                "source_key": key,
                "status": status,
                "found": found,
                "error": str(error) if error else None,
                "message": message,
            }
        )
    return shortfalls


def _labels(items: Sequence[dict], *, fallback: str) -> list[str]:
    """Human labels for field/question records (label, else selector, else fallback)."""
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip() or str(
            item.get("selector") or ""
        ).strip()
        out.append(label or fallback)
    return out


def _named(labels: Sequence[str]) -> str:
    """Inline-name up to ``_MAX_NAMED_FIELDS`` labels: ``"A, B, C and 2 more"``."""
    shown = list(labels[:_MAX_NAMED_FIELDS])
    rest = len(labels) - len(shown)
    text = ", ".join(shown)
    if rest > 0:
        text += f" and {rest} more"
    return text


def prefill_shortfall(
    *,
    fields_detected: int,
    fields_filled: int,
    failed_fields: Sequence[dict] = (),
    deferred_questions: Sequence[dict] = (),
) -> dict | None:
    """The item-level shortfall of one pre-fill run, or ``None`` when it fully delivered.

    A run fully delivered when every detected field was filled and nothing
    failed or was deferred — only then is there no statement to make. Otherwise
    the record carries the counts, the affected field/question labels, and a
    ready-made plain-language ``summary`` the review surfaces show verbatim, so
    an incomplete pre-fill can never read as a complete one (H2).
    """
    detected = max(0, int(fields_detected))
    filled = max(0, int(fields_filled))
    failed = [f for f in failed_fields if isinstance(f, dict)]
    deferred = [q for q in deferred_questions if isinstance(q, dict)]
    unfilled = max(0, detected - filled)
    if unfilled == 0 and not failed and not deferred:
        return None
    parts = [f"I filled {filled} of the {detected} fields I found"]
    failed_labels = _labels(failed, fallback="a field")
    if failed_labels:
        parts.append(
            f"{len(failed_labels)} failed to fill ({_named(failed_labels)})"
        )
    question_labels = _labels(deferred, fallback="a question")
    if question_labels:
        noun = "question needs" if len(question_labels) == 1 else "questions need"
        parts.append(
            f"{len(question_labels)} {noun} your answer ({_named(question_labels)})"
        )
    # Failed fills and deferred questions are both detected-but-unfilled; the
    # remainder is what was skipped/left blank (optional fields, unmapped
    # inputs) — named as its own count so nothing hides inside another bucket.
    leftover = unfilled - len(failed_labels) - len(question_labels)
    if leftover > 0:
        parts.append(f"{leftover} left blank")
    summary = (
        "; ".join(parts)
        + " — double-check the form in the live view before submitting."
    )
    return {
        "fields_detected": detected,
        "fields_filled": filled,
        "fields_unfilled": unfilled,
        "failed_fields": failed_labels,
        "deferred_questions": question_labels,
        "summary": summary,
    }
