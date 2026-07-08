"""P2-5 — the citable truthfulness claim, with its reproducible artifact.

THE CLAIM, exactly as it may be marketed: **"It rewrites freely; it never
invents facts."** Under the default BALANCED truth policy the engine may
rewrite prose without restriction, while every invented fact-class token —
employer, title, credential/certification, date, number/metric — is DETECTED
and surfaced for human review before anything can be approved or sent; under
STRICT the same inventions hard-fail. The over-broad promise the product does
NOT make ("it never rewrites") is deliberately absent.

This suite IS the evidence: one red-team case per fact class, each asserted
under BOTH policies, plus the rewrite-freedom case proving faithful
rephrasing passes untouched. Companion invariant: the human-final-say chain
(``test_final_say_invariant.py``) proves a surfaced fact can never reach a
submission without an explicit human approval.

Reproduce:
    DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
      uv run pytest -q tests/unit/test_truth_claim_evidence.py
"""

from __future__ import annotations

import pytest

from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.material_service import MaterialService
from applicant.core.errors import TruthfulnessViolation
from applicant.core.rules.truthfulness import TruthPolicy

#: The candidate's REAL history — the ground truth every case checks against.
TRUE_SOURCE = (
    "Senior Data Engineer at Initech from June 2019 to March 2023. "
    "Built Python and SQL pipelines processing 2 million records daily. "
    "Led a team of 5 engineers. Certified Kubernetes Administrator. "
    "BS Computer Science, State University, 2015."
)


@pytest.fixture
def svc() -> MaterialService:
    return MaterialService(InMemoryStorage(), llm=None, resume_tailoring=LatexTailor())


#: One red-team case per fact class: (label, generated text containing exactly
#: one invented fact, the invented token expected in the flag list).
FACT_CLASS_CASES = [
    (
        "employer",
        "Senior Data Engineer at Globex, building Python and SQL pipelines.",
        "globex",
    ),
    (
        "title",
        "Chief Architect at Initech, building Python and SQL pipelines.",
        "architect",
    ),
    (
        "credential",
        "Certified Snowflake Administrator; built Python and SQL pipelines.",
        "snowflake",
    ),
    (
        "date",
        "Senior Data Engineer at Initech from June 2012, Python and SQL pipelines.",
        "2012",
    ),
    (
        "number",
        "Built Python and SQL pipelines processing 900 million records daily.",
        "900",
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize("label,generated,invented", FACT_CLASS_CASES, ids=[c[0] for c in FACT_CLASS_CASES])
def test_an_invented_fact_is_surfaced_under_balanced(svc, label, generated, invented):
    """BALANCED (the default): the invention is DETECTED and returned for
    review — never silently accepted, never silently blocked."""
    flagged = svc.assert_no_fabrication(
        TRUE_SOURCE, generated, policy=TruthPolicy.BALANCED
    )
    joined = " ".join(flagged).lower()
    assert invented in joined, (
        f"the invented {label} must be flagged; got {flagged!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("label,generated,invented", FACT_CLASS_CASES, ids=[c[0] for c in FACT_CLASS_CASES])
def test_an_invented_fact_hard_fails_under_strict(svc, label, generated, invented):
    """STRICT: the same invention refuses to pass at all."""
    with pytest.raises(TruthfulnessViolation):
        svc.assert_no_fabrication(TRUE_SOURCE, generated, policy=TruthPolicy.STRICT)


@pytest.mark.unit
def test_a_faithful_resume_rewrite_passes_both_policies_with_zero_flags(svc):
    """Rewriting is FREE — résumé-class mode. The strict per-token check reads
    facts, not order: the same claims aggressively re-ordered and re-framed
    produce no flags under either policy. (Word-FORM changes belong to the
    prose mode below — the résumé-class check is deliberately verbatim about
    every claim token, so "processing" cannot silently become "processed".)"""
    rewrite = (
        "At Initech I spent June 2019 to March 2023 as a Senior Data Engineer: "
        "SQL and Python pipelines processing 2 million records daily, and I "
        "led a team of 5 engineers. Certified Kubernetes Administrator; "
        "BS Computer Science (State University, 2015)."
    )
    assert svc.assert_no_fabrication(TRUE_SOURCE, rewrite, policy=TruthPolicy.BALANCED) == []
    assert svc.assert_no_fabrication(TRUE_SOURCE, rewrite, policy=TruthPolicy.STRICT) == []


@pytest.mark.unit
def test_a_full_prose_rephrase_passes_both_policies_with_zero_flags(svc):
    """Rewriting is FREE — prose mode (cover letters / essays). A complete
    re-wording with new vocabulary passes as long as every named entity,
    credential, and figure stays real."""
    prose = (
        "My years at Initech taught me how to keep 2 million records flowing "
        "through Python and SQL every single day, and how to bring 5 engineers "
        "along with me while doing it."
    )
    assert (
        svc.assert_no_fabrication(TRUE_SOURCE, prose, prose=True, policy=TruthPolicy.BALANCED)
        == []
    )
    assert (
        svc.assert_no_fabrication(TRUE_SOURCE, prose, prose=True, policy=TruthPolicy.STRICT)
        == []
    )


@pytest.mark.unit
def test_free_prose_mode_still_catches_entity_shaped_inventions(svc):
    """Cover letters / essays run the entity-shaped check: open narrative
    vocabulary passes, but a named invented credential still flags."""
    prose = (
        "I am excited to bring my passion for scalable systems to this role. "
        "As an AWS Certified Solutions Architect, I thrive in fast-moving teams."
    )
    flagged = svc.assert_no_fabrication(
        TRUE_SOURCE, prose, prose=True, policy=TruthPolicy.BALANCED
    )
    joined = " ".join(flagged).lower()
    assert "aws" in joined or "architect" in joined
    # The narrative filler itself ("excited", "passion", "thrive") never flags.
    assert not any(w in joined for w in ("excited", "passion", "thrive"))


@pytest.mark.unit
def test_the_default_policy_is_balanced_surface_not_block(svc):
    """The shipped default: no policy argument means BALANCED — surfaced
    flags, no exception (the owner's directive, pinned)."""
    flagged = svc.assert_no_fabrication(
        TRUE_SOURCE, "Senior Data Engineer at Globex."
    )
    assert flagged, "the invention is surfaced"
