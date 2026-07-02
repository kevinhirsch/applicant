"""Dev/demo seed — a coherent, realistic dataset for ONE campaign (audit §6, quick-win #49).

Without seeded rows the front-door opens every surface empty: no model, no
campaign, no digest, no redline, no tracker, no Portal actions. That means the
trust-core daily loop (digest -> redline -> approve -> takeover -> submit) can
never be rendered or exercised end to end. This module is the pure-derivation
+ persistence layer that fixes that, gated strictly behind
``APPLICANT_ALLOW_SEED=1`` at the call site (``scripts/seed_demo.py`` for the
CLI, ``applicant.app.routers.dev_seed`` for the HTTP route).

What it produces (all scoped to one demo campaign):

* a **campaign** with real-looking search criteria;
* **seven** discovered **postings**, varied in company/title/location/source,
  each carrying a durable ``viability_score`` + rationale so the digest can
  render scored rows;
* the matching **applications** (one per posting), parked in states that make
  every front-door surface visible: a ``DIGESTED`` role awaiting digest
  approval, a ``MATERIAL_REVIEW`` role with a generated résumé under redline, an
  ``AWAITING_FINAL_APPROVAL`` role for the live-takeover final-submit gate, a
  ``BLOCKED_QUESTION`` role behind an agent question, a ``BLOCKED_MISSING_ATTR``
  role behind a missing-detail prompt, and two post-submission **tracker**
  rows -- one plain ``AWAITING_RESPONSE`` and one ``AWAITING_RESPONSE`` carrying
  a recorded ``interview_invited`` signal;
* a **résumé variant** + a generated **material** (résumé) with an OPEN
  **revision session** (add/subtract/free-text turns) so the redline UI has
  state;
* a **submission snapshot** (the immutable stop-boundary evidence) for the
  interview-signal tracker row;
* **outcome events** (``submitted`` / ``interview_invited``) backing the
  tracker rows' signal badges;
* **six Portal pending-actions of DIFFERENT kinds** -- digest-approval,
  material-review, agent-question, final-approval, missing-detail, and a held
  integral-attribute change awaiting confirm-or-reject -- so the Portal home
  base is populated with each card type the product actually renders.

Design (mirrors ``onboarding_seed.py``): pure derivation split from IO.

* ``build_demo_*()`` are **pure** entity builders (no IO) -- unit-tested directly.
* :func:`build_demo_bundle` assembles them into one :class:`DemoBundle`.
* :func:`persist` is the ONLY IO: it writes the bundle through the REAL
  repositories (whatever ``StoragePort`` the caller passes -- in-memory or the
  real ``SqlAlchemyStorage``), never hand-rolled SQL, so invariants hold and the
  surfaces render the seed exactly as they would for a genuine user.
* :func:`purge` reuses the existing ``StoragePort.purge_campaign`` cascade
  (#363) so resetting the demo data is the same, already-audited delete path
  campaign-deletion uses -- not a bespoke wipe.

Safety: this module performs NO env check itself -- gating is the CALLER's
job (the CLI checks ``APPLICANT_ALLOW_SEED`` before importing/calling
``persist``; the router checks it per-request before resolving the storage
dependency at all). Re-running is safe: every repo ``add`` merges by id
(upsert), so a second run replaces the demo rows rather than piling up
duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign, RunMode
from applicant.core.entities.generated_document import DocumentType, GeneratedDocument
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.entities.revision_session import (
    RevisionSession,
    RevisionStatus,
    RevisionTurn,
)
from applicant.core.entities.submission_snapshot import SubmissionSnapshot
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
    OutcomeEventId,
    PendingActionId,
    ResumeVariantId,
    RevisionSessionId,
    SubmissionSnapshotId,
)
from applicant.core.state_machine import ApplicationState

# Stable, namespaced ids so a re-seed UPSERTS the same demo rows rather than
# accumulating new ones. Everything hangs off this one demo campaign id.
DEMO_CAMPAIGN_ID = "demo-campaign"

# Pending-action kinds (kept in sync with PendingActionsService constants). Duplicated
# here as literals so the pure builders have no service dependency and unit-test in
# isolation (mirrors ``onboarding_seed.py``'s no-IO discipline).
KIND_DIGEST_APPROVAL = "digest_approval"
KIND_MATERIAL_REVIEW = "material_review"
KIND_AGENT_QUESTION = "agent_question"
KIND_FINAL_APPROVAL = "final_approval"
KIND_MISSING_ATTR = "missing_attr"
KIND_INTEGRAL_CHANGE = "integral_change"

_SEED_TIMESTAMP = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class DemoBundle:
    """The full, coherent demo dataset (pure -- no IO)."""

    campaign: Campaign
    postings: tuple[JobPosting, ...]
    applications: tuple[Application, ...]
    resume_variant: ResumeVariant
    material: GeneratedDocument
    revision_session: RevisionSession
    submission_snapshot: SubmissionSnapshot
    outcome_events: tuple[OutcomeEvent, ...] = ()
    pending_actions: tuple[PendingAction, ...] = ()


# --- pure builders ---------------------------------------------------------


def build_demo_campaign(campaign_id: str = DEMO_CAMPAIGN_ID) -> Campaign:
    """The demo campaign -- the scope root everything else references."""
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
            # ``keywords`` + a free-text statement are the last two apply-readiness
            # essentials (alongside a base résumé, seeded via ``ensure_demo_apply_ready``);
            # with them the demo campaign satisfies the hard apply-gate so
            # ``require_automated_work`` surfaces (the digest) render instead of 409'ing.
            "keywords": ["Python", "Postgres", "distributed systems", "Kubernetes"],
            "human_readable": (
                "Senior/staff backend roles, remote-first, Python + Postgres "
                "distributed-systems depth, $180k+ floor."
            ),
        },
    )


#: The demo postings, as plain dicts so the builder is trivially inspectable. Each
#: carries a viability score (0..1) + a rationale so the digest renders scored rows,
#: and a distinct ``source`` so the discovery-source spread looks real too.
_DEMO_POSTINGS: tuple[dict, ...] = (
    {
        "suffix": "acme",
        "title": "Senior Backend Engineer",
        "company": "Acme Robotics",
        "location": "Remote (US)",
        "work_mode": "remote",
        "salary": "$185,000 - $215,000",
        "source": "linkedin",
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
        "source": "indeed",
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
        "source": "greenhouse",
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
        "source": "lever",
        "score": 0.79,
        "why": "Search-infra scale matches roles you've converted on before.",
    },
    {
        "suffix": "umbrella",
        "title": "Backend Engineer, Platform Reliability",
        "company": "Umbrella Cloud",
        "location": "Remote (US)",
        "work_mode": "remote",
        "salary": "$180,000 - $205,000",
        "source": "wellfound",
        "score": 0.76,
        "why": "Reliability/SRE-adjacent backend work close to your recent role.",
    },
    {
        "suffix": "wayne",
        "title": "Senior Software Engineer, Fulfillment",
        "company": "Wayne Logistics",
        "location": "Remote (US)",
        "work_mode": "remote",
        "salary": "$195,000 - $225,000",
        "source": "company_site",
        "score": 0.83,
        "why": "Fulfillment-scale distributed systems overlap heavily with your background.",
    },
    {
        "suffix": "stark",
        "title": "Backend Engineer, Developer Platform",
        "company": "Stark Industries",
        "location": "Remote (US)",
        "work_mode": "remote",
        "salary": "$200,000 - $235,000",
        "source": "referral",
        "score": 0.72,
        "why": "Developer-platform focus is adjacent to your tooling experience.",
    },
)

#: §7 status assigned per posting suffix (deterministic so every demo surface has a
#: subject): DIGESTED (digest approval), MATERIAL_REVIEW (résumé redline),
#: AWAITING_FINAL_APPROVAL (live-takeover final submit), BLOCKED_QUESTION (agent
#: question), BLOCKED_MISSING_ATTR (missing-detail prompt), and two post-submission
#: tracker rows sharing AWAITING_RESPONSE -- one plain, one carrying a positive
#: ``interview_invited`` signal (layered via an OutcomeEvent, not a distinct state).
_STATE_BY_SUFFIX: dict[str, ApplicationState] = {
    "acme": ApplicationState.DIGESTED,
    "globex": ApplicationState.MATERIAL_REVIEW,
    "initech": ApplicationState.AWAITING_FINAL_APPROVAL,
    "hooli": ApplicationState.BLOCKED_QUESTION,
    "umbrella": ApplicationState.AWAITING_RESPONSE,
    "wayne": ApplicationState.AWAITING_RESPONSE,
    "stark": ApplicationState.BLOCKED_MISSING_ATTR,
}

#: The suffix whose tracker row carries the recorded ``interview_invited`` signal +
#: the submission snapshot (the other AWAITING_RESPONSE row, "umbrella", stays plain
#: so the tracker board shows both a signalled and an un-signalled waiting row).
_INTERVIEW_SUFFIX = "wayne"


def build_demo_postings(campaign_id: str = DEMO_CAMPAIGN_ID) -> tuple[JobPosting, ...]:
    """Seven scored, discovered postings spanning distinct companies/sources."""
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
                source_key=spec["source"],
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
    """One application per posting, parked in the state its suffix maps to.

    See ``_STATE_BY_SUFFIX`` for the per-surface rationale. Only the
    material-review application carries the tailored variant; only the
    final-approval application carries a live sandbox session url.
    """
    cid = CampaignId(campaign_id)
    out: list[Application] = []
    for posting in postings:
        suffix = posting.id.rsplit("-", 1)[-1]
        state = _STATE_BY_SUFFIX.get(suffix, ApplicationState.DIGESTED)
        variant_id = (
            resume_variant.id if state == ApplicationState.MATERIAL_REVIEW else None
        )
        out.append(
            Application(
                id=ApplicationId(f"demo-app-{suffix}"),
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


def build_demo_submission_snapshot(
    application_id: str, posting: JobPosting
) -> SubmissionSnapshot:
    """The immutable stop-boundary evidence for the interview-signal tracker row."""
    return SubmissionSnapshot(
        id=SubmissionSnapshotId(f"demo-snapshot-{_INTERVIEW_SUFFIX}"),
        application_id=ApplicationId(application_id),
        answers={
            "why_interested": "The fulfillment-scale distributed systems work lines up with my background.",
            "salary_expectation": "$210,000",
        },
        materials=[{"type": "resume", "storage_path": "demo/materials/wayne-resume.pdf"}],
        material_versions={"resume": "demo-material-wayne-resume-v1"},
        posting_url=posting.source_url,
        captured_at=_SEED_TIMESTAMP,
    )


def build_demo_outcome_events(
    applications: tuple[Application, ...],
) -> tuple[OutcomeEvent, ...]:
    """``submitted`` / ``interview_invited`` events backing the tracker signal badges."""
    by_suffix = {a.id.rsplit("-", 1)[-1]: a for a in applications}
    events: list[OutcomeEvent] = []
    for suffix in ("umbrella", "wayne"):
        app = by_suffix.get(suffix)
        if app is None:
            continue
        events.append(
            OutcomeEvent(
                id=OutcomeEventId(f"demo-outcome-{suffix}-submitted"),
                application_id=app.id,
                type="submitted",
                source=OutcomeSource.AUTO,
            )
        )
    interview_app = by_suffix.get(_INTERVIEW_SUFFIX)
    if interview_app is not None:
        events.append(
            OutcomeEvent(
                id=OutcomeEventId(f"demo-outcome-{_INTERVIEW_SUFFIX}-interview_invited"),
                application_id=interview_app.id,
                type="interview_invited",
                source=OutcomeSource.AUTO,
            )
        )
    return tuple(events)


def build_demo_pending_actions(
    applications: tuple[Application, ...],
    postings: tuple[JobPosting, ...],
    material: GeneratedDocument,
    campaign_id: str = DEMO_CAMPAIGN_ID,
) -> tuple[PendingAction, ...]:
    """Six Portal pending-actions, one of EACH kind, tied to the demo rows.

    A ``dedup_key`` is stamped into each payload (mirroring
    ``PendingActionsService.materialize``) so a re-seed replaces rather than
    duplicates them, and so the resolve-by-dedup path can clear them.
    """
    cid = CampaignId(campaign_id)
    by_state: dict[ApplicationState, Application] = {}
    for app in applications:
        by_state.setdefault(app.status, app)
    posting_by_id = {p.id: p for p in postings}

    actions: list[PendingAction] = []

    # 1) digest-approval -- keyed on a posting id (no Application FK yet).
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

    # 2) material-review -- the résumé under redline.
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

    # 3) agent-question -- the paused, blocked application.
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

    # 4) final-approval -- the live-takeover final-submit gate.
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

    # 5) missing-detail prompt -- a soft error blocking pre-fill (FR-ATTR-5).
    missing_app = by_state.get(ApplicationState.BLOCKED_MISSING_ATTR)
    if missing_app is not None:
        posting = posting_by_id.get(missing_app.posting_id)
        site_key = posting.company.lower().replace(" ", "-") if posting else "demo"
        actions.append(
            PendingAction(
                id=PendingActionId("demo-pending-missing-attr"),
                campaign_id=cid,
                kind=KIND_MISSING_ATTR,
                title="Missing detail needed: work_authorization",
                application_id=missing_app.id,
                payload={
                    "attribute_name": "work_authorization",
                    "site_key": site_key,
                    "dedup_key": f"missing_attr:work_authorization:{site_key}",
                },
            )
        )

    # 6) integral-change confirmation -- a held attribute change awaiting the
    # user's explicit confirm-or-reject (FR-FB-3/FR-LEARN-4). Campaign-scoped, no
    # single Application it hangs off.
    actions.append(
        PendingAction(
            id=PendingActionId("demo-pending-integral-change"),
            campaign_id=cid,
            kind=KIND_INTEGRAL_CHANGE,
            title="Confirm a change to desired_salary",
            application_id=None,
            payload={
                "attribute_name": "desired_salary",
                "proposed_value": "$210,000",
                "current_value": "$190,000",
                "reason": "Inferred from your recent target-role edits — confirm before it's used.",
                "dedup_key": "integral_change:desired_salary",
            },
        )
    )

    return tuple(actions)


def build_demo_bundle(campaign_id: str = DEMO_CAMPAIGN_ID) -> DemoBundle:
    """Assemble the full, coherent demo dataset (pure -- no IO)."""
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

    interview_app = next(
        a for a in applications if a.id.rsplit("-", 1)[-1] == _INTERVIEW_SUFFIX
    )
    posting_by_id = {p.id: p for p in postings}
    submission_snapshot = build_demo_submission_snapshot(
        str(interview_app.id), posting_by_id[interview_app.posting_id]
    )
    outcome_events = build_demo_outcome_events(applications)

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
        submission_snapshot=submission_snapshot,
        outcome_events=outcome_events,
        pending_actions=pending_actions,
    )


# --- IO (persistence) -------------------------------------------------------


def persist(storage, bundle: DemoBundle) -> dict[str, int]:
    """Write the demo bundle through the REAL repositories, then commit once.

    Order is FK-safe (campaign -> postings/variant -> applications -> material ->
    revision -> submission snapshot -> outcomes -> pending actions). Every repo
    ``add`` merges by id (upsert), so a re-run replaces the demo rows rather than
    duplicating them. Returns a per-kind count for the caller's summary.
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

    storage.submission_snapshots.add(bundle.submission_snapshot)
    counts["submission_snapshots"] = 1

    for event in bundle.outcome_events:
        storage.outcomes.add(event)
    counts["outcome_events"] = len(bundle.outcome_events)

    for action in bundle.pending_actions:
        storage.pending_actions.add(action)
    counts["pending_actions"] = len(bundle.pending_actions)

    storage.commit()
    return counts


#: The demo LLM tier the seed installs so the gated read surfaces open. It points
#: at a local placeholder endpoint (never actually called for the seeded read
#: surfaces, which read persisted rows) purely to satisfy ``require_llm_configured``
#: (``is_setup_gate_open`` → a non-empty tier ladder). Kept local/private so it
#: passes the operator-URL SSRF guard.
_DEMO_LLM = {
    "provider": "ollama",
    "base_url": "http://127.0.0.1:11434",
    "api_key": "",
    "model": "demo-local-model",
}


def ensure_demo_llm(setup_service) -> bool:
    """Open the LLM gate so the seeded surfaces actually render (not 409).

    Every seeded read surface (digest, tracker, Portal pending-actions,
    post-submission, learning) sits behind ``require_llm_configured``, which is
    satisfied by a non-empty tier ladder. Without this, a freshly seeded demo
    still shows "Connect an AI model first" on every surface instead of the
    populated daily loop — defeating the seed's whole purpose.

    Non-destructive + idempotent: if the gate is ALREADY open (a real user has
    configured their own LLM, or a prior seed ran), this is a no-op and returns
    ``False`` — it never clobbers a genuine tier ladder. Only when the gate is
    closed does it install the local placeholder demo tier and return ``True``.
    """
    from applicant.ports.driving.setup_wizard import LLMSettings

    if setup_service.is_setup_gate_open():
        return False
    setup_service.configure_llm(LLMSettings(**_DEMO_LLM))
    return True


#: The demo base-résumé intake payload. ``has_base_resume`` only checks for
#: ``document_path``/``parsed`` in the BASE_RESUME intake section, and the
#: fabrication guard reads ``raw_text`` as ground truth — so a coherent snippet
#: keeps the demo self-consistent with the seeded material.
_DEMO_BASE_RESUME_TEXT = (
    "Senior backend engineer, 8+ years. Python, Postgres, distributed systems, "
    "Kubernetes. Led platform reliability work reducing p99 latency 40%; owned a "
    "1B-events/day ingestion pipeline."
)


def ensure_demo_apply_ready(onboarding_service, campaign_id: str = DEMO_CAMPAIGN_ID) -> bool:
    """Satisfy the hard apply-gate for the demo campaign so ``require_automated_work``
    surfaces (the digest) render instead of 409'ing "Automated work is blocked".

    The apply-gate (``OnboardingService.is_ready_to_apply``) needs the search-criteria
    essentials — seeded onto ``campaign.criteria`` in ``build_demo_campaign`` — PLUS a
    base résumé. This writes that base-résumé intake section through the REAL
    ``save_section`` port (never hand-rolled config), so the gate reads it back exactly
    as it would for a genuine upload.

    Non-destructive + idempotent: if the demo campaign already has a base résumé (a
    prior seed ran), this is a no-op returning ``False``. Scoped to the demo campaign
    id, so it can never touch a real campaign's onboarding state.
    """
    from applicant.ports.driving.onboarding import IntakeSection

    if onboarding_service.has_base_resume(campaign_id):
        return False
    onboarding_service.save_section(
        campaign_id,
        IntakeSection.BASE_RESUME,
        {
            "document_path": "demo/base-resume.pdf",
            "parsed": True,
            "raw_text": _DEMO_BASE_RESUME_TEXT,
            "detected_fonts": [],
        },
    )
    return True


def purge(storage, campaign_id: str = DEMO_CAMPAIGN_ID) -> dict[str, int]:
    """Reset the demo dataset via the existing campaign-purge cascade (#363).

    Reuses ``StoragePort.purge_campaign`` -- the same, already-audited delete
    path campaign-deletion uses -- rather than a bespoke wipe, so resetting the
    demo data can never diverge from (or under-delete relative to) a real
    campaign delete. Idempotent: purging an absent campaign reports zero
    counts rather than raising.
    """
    counts = storage.purge_campaign(CampaignId(campaign_id))
    storage.commit()
    return counts
