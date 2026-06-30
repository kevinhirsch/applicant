"""LLM-as-judge for evaluating generated-material quality (Issue #309).

Evaluates generated resumes and cover letters against a rubric using an
LLM-as-judge pass. Each material receives a quality score (1-5) across
dimensions like truthfulness, relevance, formatting, and completeness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# Default rubric dimensions
DEFAULT_RUBRIC: dict[str, str] = {
    "truthfulness": "Does the material contain only facts supported by the candidate's profile? (No fabricated employers, titles, dates, skills, or degrees.)",
    "relevance": "Is the material relevant to the target job description? Does it highlight matching skills and experience?",
    "completeness": "Does the material cover all expected sections (contact info, summary, experience, education, skills)?",
    "formatting": "Is the material well-formatted, professional, and free of grammar/spelling errors?",
    "specificity": "Does the material use specific, quantifiable achievements rather than vague statements?",
}


@dataclass(frozen=True)
class MaterialQualityScore:
    """Quality score for a single material evaluation dimension."""

    dimension: str
    """The rubric dimension being scored."""

    score: int
    """Score from 1 (poor) to 5 (excellent)."""

    rationale: str
    """Brief rationale for the score."""


@dataclass(frozen=True)
class MaterialJudgment:
    """Complete judgment for one piece of generated material."""

    material_id: str
    """Identifier for the material."""

    material_type: str
    """Type: 'resume', 'cover_letter', 'screening_answer'."""

    overall_score: float
    """Average score across all dimensions (1.0 - 5.0)."""

    dimension_scores: tuple[MaterialQualityScore, ...] = ()
    """Per-dimension scores."""

    summary: str = ""
    """Overall summary of the judgment."""

    errors: tuple[str, ...] = ()
    """Any errors encountered during evaluation."""


def judge_material(
    material_text: str,
    material_type: str,
    material_id: str,
    *,
    rubric: dict[str, str] | None = None,
    profile_facts: dict[str, str] | None = None,
    job_description: str | None = None,
    llm_client: Any | None = None,
) -> MaterialJudgment:
    """Judge a generated material against a rubric.

    Uses LLM-as-judge when an llm_client is provided. Falls back to
    rule-based heuristic scoring when no LLM is available.

    Args:
        material_text: The generated material text.
        material_type: 'resume', 'cover_letter', or 'screening_answer'.
        material_id: Stable identifier for the material.
        rubric: Optional custom rubric dimensions.
        profile_facts: Optional candidate profile facts for truthfulness check.
        job_description: Optional target job description for relevance check.
        llm_client: Optional LLM client for AI-as-judge evaluation.

    Returns:
        MaterialJudgment with scores and summary.
    """
    if rubric is None:
        rubric = DEFAULT_RUBRIC

    scores: list[MaterialQualityScore] = []
    errors: list[str] = []

    for dimension, description in rubric.items():
        try:
            score = _score_dimension(
                dimension=dimension,
                description=description,
                material_text=material_text,
                material_type=material_type,
                profile_facts=profile_facts,
                job_description=job_description,
                llm_client=llm_client,
            )
            scores.append(score)
        except Exception as exc:
            errors.append(f"Failed to score '{dimension}': {exc}")
            scores.append(
                MaterialQualityScore(
                    dimension=dimension, score=1, rationale=f"Error: {exc}"
                )
            )

    if scores:
        overall = sum(s.score for s in scores) / len(scores)
    else:
        overall = 0.0

    summary_parts = []
    if material_type == "resume":
        summary_parts.append(f"Resume quality: {overall:.1f}/5.0")
    elif material_type == "cover_letter":
        summary_parts.append(f"Cover letter quality: {overall:.1f}/5.0")
    else:
        summary_parts.append(f"Material quality: {overall:.1f}/5.0")

    if errors:
        summary_parts.append(f"({len(errors)} evaluation errors)")

    return MaterialJudgment(
        material_id=material_id,
        material_type=material_type,
        overall_score=overall,
        dimension_scores=tuple(scores),
        summary=". ".join(summary_parts),
        errors=tuple(errors),
    )


def _score_dimension(
    dimension: str,
    description: str,
    material_text: str,
    material_type: str,
    profile_facts: dict[str, str] | None = None,
    job_description: str | None = None,
    llm_client: Any | None = None,
) -> MaterialQualityScore:
    """Score a single rubric dimension.

    Uses LLM-as-judge when available, otherwise falls back to heuristics.
    """
    if llm_client is not None:
        return _llm_score_dimension(
            dimension=dimension,
            description=description,
            material_text=material_text,
            material_type=material_type,
            profile_facts=profile_facts,
            job_description=job_description,
            llm_client=llm_client,
        )
    return _heuristic_score_dimension(
        dimension=dimension,
        description=description,
        material_text=material_text,
        material_type=material_type,
        profile_facts=profile_facts,
        job_description=job_description,
    )


def _heuristic_score_dimension(
    dimension: str,
    description: str,
    material_text: str,
    material_type: str,
    profile_facts: dict[str, str] | None = None,
    job_description: str | None = None,
) -> MaterialQualityScore:
    """Score a dimension using rule-based heuristics.

    This is a fallback when no LLM client is available. Scores are
    conservative estimates based on text characteristics.
    """
    text = material_text or ""
    words = text.split()
    word_count = len(words)

    if word_count < 10:
        return MaterialQualityScore(
            dimension=dimension,
            score=1,
            rationale="Material is too short to evaluate (fewer than 10 words).",
        )

    # Truthfulness heuristic: check for unsupported claims
    if dimension == "truthfulness":
        if profile_facts:
            # Check if material references facts from the profile
            mentioned_facts = sum(
                1 for v in profile_facts.values() if v.lower() in text.lower()
            )
            if mentioned_facts >= len(profile_facts) * 0.5:
                return MaterialQualityScore(
                    dimension=dimension,
                    score=4,
                    rationale=f"Material references {mentioned_facts}/{len(profile_facts)} profile facts.",
                )
            return MaterialQualityScore(
                dimension=dimension,
                score=3,
                rationale=f"Only {mentioned_facts}/{len(profile_facts)} profile facts detected.",
            )
        return MaterialQualityScore(
            dimension=dimension,
            score=3,
            rationale="No profile facts available for truthfulness check.",
        )

    # Relevance heuristic: check for job description keywords
    if dimension == "relevance":
        if job_description:
            jd_words = set(job_description.lower().split())
            text_words = set(text.lower().split())
            overlap = len(jd_words & text_words)
            if overlap > 10:
                return MaterialQualityScore(
                    dimension=dimension,
                    score=4,
                    rationale=f"Material shares {overlap} keywords with job description.",
                )
            return MaterialQualityScore(
                dimension=dimension,
                score=3,
                rationale=f"Only {overlap} keyword overlaps with job description.",
            )
        return MaterialQualityScore(
            dimension=dimension,
            score=3,
            rationale="No job description available for relevance check.",
        )

    # Completeness heuristic: check for expected sections
    if dimension == "completeness":
        sections_found = 0
        expected_sections = ["experience", "education", "skills", "summary", "contact"]
        for section in expected_sections:
            if section in text.lower():
                sections_found += 1
        if sections_found >= 3:
            return MaterialQualityScore(
                dimension=dimension,
                score=4,
                rationale=f"Found {sections_found}/5 expected sections.",
            )
        return MaterialQualityScore(
            dimension=dimension,
            score=2,
            rationale=f"Only {sections_found}/5 expected sections found.",
        )

    # Formatting heuristic: basic checks
    if dimension == "formatting":
        score = 3
        rationales: list[str] = []
        if len(text) > 500:
            score += 1
        else:
            rationales.append("Material is short")
        if text.strip().endswith((".", "!", "?")):
            score += 0  # Has sentence endings
        else:
            rationales.append("No sentence-ending punctuation")
        return MaterialQualityScore(
            dimension=dimension,
            score=min(score, 5),
            rationale="; ".join(rationales) if rationales else "Basic formatting checks passed.",
        )

    # Specificity heuristic: look for numbers and metrics
    if dimension == "specificity":
        import re
        numbers = re.findall(r"\d+", text)
        if len(numbers) > 5:
            return MaterialQualityScore(
                dimension=dimension,
                score=4,
                rationale=f"Contains {len(numbers)} quantified metrics/numbers.",
            )
        return MaterialQualityScore(
            dimension=dimension,
            score=2,
            rationale=f"Only {len(numbers)} numbers found; lacks quantified achievements.",
        )

    # Default fallback
    return MaterialQualityScore(
        dimension=dimension,
        score=3,
        rationale="Scored via heuristic fallback.",
    )


def _llm_score_dimension(
    dimension: str,
    description: str,
    material_text: str,
    material_type: str,
    profile_facts: dict[str, str] | None = None,
    job_description: str | None = None,
    llm_client: Any | None = None,
) -> MaterialQualityScore:
    """Score a dimension using an LLM-as-judge.

    Requires an LLM client with a 'complete' method that accepts
    a list of ChatMessage and returns a CompletionResult.
    """
    if llm_client is None:
        return _heuristic_score_dimension(
            dimension=dimension,
            description=description,
            material_text=material_text,
            material_type=material_type,
            profile_facts=profile_facts,
            job_description=job_description,
        )

    try:
        from applicant.ports.driven.llm import ChatMessage

        facts_context = ""
        if profile_facts:
            facts_context = "\nCandidate Profile Facts:\n" + "\n".join(
                f"- {k}: {v}" for k, v in profile_facts.items()
            )

        jd_context = ""
        if job_description:
            jd_context = f"\nTarget Job Description:\n{job_description[:500]}..."

        prompt = (
            f"You are evaluating a {material_type}. Score the following dimension "
            f"from 1 (poor) to 5 (excellent).\n\n"
            f"Dimension: {dimension}\n"
            f"Description: {description}\n"
            f"{facts_context}"
            f"{jd_context}\n\n"
            f"Material:\n{material_text[:2000]}...\n\n"
            f"Respond with a JSON object with keys 'score' (integer 1-5) "
            f"and 'rationale' (brief explanation)."
        )

        result = llm_client.complete(
            [ChatMessage(role="user", content=prompt)],
        )

        import json
        try:
            data = json.loads(result.text)
            score = int(data.get("score", 3))
            rationale = str(data.get("rationale", "LLM-judged"))
        except (json.JSONDecodeError, ValueError, TypeError):
            score = 3
            rationale = "LLM response could not be parsed."

        return MaterialQualityScore(
            dimension=dimension,
            score=max(1, min(5, score)),
            rationale=rationale,
        )

    except Exception as exc:
        logger.warning("LLM scoring failed for '%s': %s", dimension, exc)
        return _heuristic_score_dimension(
            dimension=dimension,
            description=description,
            material_text=material_text,
            material_type=material_type,
            profile_facts=profile_facts,
            job_description=job_description,
        )
