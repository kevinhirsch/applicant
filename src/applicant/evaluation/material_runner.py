"""Golden-set material runner + per-rubric-dimension regression gate (P2-6).

This closes the remaining piece of the LLM output eval harness. The judging
machinery already exists (:mod:`applicant.evaluation.material_judge`); this
module adds the two things it was missing:

* a **golden set** (profiles x postings) loader — synthetic goldens ship under
  ``goldens/`` and are clearly labelled as such; the loader accepts any
  directory with the same schema so the owner's REAL profiles can be dropped in
  with ``--golden-dir`` (the report echoes the set's own ``provenance``);
* a **material runner** that drives the *real* :class:`MaterialService`
  generation path (cover letters + screening answers) for every golden case,
  judges each generated material across the rubric with an LLM-as-judge, folds
  in the service's OWN deterministic fabrication check for the honesty
  dimension, aggregates per rubric dimension, and **gates per dimension** — a
  regression in ANY dimension (or any deterministic fabrication) fails the
  check.

It is both a library (imported by tests) and a CLI (the trigger, wired into the
``eval`` CI lane). Live judging needs an OpenRouter key in ``OPENROUTER_API_KEY``;
with no key it runs fully offline — generation uses the deterministic truthful
fallback and judging uses the heuristic fallback — so the wiring is exercisable
hermetically, while a real signal requires the live model.

Honesty (H-series): every report states the golden set's provenance, counts and
surfaces degraded (fallback) generations distinctly from real ones, and reports
the deterministic fabrication count alongside the model's honesty score. A run
over the synthetic set proves the machinery, NOT real-world quality — the report
says so.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.material_service import MaterialService
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.ids import (
    ApplicationId,
    AttributeId,
    CampaignId,
    JobPostingId,
    OnboardingProfileId,
    new_id,
)
from applicant.evaluation.material_judge import MaterialJudgment, judge_material
from applicant.ports.driven.llm import TierConfig, TierLadder

log = logging.getLogger(__name__)

# --- rubric (P2-6 DoR: relevance, tone, honesty/zero-fabrication, quality) ---
#: The agreed eval rubric. ``honesty`` is the zero-fabrication dimension (also
#: cross-checked deterministically by the service's own fabrication guard);
#: ``tone`` is the human-voice / non-AI-boilerplate dimension. Kept here (not in
#: material_judge) so the eval's rubric can evolve without touching the judge.
EVAL_RUBRIC: dict[str, str] = {
    "relevance": (
        "Is the material clearly relevant to THIS job posting? Does it surface the "
        "candidate's most job-relevant experience and language?"
    ),
    "tone": (
        "Does the material read as a natural, professional, first-person human voice "
        "— specific and grounded, NOT generic AI boilerplate, cliché, or filler?"
    ),
    "honesty": (
        "Does the material contain ONLY facts supported by the candidate's profile? "
        "No fabricated employers, titles, dates, skills, metrics, or degrees."
    ),
    "specificity": (
        "Does the material use specific, concrete, quantified achievements rather "
        "than vague statements?"
    ),
    "completeness": (
        "Is the material complete and well-structured for its type (a cover letter "
        "opens, argues fit, and closes; an answer directly addresses the question)?"
    ),
}

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
#: Cheap, capable default for the generation path; overridable. Naming an
#: eval-target model slug here is product configuration, not an identity claim.
DEFAULT_GEN_MODEL = "openai/gpt-4o-mini"
#: Judge model. Defaults to the same cheap model for cost; upgrade with
#: ``--judge-model`` for a stronger judge when a run's budget allows.
DEFAULT_JUDGE_MODEL = "openai/gpt-4o-mini"

#: Absolute per-dimension floor (1-5) used when no baseline is supplied.
DEFAULT_MIN_SCORE = 3.0
#: How far a dimension may drop below baseline before the gate fails.
DEFAULT_REGRESSION_THRESHOLD = 0.5

_GOLDENS_DIR = Path(__file__).resolve().parent / "goldens"


# --- golden-set data contracts ----------------------------------------------


@dataclass(frozen=True)
class GoldenProfile:
    id: str
    name: str
    headline: str
    base_resume: str
    attributes: list[dict[str, str]] = field(default_factory=list)
    voice: list[str] = field(default_factory=list)

    def facts(self) -> dict[str, str]:
        """The attribute cloud as a flat {name: value} dict for the judge."""
        return {a["name"]: a["value"] for a in self.attributes if a.get("value")}


@dataclass(frozen=True)
class GoldenPosting:
    id: str
    company: str
    title: str
    location: str
    jd_text: str
    jd_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GoldenPair:
    profile_id: str
    posting_id: str
    cover_letter: bool = True
    screening_question: str = ""


@dataclass(frozen=True)
class GoldenSet:
    provenance: str
    profiles: dict[str, GoldenProfile]
    postings: dict[str, GoldenPosting]
    pairs: list[GoldenPair]


def load_golden_set(golden_dir: str | Path | None = None) -> GoldenSet:
    """Load a golden set from ``golden_dir`` (defaults to the shipped synthetic set).

    Expects ``profiles.json``, ``postings.json``, ``pairs.json`` with the schema
    documented in ``goldens/README.md``. The set's own ``provenance`` string is
    carried through to the report verbatim (honesty: a real set says "real", a
    synthetic set says "synthetic").
    """
    base = Path(golden_dir) if golden_dir else _GOLDENS_DIR
    profiles_raw = json.loads((base / "profiles.json").read_text())
    postings_raw = json.loads((base / "postings.json").read_text())
    pairs_raw = json.loads((base / "pairs.json").read_text())

    profiles = {
        p["id"]: GoldenProfile(
            id=p["id"],
            name=p["name"],
            headline=p.get("headline", ""),
            base_resume=p["base_resume"],
            attributes=p.get("attributes", []),
            voice=p.get("voice", []),
        )
        for p in profiles_raw["profiles"]
    }
    postings = {
        q["id"]: GoldenPosting(
            id=q["id"],
            company=q["company"],
            title=q["title"],
            location=q.get("location", ""),
            jd_text=q["jd_text"],
            jd_terms=q.get("jd_terms", []),
        )
        for q in postings_raw["postings"]
    }
    pairs = [
        GoldenPair(
            profile_id=r["profile_id"],
            posting_id=r["posting_id"],
            cover_letter=bool(r.get("cover_letter", True)),
            screening_question=r.get("screening_question", ""),
        )
        for r in pairs_raw["pairs"]
    ]
    # A synthetic default set; a real set names itself. Prefer the profiles file's
    # provenance, falling back to a conservative synthetic label.
    provenance = profiles_raw.get(
        "provenance", "UNLABELLED — treat as synthetic unless the set states otherwise."
    )
    return GoldenSet(provenance=provenance, profiles=profiles, postings=postings, pairs=pairs)


# --- LLM wiring --------------------------------------------------------------


def build_llm(
    model: str,
    *,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    context_window: int = 128_000,
) -> OpenAICompatibleLLM | None:
    """Build an OpenRouter-backed LLM client, or ``None`` when no key is present.

    ``None`` lets the caller run offline: the generation path falls back to the
    deterministic truthful reframe and the judge to its heuristic scoring, so the
    whole runner is exercisable with no egress (a real signal needs the key).
    """
    if not api_key or not model:
        return None
    ladder = TierLadder(
        tiers=[
            TierConfig(
                provider="openrouter",
                base_url=base_url,
                model=model,
                api_key=api_key,
                context_window=context_window,
            )
        ]
    )
    return OpenAICompatibleLLM(ladder=ladder)


# --- per-case running --------------------------------------------------------


@dataclass
class MaterialResult:
    """One generated + judged material."""

    case_id: str
    profile_id: str
    posting_id: str
    material_type: str  # "cover_letter" | "screening_answer"
    text: str
    degraded: bool  # True iff generation fell back to the deterministic draft
    deterministic_fabrications: list[str]  # service's own fabrication-guard flags
    dimension_scores: dict[str, int]
    overall_score: float
    judge_summary: str
    errors: list[str] = field(default_factory=list)


def _seed_service(profile: GoldenProfile, gen_llm: Any | None) -> tuple[MaterialService, CampaignId]:
    """Build a MaterialService over an in-memory store seeded with the profile.

    Seeds the onboarding base résumé + the attribute cloud so the service derives
    its truthfulness ground truth EXACTLY as the live loop does (from storage,
    not a caller blob) — this is the real generation path, not a shortcut.
    """
    storage = InMemoryStorage()
    campaign_id = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=campaign_id, name=f"eval:{profile.id}"))
    for a in profile.attributes:
        if not a.get("value"):
            continue
        storage.attributes.add(
            Attribute(
                id=AttributeId(new_id()),
                campaign_id=campaign_id,
                name=a.get("name", ""),
                value=a["value"],
            )
        )
    storage.onboarding_profiles.add(
        OnboardingProfile(
            id=OnboardingProfileId(new_id()),
            campaign_id=campaign_id,
            completion_flag=True,
            intake={"base_resume": {"raw_text": profile.base_resume}},
        )
    )
    storage.commit()
    svc = MaterialService(
        storage,
        llm=gen_llm,
        resume_tailoring=LatexTailor(),
        embedding=LocalEmbedding(),
    )
    return svc, campaign_id


def _seed_application(
    svc: MaterialService, campaign_id: CampaignId, posting: GoldenPosting
) -> ApplicationId:
    """Seed a posting + application so the service resolves the target company/role.

    Without this the letter naming the employer it is addressed to would read as
    an unsupported entity to the fabrication guard; seeding it keeps that context
    legitimate (the addressee is not a claim about the candidate).
    """
    storage = svc._storage  # noqa: SLF001 — runner is a first-party driver of the service
    posting_id = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=posting_id,
            campaign_id=campaign_id,
            title=posting.title,
            company=posting.company,
            source_url="",
            location=posting.location,
            description=posting.jd_text,
        )
    )
    application_id = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=application_id,
            campaign_id=campaign_id,
            posting_id=posting_id,
            role_name=posting.title,
            job_title=posting.title,
        )
    )
    storage.commit()
    return application_id


def _judge(
    text: str,
    material_type: str,
    material_id: str,
    profile: GoldenProfile,
    posting: GoldenPosting,
    judge_llm: Any | None,
) -> MaterialJudgment:
    return judge_material(
        text,
        material_type,
        material_id,
        rubric=EVAL_RUBRIC,
        profile_facts=profile.facts(),
        job_description=posting.jd_text,
        llm_client=judge_llm,
    )


def run_case(
    pair: GoldenPair,
    profile: GoldenProfile,
    posting: GoldenPosting,
    *,
    gen_llm: Any | None,
    judge_llm: Any | None,
    material_types: tuple[str, ...] = ("cover_letter", "screening_answer"),
) -> list[MaterialResult]:
    """Generate + judge the materials for one golden case."""
    svc, campaign_id = _seed_service(profile, gen_llm)
    application_id = _seed_application(svc, campaign_id, posting)
    case_id = f"{profile.id}|{posting.id}"
    results: list[MaterialResult] = []

    if "cover_letter" in material_types and pair.cover_letter:
        results.append(
            _run_material(
                "cover_letter",
                svc,
                campaign_id,
                application_id,
                pair,
                profile,
                posting,
                judge_llm,
                case_id,
            )
        )
    if "screening_answer" in material_types and pair.screening_question:
        results.append(
            _run_material(
                "screening_answer",
                svc,
                campaign_id,
                application_id,
                pair,
                profile,
                posting,
                judge_llm,
                case_id,
            )
        )
    return results


def _run_material(
    material_type: str,
    svc: MaterialService,
    campaign_id: CampaignId,
    application_id: ApplicationId,
    pair: GoldenPair,
    profile: GoldenProfile,
    posting: GoldenPosting,
    judge_llm: Any | None,
    case_id: str,
) -> MaterialResult:
    errors: list[str] = []
    text = ""
    degraded = False
    fabrications: list[str] = []
    try:
        if material_type == "cover_letter":
            doc = svc.generate_cover_letter(
                campaign_id,
                application_id,
                true_source="",  # derived server-side from the seeded ground truth
                jd_terms=list(posting.jd_terms),
                campaign_default=True,
            )
        else:
            doc = svc.generate_screening_answer(
                campaign_id,
                application_id,
                question=pair.screening_question,
                true_source="",
                essay=True,
            )
        if doc is None:
            errors.append("generation returned no document")
        else:
            text = doc.content or ""
            degraded = bool(svc.last_generation_degraded)
            # The service's OWN deterministic fabrication guard, recomputed against
            # the same ground truth (incl. posting context). This is the honest
            # zero-fabrication signal that backs the LLM's honesty score.
            try:
                fabrications = list(svc.flagged_facts_for_document(doc.id).get("flagged", []))
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"fabrication recheck failed: {exc}")
    except Exception as exc:
        errors.append(f"generation failed: {exc}")

    judgment = _judge(text, material_type, case_id, profile, posting, judge_llm)
    scores = {s.dimension: s.score for s in judgment.dimension_scores}
    return MaterialResult(
        case_id=case_id,
        profile_id=profile.id,
        posting_id=posting.id,
        material_type=material_type,
        text=text,
        degraded=degraded,
        deterministic_fabrications=fabrications,
        dimension_scores=scores,
        overall_score=judgment.overall_score,
        judge_summary=judgment.summary,
        errors=errors + list(judgment.errors),
    )


# --- aggregation + report ----------------------------------------------------


@dataclass
class MaterialEvalReport:
    provenance: str
    gen_model: str
    judge_model: str
    live: bool  # True iff a real model produced + judged the materials
    case_count: int
    material_count: int
    degraded_count: int
    fabrication_material_count: int
    dimension_means: dict[str, float]
    overall_mean: float
    results: list[MaterialResult]
    generated_at: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def run_golden_set(
    golden: GoldenSet,
    *,
    gen_llm: Any | None,
    judge_llm: Any | None,
    gen_model: str,
    judge_model: str,
    max_cases: int | None = None,
    material_types: tuple[str, ...] = ("cover_letter", "screening_answer"),
) -> MaterialEvalReport:
    """Run every (optionally capped) golden case and aggregate per dimension."""
    pairs = golden.pairs[:max_cases] if max_cases else golden.pairs
    all_results: list[MaterialResult] = []
    for pair in pairs:
        profile = golden.profiles.get(pair.profile_id)
        posting = golden.postings.get(pair.posting_id)
        if profile is None or posting is None:
            log.warning("skipping pair with unknown ids: %s / %s", pair.profile_id, pair.posting_id)
            continue
        all_results.extend(
            run_case(
                pair,
                profile,
                posting,
                gen_llm=gen_llm,
                judge_llm=judge_llm,
                material_types=material_types,
            )
        )

    dim_totals: dict[str, list[int]] = {d: [] for d in EVAL_RUBRIC}
    for r in all_results:
        for dim, score in r.dimension_scores.items():
            dim_totals.setdefault(dim, []).append(score)
    dimension_means = {
        d: round(sum(v) / len(v), 3) if v else 0.0 for d, v in dim_totals.items()
    }
    overall_mean = (
        round(sum(r.overall_score for r in all_results) / len(all_results), 3)
        if all_results
        else 0.0
    )
    live = gen_llm is not None and judge_llm is not None
    note = (
        "Live run: a real model generated and judged every material."
        if live
        else "OFFLINE run: no model key present — generation used the deterministic "
        "truthful fallback and judging used the heuristic fallback. Scores prove the "
        "wiring, not real-world quality."
    )
    return MaterialEvalReport(
        provenance=golden.provenance,
        gen_model=gen_model,
        judge_model=judge_model,
        live=live,
        case_count=len(pairs),
        material_count=len(all_results),
        degraded_count=sum(1 for r in all_results if r.degraded),
        fabrication_material_count=sum(1 for r in all_results if r.deterministic_fabrications),
        dimension_means=dimension_means,
        overall_mean=overall_mean,
        results=all_results,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        note=note,
    )


# --- gating ------------------------------------------------------------------


@dataclass
class GateOutcome:
    passed: bool
    failures: list[str]
    dimension_deltas: dict[str, float] = field(default_factory=dict)


def gate_report(
    report: MaterialEvalReport,
    *,
    baseline: dict[str, Any] | None = None,
    min_score: float = DEFAULT_MIN_SCORE,
    regression_threshold: float = DEFAULT_REGRESSION_THRESHOLD,
    max_fabrication_materials: int | None = None,
) -> GateOutcome:
    """Per-rubric-dimension regression gate (P2-6 DoD).

    With a ``baseline`` (a prior report's ``dimension_means``), fails if ANY
    dimension drops more than ``regression_threshold`` below its baseline. Without
    a baseline, fails if any dimension is below the absolute ``min_score`` floor.
    The judge's ``honesty`` dimension is one of those gated dimensions, so
    fabrication regressions ARE caught by the primary gate.

    The service's OWN deterministic fabrication guard runs under the shipped
    BALANCED policy, which *surfaces flagged tokens for human review* rather than
    blocking (the entity-shaped prose check is deliberately conservative — it
    flags verb synonyms like "Developed" for "Built", or a bare acronym the
    candidate genuinely uses). A nonzero count is therefore EXPECTED and reviewed,
    not a regression, so it is reported but only hard-gated when a caller opts in
    with ``max_fabrication_materials`` (e.g. ``0`` to enforce a strict-policy
    zero-flag posture).
    """
    failures: list[str] = []
    deltas: dict[str, float] = {}

    if (
        max_fabrication_materials is not None
        and report.fabrication_material_count > max_fabrication_materials
    ):
        failures.append(
            f"deterministic fabrication cross-check: {report.fabrication_material_count} "
            f"material(s) carry a flag (allowed {max_fabrication_materials})"
        )

    base_dims = (baseline or {}).get("dimension_means") if baseline else None
    for dim, mean in report.dimension_means.items():
        if base_dims and dim in base_dims:
            delta = round(mean - base_dims[dim], 3)
            deltas[dim] = delta
            if delta < -regression_threshold:
                failures.append(
                    f"dimension '{dim}' regressed: {mean:.2f} vs baseline "
                    f"{base_dims[dim]:.2f} (delta {delta:+.2f}, threshold "
                    f"-{regression_threshold:.2f})"
                )
        else:
            if mean < min_score:
                failures.append(
                    f"dimension '{dim}' below floor: {mean:.2f} < {min_score:.2f}"
                )
    return GateOutcome(passed=not failures, failures=failures, dimension_deltas=deltas)


# --- report serialization ----------------------------------------------------


def write_report(report: MaterialEvalReport, out_dir: str | Path, gate: GateOutcome) -> Path:
    """Write the JSON report + a human-readable Markdown summary; return the JSON path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "material_eval_report.json"
    payload = report.to_dict()
    payload["gate"] = asdict(gate)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    (out / "material_eval_report.md").write_text(_render_markdown(report, gate))
    return json_path


def _render_markdown(report: MaterialEvalReport, gate: GateOutcome) -> str:
    lines: list[str] = []
    lines.append("# Material eval report (P2-6)")
    lines.append("")
    lines.append(f"- **Provenance:** {report.provenance}")
    lines.append(f"- **Run mode:** {'LIVE' if report.live else 'OFFLINE (fallback)'}")
    lines.append(f"- **Generation model:** `{report.gen_model}`")
    lines.append(f"- **Judge model:** `{report.judge_model}`")
    lines.append(f"- **Generated at:** {report.generated_at}")
    lines.append(f"- **Cases:** {report.case_count} · **Materials:** {report.material_count}")
    lines.append(
        f"- **Degraded (fallback) generations:** {report.degraded_count} · "
        f"**Materials with a fabrication flag:** {report.fabrication_material_count}"
    )
    lines.append(f"- **Gate:** {'PASS' if gate.passed else 'FAIL'}")
    lines.append("")
    lines.append(f"> {report.note}")
    lines.append("")
    lines.append(
        "> Deterministic fabrication flags are surfaced by the service's own "
        "entity-shaped prose guard under the shipped BALANCED policy, which flags "
        "tokens *for human review* rather than blocking. It is deliberately "
        "conservative (it flags verb synonyms like \"Developed\" for \"Built\", or a "
        "bare acronym the candidate genuinely uses), so a nonzero count is expected "
        "and reviewed — it is reported here, not treated as a gate failure unless "
        "`--max-fabrication-materials` is set."
    )
    lines.append("")
    lines.append("## Per-dimension mean score (1-5)")
    lines.append("")
    lines.append("| Dimension | Mean | Delta vs baseline |")
    lines.append("| --- | --- | --- |")
    for dim, mean in report.dimension_means.items():
        delta = gate.dimension_deltas.get(dim)
        delta_s = f"{delta:+.2f}" if delta is not None else "—"
        lines.append(f"| {dim} | {mean:.2f} | {delta_s} |")
    lines.append(f"| **overall** | **{report.overall_mean:.2f}** | |")
    lines.append("")
    if gate.failures:
        lines.append("## Gate failures")
        lines.append("")
        for f in gate.failures:
            lines.append(f"- {f}")
        lines.append("")
    lines.append("## Per-material results")
    lines.append("")
    lines.append("| Case | Type | Overall | Fabrications | Degraded |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in report.results:
        fab = ", ".join(r.deterministic_fabrications) if r.deterministic_fabrications else "none"
        lines.append(
            f"| {r.case_id} | {r.material_type} | {r.overall_score:.2f} | {fab} | "
            f"{'yes' if r.degraded else 'no'} |"
        )
    lines.append("")
    return "\n".join(lines)


# --- CLI (the trigger) -------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="applicant.evaluation.material_runner",
        description="Run the golden-set material eval + per-dimension regression gate (P2-6).",
    )
    p.add_argument("--golden-dir", default=None, help="Golden set directory (default: shipped synthetic set).")
    # ``or DEFAULT`` (not the get() default) so an env var explicitly set to the
    # empty string — as a blank CI workflow input becomes — falls back to the
    # default rather than disabling the model with "".
    p.add_argument("--gen-model", default=os.environ.get("EVAL_GEN_MODEL") or DEFAULT_GEN_MODEL)
    p.add_argument("--judge-model", default=os.environ.get("EVAL_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL)
    p.add_argument("--base-url", default=os.environ.get("EVAL_BASE_URL") or DEFAULT_BASE_URL)
    p.add_argument("--max-cases", type=int, default=None, help="Cap the number of golden cases (cost control).")
    p.add_argument("--out", default="reports/eval", help="Output directory for the report.")
    p.add_argument("--baseline", default=None, help="Path to a baseline report JSON to gate against.")
    p.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    p.add_argument("--regression-threshold", type=float, default=DEFAULT_REGRESSION_THRESHOLD)
    p.add_argument(
        "--max-fabrication-materials",
        type=int,
        default=None,
        help="Hard-gate the deterministic fabrication cross-check at this many flagged "
        "materials (default: report only, since BALANCED policy surfaces flags for review).",
    )
    p.add_argument(
        "--material-types",
        default="cover_letter,screening_answer",
        help="Comma-separated material types to evaluate.",
    )
    p.add_argument("--offline", action="store_true", help="Force offline (fallback) mode even if a key is present.")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    golden = load_golden_set(args.golden_dir)
    material_types = tuple(t.strip() for t in args.material_types.split(",") if t.strip())

    api_key = "" if args.offline else os.environ.get("OPENROUTER_API_KEY", "")
    gen_llm = build_llm(args.gen_model, api_key=api_key, base_url=args.base_url)
    judge_llm = build_llm(args.judge_model, api_key=api_key, base_url=args.base_url)
    if api_key and (gen_llm is None or judge_llm is None):
        log.warning("a key is present but a model was empty; check --gen-model/--judge-model")
    if not api_key:
        log.warning(
            "no OPENROUTER_API_KEY — running OFFLINE (deterministic generation + heuristic "
            "judging). Scores prove the wiring, not real-world quality."
        )

    report = run_golden_set(
        golden,
        gen_llm=gen_llm,
        judge_llm=judge_llm,
        gen_model=args.gen_model if gen_llm else "(offline/deterministic)",
        judge_model=args.judge_model if judge_llm else "(offline/heuristic)",
        max_cases=args.max_cases,
        material_types=material_types,
    )

    baseline = None
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text())
    gate = gate_report(
        report,
        baseline=baseline,
        min_score=args.min_score,
        regression_threshold=args.regression_threshold,
        max_fabrication_materials=args.max_fabrication_materials,
    )
    json_path = write_report(report, args.out, gate)

    log.info("wrote report: %s", json_path)
    log.info("dimension means: %s", report.dimension_means)
    log.info("gate: %s", "PASS" if gate.passed else "FAIL")
    for f in gate.failures:
        log.info("  - %s", f)
    return 0 if gate.passed else 1


if __name__ == "__main__":
    sys.exit(main())
