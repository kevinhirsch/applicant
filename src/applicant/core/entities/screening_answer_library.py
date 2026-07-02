"""ScreeningAnswerLibraryEntry entity (product-gaps backlog #20, FR-ANSWER-1).

Screening answers are generated per-application (``MaterialService.generate_
screening_answer``) through the same review gate every other generated material
uses, but users answer the SAME essay/factual questions ("Why do you want to
work here?", "What's your notice period?") over and over across applications.
This entity is the reusable answer bank -- parallel to the résumé variant
library (FR-RESUME-6) -- that lets a previously-approved-worthy answer be reused
or edited for a new application instead of being regenerated fresh every time.

Scoped per campaign (never global/cross-campaign, mirroring the per-campaign
attribute-value scoping FR-ATTR-2 documents for ``FieldMapping``): a candidate
running multiple job searches keeps each search's voice/positioning separate.
Sensitive (EEO/demographic) answers are NEVER stored here -- see
``MaterialService.generate_screening_answer``'s ``ScreeningKind.SENSITIVE``
branch, which is policy-driven and privacy-scoped (FR-ATTR-6, NFR-PRIV-1) and is
deliberately excluded from library persistence.
"""

from __future__ import annotations

from dataclasses import dataclass

from applicant.core.ids import CampaignId, ScreeningAnswerLibraryEntryId


@dataclass(frozen=True)
class ScreeningAnswerLibraryEntry:
    """One reusable, campaign-scoped screening-question answer.

    ``question_key`` is the NORMALIZED question text (see
    ``core.rules.materials.normalize_screening_question``) -- the lookup key so
    minor phrasing differences ("Why do you want to work here?" vs "why do you
    want to work here") still hit the same library entry. ``question_text`` keeps
    the original (last-seen) phrasing for display. ``essay`` records which
    truthfulness check (entity-shaped prose vs strict per-token) the answer was
    generated under, so a reuse re-verifies it against the SAME check.
    """

    id: ScreeningAnswerLibraryEntryId
    campaign_id: CampaignId
    question_key: str
    question_text: str
    answer_text: str
    essay: bool = False
