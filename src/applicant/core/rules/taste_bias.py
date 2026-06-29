"""Taste-bias rule (FR-LEARN-1/3) — pure, no IO.

The per-campaign learning model accumulates an approve/decline taste signal per
feature value in ``LearningModel.feature_stats`` (e.g.
``{"keyword": {"frontend:decline": 10, "python:approve": 3}}``). Issue #237: this
signal was folded + persisted but **never read** by scoring, so the approve/decline
feedback loop was open.

``taste_bias`` derives a small, bounded, signed multiplier in
``[1 - cap, 1 + cap]`` that scoring applies to the base viability score: a posting
whose text carries a feature value the user has consistently DECLINED is nudged down;
one carrying a consistently APPROVED value is nudged up; a value with mixed / no
history contributes nothing. The bias is deliberately conservative (FR-LEARN-7,
advisory) — it can only bend ranking, never override the user's hard criteria, and a
fresh model with no taste yields exactly ``1.0`` (byte-identical to before).
"""

from __future__ import annotations

#: Max fraction the taste signal can move the base score either way. Kept small so the
#: signal nudges ranking without ever swamping criteria/conversion learning.
_TASTE_CAP = 0.2
#: Confidence ramp: a feature value needs this many net observations to reach the full
#: cap, so a single noisy decline barely moves the needle.
_TASTE_FULL_AT = 8.0


def _value_polarity(slot: dict) -> float:
    """Net approve/decline polarity for one feature, in roughly [-1, 1].

    ``slot`` maps ``"{value}:approve"`` / ``"{value}:decline"`` -> count. Returns the
    summed (approve - decline) lean across the feature's values, ramped by confidence
    so a small sample contributes proportionally less. Positive = approved on net,
    negative = declined on net.
    """
    net = 0
    for label, count in slot.items():
        try:
            c = int(count)
        except (TypeError, ValueError):
            continue
        if label.endswith(":approve"):
            net += c
        elif label.endswith(":decline"):
            net -= c
    if net == 0:
        return 0.0
    # Confidence ramp: |net| / FULL_AT, clamped to 1.0.
    magnitude = min(1.0, abs(net) / _TASTE_FULL_AT)
    return magnitude if net > 0 else -magnitude


def matched_values(feature_stats: dict, haystack: str) -> dict[str, float]:
    """Per-feature net polarity for the feature VALUES that appear in ``haystack``.

    Walks each feature's value buckets; a value is "matched" when its token appears in
    the lowercased ``haystack`` (the posting title + description + criteria text). Only
    matched values contribute, so a posting is biased solely by the taste signals it
    actually carries. Returns ``{feature: polarity}`` for matched features.
    """
    if not feature_stats or not haystack:
        return {}
    hay = haystack.lower()
    out: dict[str, float] = {}
    for feature, slot in feature_stats.items():
        if not isinstance(slot, dict):
            continue
        # Restrict each feature's polarity to the value tokens present in the text.
        present: dict = {}
        for label, count in slot.items():
            value = label.rsplit(":", 1)[0].strip().lower()
            if value and value in hay:
                present[label] = count
        polarity = _value_polarity(present)
        if polarity != 0.0:
            out[feature] = polarity
    return out


def taste_bias(feature_stats: dict, haystack: str, *, cap: float = _TASTE_CAP) -> float:
    """Bounded multiplicative taste bias in ``[1 - cap, 1 + cap]`` for a posting.

    Aggregates the net polarity of every feature value the posting carries (averaged
    so many small signals don't compound past the cap) and maps it onto the cap.
    Returns exactly ``1.0`` when the model has no taste history that matches the
    posting, so a cold campaign scores byte-identically to before (#237).
    """
    matched = matched_values(feature_stats, haystack)
    if not matched:
        return 1.0
    # Average polarity across matched features, then scale by the cap. Averaging (not
    # summing) keeps the bias bounded and stops one verbose feature from dominating.
    avg = sum(matched.values()) / len(matched)
    bias = 1.0 + cap * max(-1.0, min(1.0, avg))
    return max(1.0 - cap, min(1.0 + cap, bias))
