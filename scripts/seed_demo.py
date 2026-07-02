#!/usr/bin/env python
"""Seed a realistic demo dataset for one owner/campaign (dev/playtest only).

This is the single blocker-buster for *rendering / auditing the trust-core flows*:
without rows in the database the Portal is empty, the digest has nothing to review,
the redline session has no material, and live-takeover / chat have nothing to point
at. This script inserts a small, coherent, *hand-built* dataset for ONE campaign so
every one of those surfaces lights up in the white-labeled front-door.

What it creates (all scoped to one demo campaign):

* a **campaign** (the scope root);
* a handful of discovered **postings**, each already carrying a durable
  ``viability_score`` + rationale so the digest can render scored rows;
* the matching **applications** (one per posting) parked in states that make the
  Portal/redline/takeover flows visible — a ``DIGESTED`` role awaiting approval, a
  ``MATERIAL_REVIEW`` role with a generated résumé under redline, an
  ``AWAITING_FINAL_APPROVAL`` role for the live-takeover final-submit gate, and a
  ``BLOCKED_QUESTION`` role behind an agent question;
* a **résumé variant** + a generated **material** (résumé) with an OPEN
  **revision session** (a couple of add/subtract turns) so the redline UI has state;
* **3–4 Portal pending-actions of DIFFERENT kinds** — digest-approval,
  material-review, agent-question, final-approval — so the Portal home base is
  populated with each card type.

Design (mirrors ``onboarding_seed.py`` — pure derivation split from IO):

* ``build_demo_*()`` are **pure** entity builders (no IO) — unit-tested directly.
* :func:`build_demo_bundle` assembles them into one :class:`DemoBundle`.
* :func:`persist` is the ONLY IO: it writes the bundle through the REAL repositories
  (``SqlAlchemyStorage`` over the app's own session factory), never hand-rolled SQL.

Safety:

* Execution is gated behind ``APPLICANT_ALLOW_SEED=1``. Without it the script refuses
  to run (so it can never fire in prod by accident).
* Re-running is safe: the repos ``merge`` by id (upsert) and the pending actions are
  deduped, so a second run replaces the demo rows rather than piling up duplicates.

Invocation::

    APPLICANT_ALLOW_SEED=1 DATABASE_URL=postgresql+psycopg://applicant:applicant@localhost:5432/applicant \\
        uv run python scripts/seed_demo.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.entities.revision_session import (
    RevisionSession,
    RevisionStatus,
    RevisionTurn,
)
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    PendingActionId,
    ResumeVariantId,
    RevisionSessionId,
)
from applicant.core.state_machine import ApplicationState

# Stable, namespaced ids so a re-seed UPSERTS the same demo rows rather than
# accumulating new ones. Everything hangs off this one demo campaign id.
DEMO_CAMPAIGN_ID = "demo-campaign"

# Pending-action kinds (kept in sync with PendingActionsService constants). Duplicated
# here as literals so the pure builders have no service dependency and unit-test in
# isolation.
KIND_DIGEST_APPROVAL = "digest_approval"
KIND_MATERIAL_REVIEW = "material_review"
KIND_AGENT_QUESTION = "agent_question"
KIND_FINAL_APPROVAL = "final_approval"


@dataclass(frozen=True)
class DemoBundle:
    """The full, coherent demo dataset (pure — no IO)."""

    campaign: Campaign
    postings: tuple[JobPosting, ...]
    applications: tuple[Application, ...]
    resume_variant: ResumeVariant
    material: GeneratedDocument
    revision_session: RevisionSession
    pending_actions: tuple[PendingAction, ...] = field(default_factory=tuple)


# --- pure builders ---------------------------------------------------------


def build_demo_campaign(campaign_id: str = DEMO_CAMPAIGN_ID) -> Campaign:
    """The demo campaign — the scope root everything else references."""
    return Campaign(
        id=CampaignId(campaign_id),
        name="Demo — Senior Backend Engineer search",
        run_mode=RunMode.CONTINUOUS,
        throughput_target=15,
        active=True,
        criteria={
            "titles": ["Senior Backend Engineer", "Staff Software Engineer"],
            "locations": ["Remote (US)", "New York, NY"],
            "work_modes": ["remote", "hybrid"],
            "salary_floor": "$180,000",
        },
    )


#: The demo postings, as plain dicts so the builder is trivially inspectable. Each
#: carries a viability score (0..1) + a rationale so the digest renders scored rows.
_DEMO_POSTINGS: tuple[dict, ...] = (
    {
        "suffix": "acme",
        "title": "Senior Backend Engineer",
        "company": "Acme Robotics",
        "location": "Remote (US)",
        "work_mode": "remote",
        "salary": "$185,000 - $215,000",
        "score": 0.88,
        "why": "Strong match on Python/Postgres backend depth and remote-first team.",
    },
    {
        "suffix": "globex",
        "title": "Staff Software Engineer, Platform",
        "company": "Globex",
        "location": "New York, NY",
        "work_mode": "hybrid",
        "salary": "$210,000 - $250,000",
        "score": 0.81,
        "why": "Platform/infra focus aligns with your distributed-systems history.",
    },
    {
        "suffix": "initech",
        "title": "Backend Engineer, Payments",
        "company": "Initech",
        "location": "Remote (US)",
        "work_mode": "remote",
        "salary": "$175,000 - $200,000",
        "score": 0.74,
        "why": "Payments domain is new to you but the core stack is a close fit.",
    },
    {
        "suffix": "hooli",
        "title": "Senior Engineer, Search Infrastructure",
        "company": "Hooli",
        "location": "Remote (US)",
        "work_mode": "remote",
        "salary": "$190,000 - $230,000",
        "score": 0.79,
        "why": "Search-infra scale matches roles you've converted on before.",
    },
)


def build_demo_postings(campaign_id: str = DEMO_CAMPAIGN_ID) -> tuple[JobPosting, ...]:
    """A handful of scored, discovered postings for the demo campaign."""
    cid = CampaignId(campaign_id)
    out: list[JobPosting] = []
    for spec in _DEMO_POSTINGS:
        pid = JobPostingId(f"demo-posting-{spec['suffix']}")
        out.append(
            JobPosting(
                id=pid,
                campaign_id=cid,
                title=spec["title"],
                company=spec["company"],
                source_url=f"https://jobs.example.com/{spec['suffix']}/{spec['suffix']}-role",
                location=spec["location"],
                work_mode=spec["work_mode"],
                salary=spec["salary"],
                description=(
                    f"{spec['title']} at {spec['company']}. "
                    "Build and operate high-throughput backend services."
                ),
                source_key="demo",
                viability_score=spec["score"],
                rationale={"summary": spec["why"], "score": spec["score"]},
            )
        )
    return tuple(out)


def build_demo_resume_variant(
    campaign_id: str = DEMO_CAMPAIGN_ID,
) -> ResumeVariant:
    """A tailored résumé variant (the parent material for the redline session)."""
    return ResumeVariant(
        id=ResumeVariantId("demo-variant-globex"),
        campaign_id=CampaignId(campaign_id),
        storage_path="demo/variants/globex-staff.tex",
        parent_id=None,
        targeted_jd_signature="staff-platform-globex",
        approved=False,
        fit_scores={"coverage": 0.82, "missing_terms": ["Kubernetes", "gRPC"]},
    )


def build_demo_material(
    application_id: str,
    campaign_id: str = DEMO_CAMPAIGN_ID,
) -> GeneratedDocument:
    """A generated résumé material under review (the redline target)."""
    return GeneratedDocument(
        id=GeneratedDocumentId("demo-material-globex-resume"),
        campaign_id=CampaignId(campaign_id),
        application_id=ApplicationId(application_id),
        type=DocumentType.RESUME,
        content=(
            "SUMMARY\n"
            "Senior backend engineer with 8+ years building distributed services on "
            "Python and Postgres. Led platform reliability work reducing p99 latency 40%.\n\n"
            "EXPERIENCE\n"
            "- Platform Engineer, Contoso: owned the ingestion pipeline (1B events/day).\n"
            "- Backend Engineer, Umbrella: shipped the billing service rewrite.\n"
        ),
        storage_path="demo/materials/globex-staff-resume.pdf",
        approved=False,
    )


def build_demo_revision_session(
    material_id: str,
) -> RevisionSession:
    """An OPEN redline session with a couple of add/subtract/free-text turns."""
    return RevisionSession(
        id=RevisionSessionId("demo-revision-globex"),
        material_id=GeneratedDocumentId(material_id),
        status=RevisionStatus.OPEN,
        turns=(
            RevisionTurn(
                kind="add",
                instruction="Add a bullet about the Kubernetes migration.",
                ai_response="Added: 'Led migration of 40 services to Kubernetes with zero downtime.'",
            ),
            RevisionTurn(
                kind="subtract",
                instruction="Drop the line about the internal wiki.",
                ai_response="Removed the internal-wiki bullet from the Umbrella role.",
            ),
            RevisionTurn(
                kind="free_text",
                instruction="Make the summary a touch more concise.",
                ai_response="Tightened the summary to two sentences.",
            ),
        ),
        redline_state={
            "added": ["Led migration of 40 services to Kubernetes with zero downtime."],
            "removed": ["Maintained the internal engineering wiki."],
        },
    )


def build_demo_applications(
    postings: tuple[JobPosting, ...],
    resume_variant: ResumeVariant,
    campaign_id: str = DEMO_CAMPAIGN_ID,
) -> tuple[Application, ...]:
    """One application per posting, parked in states that light up each flow.

    The states are assigned deterministically by posting order so the four
    trust-core surfaces each have a subject:

    * posting 0 → ``DIGESTED`` (awaiting digest approval),
    * posting 1 → ``MATERIAL_REVIEW`` (résumé under redline),
    * posting 2 → ``AWAITING_FINAL_APPROVAL`` (live-takeover final submit),
    * posting 3 → ``BLOCKED_QUESTION`` (agent paused with a question).
    """
    cid = CampaignId(campaign_id)
    states = (
        ApplicationState.DIGESTED,
        ApplicationState.MATERIAL_REVIEW,
        ApplicationState.AWAITING_FINAL_APPROVAL,
        ApplicationState.BLOCKED_QUESTION,
    )
    out: list[Application] = []
    for idx, posting in enumerate(postings):
        state = states[idx] if idx < len(states) else ApplicationState.DIGESTED
        # Only the material-review application carries the tailored variant.
        variant_id = (
            resume_variant.id if state == ApplicationState.MATERIAL_REVIEW else None
        )
        out.append(
            Application(
                id=ApplicationId(f"demo-app-{posting.id.rsplit('-', 1)[-1]}"),
                campaign_id=cid,
                posting_id=posting.id,
                status=state,
                role_name=posting.title,
                job_title=posting.title,
                work_mode=posting.work_mode,
                root_url=posting.source_url,
                resume_variant_id=variant_id,
                sandbox_session_url=(
                    "https://takeover.example.com/session/demo"
                    if state == ApplicationState.AWAITING_FINAL_APPROVAL
                    else None
                ),
            )
        )
    return tuple(out)


def build_demo_pending_actions(
    applications: tuple[Application, ...],
    postings: tuple[JobPosting, ...],
    material: GeneratedDocument,
    campaign_id: str = DEMO_CAMPAIGN_ID,
) -> tuple[PendingAction, ...]:
    """Four Portal pending-actions, one of EACH kind, tied to the demo rows.

    A ``dedup_key`` is stamped into each payload (mirroring
    ``PendingActionsService.materialize``) so a re-seed replaces rather than
    duplicates them, and so the resolve-by-dedup path can clear them.
    """
    cid = CampaignId(campaign_id)
    by_state = {a.status: a for a in applications}
    posting_by_id = {p.id: p for p in postings}

    actions: list[PendingAction] = []

    # 1) digest-approval — keyed on a posting id (no Application FK yet).
    digest_app = by_state.get(ApplicationState.DIGESTED)
    if digest_app is not None:
        posting = posting_by_id.get(digest_app.posting_id)
        pid = str(digest_app.posting_id)
        actions.append(
            PendingAction(
                id=PendingActionId("demo-pending-digest"),
                campaign_id=cid,
                kind=KIND_DIGEST_APPROVAL,
                title=f"Approve applying to {posting.title if posting else 'a new role'}",
                application_id=None,
                payload={
                    "posting_id": pid,
                    "company": posting.company if posting else "",
                    "viability_score": round((posting.viability_score or 0) * 100)
                    if posting
                    else 0,
                    "dedup_key": f"digest_approval:{pid}",
                },
            )
        )

    # 2) material-review — the résumé under redline.
    review_app = by_state.get(ApplicationState.MATERIAL_REVIEW)
    if review_app is not None:
        actions.append(
            PendingAction(
                id=PendingActionId("demo-pending-material"),
                campaign_id=cid,
                kind=KIND_MATERIAL_REVIEW,
                title="Review your tailored résumé before it's used",
                application_id=review_app.id,
                payload={
                    "material_id": str(material.id),
                    "material_type": material.type.value,
                    "dedup_key": f"material_review:{material.id}",
                },
            )
        )

    # 3) agent-question — the paused, blocked application.
    question_app = by_state.get(ApplicationState.BLOCKED_QUESTION)
    if question_app is not None:
        actions.append(
            PendingAction(
                id=PendingActionId("demo-pending-question"),
                campaign_id=cid,
                kind=KIND_AGENT_QUESTION,
                title="This role asks for a security clearance — do you hold one?",
                application_id=question_app.id,
                payload={
                    "question": "This role asks for a security clearance — do you hold one?",
                    "dedup_key": "agent_question:demo-clearance",
                },
            )
        )

    # 4) final-approval — the live-takeover final-submit gate.
    final_app = by_state.get(ApplicationState.AWAITING_FINAL_APPROVAL)
    if final_app is not None:
        posting = posting_by_id.get(final_app.posting_id)
        actions.append(
            PendingAction(
                id=PendingActionId("demo-pending-final"),
                campaign_id=cid,
                kind=KIND_FINAL_APPROVAL,
                title=f"Ready to submit — final approval for {posting.company if posting else 'this role'}",
                application_id=final_app.id,
                payload={
                    "sandbox_session_url": final_app.sandbox_session_url,
                    "dedup_key": f"final_approval:{final_app.id}",
                },
            )
        )

    return tuple(actions)


def build_demo_bundle(campaign_id: str = DEMO_CAMPAIGN_ID) -> DemoBundle:
    """Assemble the full, coherent demo dataset (pure — no IO)."""
    campaign = build_demo_campaign(campaign_id)
    postings = build_demo_postings(campaign_id)
    resume_variant = build_demo_resume_variant(campaign_id)
    applications = build_demo_applications(postings, resume_variant, campaign_id)

    # The material + redline hang off the material-review application.
    review_app = next(
        (a for a in applications if a.status == ApplicationState.MATERIAL_REVIEW),
        applications[0],
    )
    material = build_demo_material(str(review_app.id), campaign_id)
    revision_session = build_demo_revision_session(str(material.id))

    pending_actions = build_demo_pending_actions(
        applications, postings, material, campaign_id
    )

    return DemoBundle(
        campaign=campaign,
        postings=postings,
        applications=applications,
        resume_variant=resume_variant,
        material=material,
        revision_session=revision_session,
        pending_actions=pending_actions,
    )


# --- IO (persistence) ------------------------------------------------------


def persist(storage, bundle: DemoBundle) -> dict[str, int]:
    """Write the demo bundle through the REAL repositories, then commit once.

    Order is FK-safe (campaign → postings/variant → applications → material →
    revision → pending actions). Every repo ``add`` merges by id (upsert), so a
    re-run replaces the demo rows rather than duplicating them. Returns a per-kind
    count for the CLI summary.
    """
    counts: dict[str, int] = {}

    storage.campaigns.add(bundle.campaign)
    counts["campaign"] = 1

    for posting in bundle.postings:
        storage.postings.add(posting)
    counts["postings"] = len(bundle.postings)

    storage.resume_variants.add(bundle.resume_variant)
    counts["resume_variants"] = 1

    for application in bundle.applications:
        storage.applications.add(application)
    counts["applications"] = len(bundle.applications)

    storage.documents.add(bundle.material)
    counts["materials"] = 1

    storage.revisions.add(bundle.revision_session)
    counts["revision_sessions"] = 1

    for action in bundle.pending_actions:
        storage.pending_actions.add(action)
    counts["pending_actions"] = len(bundle.pending_actions)

    storage.commit()
    return counts


def _build_storage():
    """Build a real ``SqlAlchemyStorage`` over the app's own session factory.

    Reuses the exact engine/sessionmaker the container uses (``make_engine`` /
    ``make_session_factory``) against the configured ``DATABASE_URL``. Raises if
    the DB is unreachable — the seed is a write path and must not silently no-op.
    """
    from applicant.adapters.storage.repositories import SqlAlchemyStorage
    from applicant.adapters.storage.session import make_engine, make_session_factory
    from applicant.app.config import get_settings

    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    storage = SqlAlchemyStorage(session_factory())
    if not storage.healthcheck():
        raise RuntimeError(
            "Database healthcheck failed — the demo seed needs a reachable, "
            "migrated Postgres (run `uv run alembic upgrade head` first)."
        )
    return storage


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Gated behind ``APPLICANT_ALLOW_SEED=1``."""
    if os.environ.get("APPLICANT_ALLOW_SEED") != "1":
        print(
            "Refusing to seed demo data: set APPLICANT_ALLOW_SEED=1 to confirm.\n"
            "This inserts DEMO rows and must never run against production by accident.\n\n"
            "  APPLICANT_ALLOW_SEED=1 DATABASE_URL=... uv run python scripts/seed_demo.py",
            file=sys.stderr,
        )
        return 2

    bundle = build_demo_bundle()
    storage = _build_storage()
    counts = persist(storage, bundle)

    print(f"Seeded demo dataset for campaign '{bundle.campaign.id}' ({bundle.campaign.name}):")
    for key in (
        "campaign",
        "postings",
        "resume_variants",
        "applications",
        "materials",
        "revision_sessions",
        "pending_actions",
    ):
        print(f"  {key:18s}: {counts.get(key, 0)}")
    print(
        "\nPortal pending-action kinds: "
        + ", ".join(sorted({a.kind for a in bundle.pending_actions}))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
