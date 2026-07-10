"""Composition root (FROZEN for phase agents).

Instantiates the engine/sessionmaker + ALL adapters + services and returns a
``Container``. Phase agents flesh out adapter bodies but MUST NOT change this
wiring (add new adapters by extending, not editing, where possible).

Storage selection: if a real DB is reachable we use ``SqlAlchemyStorage``;
otherwise (and in tests) we fall back to ``InMemoryStorage`` so the app always
boots. The durable orchestrator defaults to the file-backed shim (no Postgres
needed) and switches to DBOS when ``ORCHESTRATOR_BACKEND=dbos``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from applicant.adapters.credentials.pg_credential_store import (
    InMemoryCredentialStore,
    PgCredentialStore,
)
from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.discovery.factory import build_default_discovery
from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.fonts.font_installer import FontInstaller
from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.resume_parser.llm_verify import LLMVerifiedResumeParser
from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.resume_tailoring.base_resume_provider import BaseResumeProvider
from applicant.adapters.resume_tailoring.docx_tailor import DocxTailor
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.storage.app_config_store import (
    InMemoryAppConfigStore,
    SqlAlchemyAppConfigStore,
)
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.adapters.tools.tool_registry import ToolRegistry
from applicant.adapters.tools.tool_settings_sink import (
    InMemoryToolSettingsSink,
    SqlAlchemyToolSettingsSink,
)
from applicant.app.config import Settings, get_settings
from applicant.application.services.admin_query_service import AdminQueryService
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.campaign_service import CampaignService
from applicant.application.services.chat_service import ChatService
from applicant.application.services.conversion_service import ConversionService
from applicant.application.services.criteria_service import CriteriaService
from applicant.application.services.data_lifecycle_service import DataLifecycleService
from applicant.application.services.digest_service import DigestService
from applicant.application.services.discovery_service import DiscoveryService
from applicant.application.services.feedback_service import FeedbackService
from applicant.application.services.font_service import FontService
from applicant.application.services.learning_advanced import AdvancedLearningService
from applicant.application.services.learning_service import (
    EpisodicLessonLedger,
    LearningService,
)
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.onboarding_service import OnboardingService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.application.services.retention_service import RetentionService
from applicant.application.services.scoring_service import ScoringService
from applicant.application.services.setup_service import (
    DEFAULT_ONBOARDING_GATE_CACHE_TTL_S,
    SetupService,
    TTLCachedGate,
)
from applicant.application.workflows import application_pipeline
from applicant.observability.telemetry import TelemetryReporter
from applicant.version import __version__


@dataclass
class Container:
    """Holds every adapter + service. Built once at startup, injected via deps.

    FROZEN after construction: ``__init__`` builds it, and then
    ``__setattr__`` prevents mutation so phase agents cannot accidentally
    swap out services at runtime (defense-in-depth — the wiring contract).
    """

    settings: Settings

    # storage
    engine: Any
    session_factory: Any
    storage: Any

    # driven adapters
    llm: Any
    discovery: Any
    embedding: Any
    browser: Any
    detection: Any
    sandbox: Any
    # Desktop control (FR-CUA): swappable computer-use sub-port of the sandbox, default
    # ``noop`` (no side effects). Sibling of ``sandbox``; ships dormant until the driver
    # is baked into the sandbox image (FR-CUA-9).
    computer_use: Any
    latex_tailor: Any
    docx_tailor: Any
    font_installer: Any
    credentials: Any
    notification: Any
    orchestrator: Any
    tool_registry: Any
    # Stage 2.5 engine -> workspace callback channel (WorkspacePort). Lanes inject
    # this to call BACK into the front-door app. ``available()`` is False when no
    # shared secret is configured, so callers degrade gracefully.
    workspace: Any

    resume_parser: Any

    # services
    setup_service: Any
    campaign_service: Any
    onboarding_service: Any
    font_service: Any
    conversion_service: Any
    discovery_service: Any
    scoring_service: Any
    learning_service: Any
    advanced_learning_service: Any
    criteria_service: Any
    agent_run_service: Any
    notification_service: Any
    pending_actions_service: Any
    digest_service: Any
    attribute_cloud_service: Any
    feedback_service: Any
    chat_service: Any = None
    admin_query_service: Any = None
    # P1-9: direct-URL intake (save a job from any page). Per-request rebuilt
    # against the request session, like its storage-bound siblings.
    intake_service: Any = None
    # #363: campaign-delete purge + PII retention cascade across the relational store
    # and the sealed credential vault. Per-request rebuilt against the request session.
    data_lifecycle_service: Any = None
    # P1-6: cost & pace guardrails read model (today's applications/spend vs. the
    # daily target/hard cap; monthly projection). Per-request rebuilt against the
    # request session, exactly like campaign_service/data_lifecycle_service above.
    cost_service: Any = None
    # Phase 2 services (sandbox concurrency, final-approval gate, submission log).
    capacity_service: Any = None
    final_approval_service: Any = None
    post_submission_service: Any = None
    submission_service: Any = None
    prefill_service: Any = None
    material_service: Any = None
    # Setup-page model sources (add a local/cloud endpoint; auto-list its models).
    model_endpoint_service: Any = None
    # #298: smart LLM router (None unless LLM_SMART_ROUTING is on). Selects/reorders
    # the endpoint ladder by task/cost/local-preference; exposed for status/health.
    llm_router: Any = None
    # Lane B (Stage 2.5): capped/deduped/cached deep-research tool over the
    # WorkspacePort — the agent escalates to it on a company/role knowledge gap and
    # the manual-trigger research router calls it for user-initiated runs.
    research_service: Any = None
    # Phase 5: the agent run loop + scheduler that finally drive everything end-to-end.
    agent_loop: Any = None
    scheduler: Any = None
    # FR-AGENT-7 / FR-OBS-2: the proactive periodic agent status update service (PUSH
    # sibling of the chatbot self-report). Dormant by default (STATUS_UPDATE_SCHEDULE=off).
    status_update_service: Any = None
    # FR-NOTIF / FR-ONBOARD: the proactive "I'm still blocked on essentials" onboarding
    # nudge. Dormant by default (ESSENTIALS_NUDGE_SCHEDULE=off).
    essentials_nudge_service: Any = None
    # FR-MIND: the agent-learning substrate. ``agent_memory`` is the curated-memory /
    # skills / recall adapter trio (default ``in_memory``, hermetic). ``curation_service``
    # runs the scheduled closed loop; its cross-tick dedupe state lives in the
    # process-lived ``curation_ledger`` injected into every per-tick loop (FR-MIND-10),
    # exactly like ``resume_ledger``.
    agent_memory: Any = None
    curation_service: Any = None
    curation_ledger: Any = None
    # FR-CUA-4: per-session, opt-in, revocable desktop-assist authorizations. A
    # PROCESS-LIVED set of live-session ids the user has opted in for the duration of
    # the open takeover. Lives on the container (built once at startup), NOT on the
    # per-tick AgentLoop, so an opt-in survives the scheduler rebuilding the loop each
    # tick — and is dropped when the session ends, never leaking across applications.
    desktop_assist_sessions: set = field(default_factory=set)
    # CONC-REQ-1: builds a PER-REQUEST SqlAlchemyStorage(session_factory()) + the
    # storage-bound services for it, so concurrent sync requests (run in FastAPI's
    # threadpool) never interleave on one non-thread-safe Session. ``None`` when no DB
    # is configured (in-memory storage is thread-safe enough for the no-DB lane and is
    # shared). Each call returns a dict including ``_session`` to close in ``finally``.
    request_services_factory: Any = None
    # P5-3: opt-in error-telemetry reporter (see observability/telemetry.py). Built
    # unconditionally — it is always a real ``TelemetryReporter`` whose ``capture``
    # is a safe no-op until the operator opts in AND is not in local-only mode; the
    # global exception handler calls it, never gated by a caller-supplied flag.
    telemetry: Any = None

    _frozen: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        """Freeze the container after construction."""
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent mutation after the container is built (FROZEN enforcement)."""
        if getattr(self, "_frozen", False):
            raise AttributeError(
                f"Cannot set attribute {name!r} on frozen Container. "
                "The container is built once at startup and must not be mutated "
                "at runtime by phase agents."
            )
        object.__setattr__(self, name, value)


def _safe_dsn_host(database_url: str) -> str:
    """Return ``host[:port]`` from a DSN with the credentials stripped (#312).

    Never returns the username or password — only the host (and port) so an
    operator can identify the unreachable database without the warning leaking
    secrets into the logs.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(database_url)
        host = parsed.hostname or "unknown-host"
        return f"{host}:{parsed.port}" if parsed.port else host
    except Exception:
        return "unknown-host"


def _build_storage(settings: Settings) -> tuple[Any, Any, Any]:
    """Return (engine, session_factory, storage). Falls back to in-memory."""
    import logging
    _logger = logging.getLogger("applicant.storage")
    host = _safe_dsn_host(settings.database_url)

    try:
        from applicant.adapters.storage.repositories import SqlAlchemyStorage
        from applicant.adapters.storage.session import make_engine, make_session_factory

        engine = make_engine(settings.database_url)
        session_factory = make_session_factory(engine)
        session = session_factory()
        storage = SqlAlchemyStorage(session)
        if storage.healthcheck():
            return engine, session_factory, storage
        session.close()
        _logger.warning(
            "Database healthcheck failed for %s — falling back to in-memory "
            "storage. Data will NOT be persisted across restarts.",
            host,
        )
    except Exception as exc:
        # Scrub the exception text: a psycopg connection error can echo the full
        # DSN (including the password). Name only the host (#312).
        _logger.warning(
            "Cannot connect to database at %s (%s) — falling back to in-memory "
            "storage. Data will NOT be persisted across restarts.",
            host,
            type(exc).__name__,
        )
    # No reachable DB — degrade to in-memory storage, but mark this instance as a
    # fallback so its healthcheck() reports unhealthy (#312): the engine must fail
    # LOUD about running without a persistent DB, not silently pretend it is healthy.
    return None, None, InMemoryStorage(is_fallback=True)


def ensure_system_campaign(storage: Any) -> bool:
    """Idempotently seed the reserved ``__system__`` campaign.

    Instance-level secrets (the LLM key, sandbox tokens) are sealed in the
    credential store, whose ``campaign_id`` is a NOT-NULL FK to ``campaigns`` — so
    the ``__system__`` row must exist before any such credential is written. No-op
    on in-memory storage (no FK; also keeps the hermetic lane's campaign listings
    clean) and when the row already exists. Returns True iff a row was created.

    MUST run before the LLM env-seed in :func:`build_container`: otherwise the
    credential insert raises ForeignKeyViolation on a real database, because the
    only other seed runs at lifespan startup — after the container is built.
    """
    if getattr(storage, "_session", None) is None:
        return False
    from applicant.core.entities.campaign import Campaign
    from applicant.core.ids import SYSTEM_CAMPAIGN_ID, CampaignId

    sid = CampaignId(SYSTEM_CAMPAIGN_ID)
    if storage.campaigns.get(sid) is not None:
        return False
    try:
        storage.campaigns.add(Campaign(id=sid, name="System (internal)", active=False))
        storage.commit()
        return True
    except Exception:  # pragma: no cover - concurrent first-boot seed race
        storage.rollback()
        return storage.campaigns.get(sid) is not None


def _build_remote_view(settings: Settings) -> Any:
    """Pick the remote-view sub-port by REMOTE_VIEW_BACKEND (FR-SANDBOX-2).

    ``webtop`` (default) -> full Ubuntu webtop desktop with the DE resolved from
    TAKEOVER_DESKTOP (cinnamon default / xfce / gnome / pantheon). ``neko`` -> browser-only Neko.
    """
    from applicant.adapters.sandbox.remote_view import NekoRemoteView, WebtopRemoteView
    from applicant.app.config import REMOTE_VIEW_NEKO

    if settings.remote_view_backend == REMOTE_VIEW_NEKO:
        return NekoRemoteView()
    return WebtopRemoteView(
        base_url=settings.takeover_desktop_base_url,
        desktop=settings.takeover_desktop,
        image=settings.takeover_desktop_image_resolved,
    )


def _build_captcha_solver(settings: Settings) -> Any:
    """Build the opt-in captcha solver port (issue #350), or ``None`` for the default.

    Returns ``None`` for the shipped ``CAPTCHA_STRATEGY=human`` so the pre-fill loop is
    byte-for-byte identical to today (every captcha → existing hand-off). For ``avoid``
    it wires only the stealth-backed avoidance leg; for ``service`` it also wires the
    third-party solver scaffold from the sealed ``CAPTCHA_API_KEY`` (never logged) — an
    empty key cleanly degrades that strategy back to the hand-off.
    """
    from applicant.app.config import (
        CAPTCHA_STRATEGY_HUMAN,
        CAPTCHA_STRATEGY_SERVICE,
    )

    strategy = settings.captcha_strategy
    if strategy == CAPTCHA_STRATEGY_HUMAN:
        return None

    from applicant.adapters.captcha import (
        BehavioralAvoidanceStrategy,
        CaptchaSolver,
        HumanHandoffAdapter,
        SolverServiceAdapter,
    )

    service: Any = None
    if strategy == CAPTCHA_STRATEGY_SERVICE:
        from applicant.adapters.captcha.solver_service import HttpTokenSolver

        # The key is held only inside the solver (redacted from repr, never logged).
        solver_call = (
            HttpTokenSolver(
                api_key=settings.captcha_api_key,
                service=settings.captcha_service,
                egress_proxy=settings.egress_proxy,
            )
            if settings.captcha_api_key
            else None
        )
        service = SolverServiceAdapter(
            solver=solver_call,
            api_key=settings.captcha_api_key,
        )

    return CaptchaSolver(
        strategy=strategy,
        avoidance=BehavioralAvoidanceStrategy(),
        service=service,
        handoff=HumanHandoffAdapter(),
    )


def _build_sandbox(settings: Settings, setup_service: Any) -> Any:
    """Pick the sandbox backend by SANDBOX_BACKEND (FR-SANDBOX-1, FR-STEALTH-1).

    ``local`` (default) -> the existing webtop/Neko container path (LocalSandbox).
    ``proxmox-windows`` -> the native Proxmox Windows VM backend: the engine drives,
    and the human takes over, REAL Google Chrome inside a real licensed Windows VM
    (genuine Windows fingerprint, ZERO spoofing). The Proxmox connection/login data
    is collected via the OOBE sandbox-connection step and the backend is GATED on it;
    if it is not yet configured we fall back to LocalSandbox so the app still boots.

    The REAL :class:`ProxmoxApiClient` is only constructed when the connection is
    configured; the default test lane never reaches it (it stays hermetic).
    """
    from applicant.adapters.sandbox.local_sandbox import LocalSandbox

    if not settings.is_proxmox_windows_backend:
        return LocalSandbox(remote_view=_build_remote_view(settings))

    # Native Proxmox Windows backend. Until the OOBE connection step is done the
    # backend is not usable — boot with LocalSandbox so the app still starts (the
    # automated-work gate blocks real work until the step is complete).
    if not setup_service.is_sandbox_backend_ready():  # pragma: no cover - boot guard
        return LocalSandbox(remote_view=_build_remote_view(settings))

    from applicant.adapters.sandbox.proxmox_client import ProxmoxApiClient
    from applicant.adapters.sandbox.proxmox_windows_sandbox import ProxmoxWindowsSandbox
    from applicant.adapters.sandbox.remote_view import WindowsRdpRemoteView

    conn = setup_service.get_sandbox_connection()
    token_secret = setup_service.resolve_sandbox_secret("token")
    client = ProxmoxApiClient(  # pragma: no cover - integration (real PVE)
        api_url=conn["proxmox_api_url"],
        token_id=conn["proxmox_token_id"],
        token_secret=token_secret,
        node=conn["proxmox_node"],
    )
    remote_view = WindowsRdpRemoteView(
        method=conn.get("takeover_method", "rdp"),
        url_template=conn.get("takeover_url_template", ""),
    )
    return ProxmoxWindowsSandbox(  # pragma: no cover - integration (real PVE)
        client,
        template_vmid=int(conn["template_vmid"]),
        node=conn["proxmox_node"],
        clone_mode=conn.get("clone_mode", "snapshot-revert"),
        cdp_host=conn.get("cdp_host", ""),
        cdp_port=int(conn.get("cdp_port", 9222)),
        remote_view=remote_view,
    )


def _approval_timeout_seconds_from(
    wait_seconds: float | None, timeout_days: int | float | None
) -> float | None:
    """#189 precedence: an explicit per-second override wins when set; otherwise
    derive from the whole-days setting. 0 (either knob) means "no timeout / forever"
    (represented as ``0.0``, the pre-existing contract). Returns ``None`` only when
    BOTH inputs are ``None`` (no value present at all -- e.g. a fresh, unconfigured
    Settings > Automation record) so callers can distinguish "no override saved"
    from "override explicitly set to forever".
    """
    if wait_seconds is not None:
        return float(wait_seconds)
    if timeout_days is not None:
        return float(timeout_days) * 86_400 if float(timeout_days) > 0 else 0.0
    return None


def _build_orchestrator(settings: Settings, setup_service: Any = None) -> Any:
    if settings.orchestrator_backend == "dbos":
        # STAGE B: DBOS requires a live Postgres; only select when truly available.
        from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator

        # #189: the per-second override wins when set, so a deployment can tune the
        # approval-gate wait precisely instead of only in whole days; otherwise fall
        # back to the days-based setting. 0 (either knob) means "no timeout / forever".
        # This is only the ``settings.*`` env DEFAULT, used as the DbosOrchestrator's
        # constructor-time fallback -- see ``_live_approval_timeout_seconds`` below for
        # the lens 11 #23 fix that makes an operator's saved override actually govern
        # the wait, without a restart.
        timeout_seconds = _approval_timeout_seconds_from(
            settings.approval_wait_seconds, settings.approval_timeout_days
        )

        def _live_approval_timeout_seconds() -> float | None:
            """Lens 11 #23: live re-read of the Settings > Automation override.

            ``timeout_seconds`` above is computed ONCE here at container-build time
            from ``settings.approval_timeout_days``/``approval_wait_seconds`` -- so an
            operator's saved override (``SetupService.set_automation_prefs(
            approval_timeout_days=..., approval_wait_seconds=...)``) persisted and
            displayed back in Settings but never actually changed how long a pending
            final-approval waited before timing out. Called on EVERY ``recv``
            (``DbosOrchestrator._resolve_timeout_seconds``), mirroring
            ``Scheduler._effective_curation_schedule``; returns ``None`` to defer to
            the env default above when nothing has been saved yet or no
            ``setup_service`` is wired (legacy/unit construction).
            """
            if setup_service is None:
                return None
            try:
                stored = setup_service.get_automation_prefs() or {}
            except Exception:  # pragma: no cover - defensive: never break a recv
                return None
            return _approval_timeout_seconds_from(
                stored.get("approval_wait_seconds"), stored.get("approval_timeout_days")
            )

        return DbosOrchestrator(
            settings.database_url,
            approval_timeout_seconds=(
                timeout_seconds if timeout_seconds is not None else 0.0
            ),
            live_approval_timeout_seconds=_live_approval_timeout_seconds,
        )
    return CheckpointShimOrchestrator(settings.checkpoint_dir)


def _compose_summary_providers(*providers: Any) -> Any:
    """Combine run-summary providers into one ``provider(storage, now)`` callable.

    Each provider maps the per-tick storage to a list of ``RunSummary`` records; the
    composed callable concatenates them so a single curation nudge reviews every
    source at once (FR-MIND-7). A provider that raises or returns nothing contributes
    no summaries and never breaks the others, so an empty/absent source is a no-op and
    behavior is byte-identical when there is no feedback to learn from.
    """
    real = tuple(p for p in providers if p is not None)
    if not real:
        return None

    def _provider(storage, now=None) -> list:
        out: list = []
        for p in real:
            try:
                out.extend(p(storage, now) or [])
            except Exception:  # pragma: no cover - defensive: one source never breaks others
                continue
        return out

    return _provider


class _LivePresubmitSafetyParams:
    """dict-like presubmit-safety parameters, re-read live on every ``.get()``
    (lens 11 #22) instead of being latched once from ``settings.presubmit_*`` at
    container-build time.

    ``AgentLoop._process_approvals`` and ``DigestService`` (the digest-row warning
    preview) both only ever call ``.get(key, default)`` on the ``presubmit_safety_
    params`` object -- never iterate or copy it -- so swapping the plain dict
    ``build_container`` used to pass for this Mapping-like proxy changes NOTHING
    about how either consumer calls it; it just makes the read live. A Settings >
    Automation save (``SetupService.set_automation_prefs(presubmit_max_listing_age_
    days=..., presubmit_duplicate_cooldown_days=..., presubmit_max_apps_per_company_
    per_day=..., presubmit_eligibility_enabled=...)``) now actually governs the
    pipeline-blocking checks in ``presubmit_safety.py`` without a restart. Falls back
    to the ``settings``-sourced default when the operator has not overridden a given
    key -- mirrors ``Scheduler._effective_curation_schedule``.
    """

    #: AgentLoop/DigestService's local key name -> the persisted automation-prefs key.
    _KEY_MAP = {
        "max_age_days": "presubmit_max_listing_age_days",
        "duplicate_cooldown_days": "presubmit_duplicate_cooldown_days",
        "max_apps_per_company_per_day": "presubmit_max_apps_per_company_per_day",
        "eligibility_enabled": "presubmit_eligibility_enabled",
    }

    def __init__(self, defaults: dict[str, Any], setup_service: Any) -> None:
        self._defaults = dict(defaults)
        self._setup = setup_service

    def get(self, key: str, default: Any = None) -> Any:
        stored_key = self._KEY_MAP.get(key)
        if stored_key is not None and self._setup is not None:
            try:
                prefs = self._setup.get_automation_prefs()
            except Exception:  # pragma: no cover - defensive: never break a check
                prefs = None
            if prefs:
                value = prefs.get(stored_key)
                if value is not None:
                    return value
        return self._defaults.get(key, default)


def build_container(settings: Settings | None = None) -> Container:
    """Build the fully-wired container."""
    settings = settings or get_settings()

    # Perf audit #6: ONE process-lived DigestCache for the whole process, shared
    # across EVERY DigestService construction below (main / per-tick / per-request).
    # DigestService is rebuilt every request (CONC-REQ-1) and every scheduler tick
    # (container._build_tick_services), so a cache living on `self` would reset on
    # every single call — exactly like resume_ledger/digest_ledger below, which is
    # why this is built here (once) and threaded through, not constructed inside
    # DigestService.__init__.
    from applicant.application.services.digest_service import DigestCache

    digest_cache = DigestCache()

    engine, session_factory, storage = _build_storage(settings)

    # Browser adapter imported lazily (Phase 2 heavy deps not required at boot).
    from applicant.adapters.browser.patchright_browser import PatchrightBrowser

    # App-config store (persists the tier ladder + wizard state, FR-LLM-3/FR-OOBE).
    session = getattr(storage, "_session", None)
    config_store = (
        SqlAlchemyAppConfigStore(session) if session is not None else InMemoryAppConfigStore()
    )

    # Credential vault (FR-VAULT-1/3): when a real DB is configured, persist sealed
    # records to Postgres (survives restarts, FR-VAULT-3); otherwise (hermetic boot /
    # no DB) use the libsodium-sealed in-memory fallback so the app still boots.
    if session_factory is not None:
        credentials = PgCredentialStore(
            settings.credential_keyfile, session_factory=session_factory
        )
    else:
        credentials = InMemoryCredentialStore(settings.credential_keyfile)

    # Onboarding service (FR-ONBOARD): resumable intake + attribute-cloud bootstrap.
    # The deterministic parser is wrapped by the LLM parse-verify layer (P1-1a): the
    # draft parse is checked/corrected by the configured model so real-world résumé
    # layouts slot into the right fields (study: docs/studies/2026-07-07-parse-verify-
    # tier-study.md). The LLM ladder is built LATER in this function, so the model is
    # late-bound via bind_llm() further down; until then — and whenever no model is
    # configured — the wrapper returns the deterministic parse with an honest
    # not-verified marker instead of failing ingest.
    resume_parser = LLMVerifiedResumeParser(
        ResumeParser(), enabled=settings.parse_verify_enabled
    )
    # CONC-2 (scheduler ↔ request Session isolation): the onboarding-gate scan and the
    # config-store reads/writes that back the automated-work gate BOTH ride whatever
    # Session ``a_storage``/``a_config_store`` were built on. The boot-time stack binds
    # to the process-lived boot Session, but the 24/7 scheduler thread must NOT reuse
    # it: a background tick reading the gate while a gated request handler reads the
    # same boot Session raises ``This session is provisioning a new connection;
    # concurrent operations are not permitted`` (first surfaced under real Postgres +
    # xdist, where connection provisioning is slow enough to widen the race; the
    # in-memory lane has no Session so it never manifests). So the whole setup/onboarding
    # stack is built by this factory, and ``_build_tick_services`` below builds a SECOND
    # stack bound to the tick's OWN fresh Session — mirroring how storage-bound services
    # are already isolated per tick. ``a_config_store`` and ``a_storage`` MUST share one
    # Session (the caller pairs them so).
    def _build_setup_stack(a_storage, a_config_store):
        onboarding_service = OnboardingService(
            storage=a_storage,
            config_store=a_config_store,
            resume_parser=resume_parser,
        )

        # The hard apply-gate: autonomous applying (discovery -> apply) is BLOCKED until
        # the required-to-apply essentials exist for SOME campaign (target roles, work
        # mode, locations, salary floor, key skills, and a résumé). The onboarding form
        # itself requires virtually nothing — the agent gathers these over time (chat,
        # résumé parse, learning) — so the gate keys on the readiness of the essentials,
        # not on a fully-completed comprehensive intake. It BLOCKS, never half-applies.
        def _onboarding_gate() -> bool:
            for c in a_storage.campaigns.list():
                if onboarding_service.is_ready_to_apply(str(c.id)):
                    return True
            return False

        # Perf item #8: ``_onboarding_gate`` scans every campaign and computes full
        # apply-readiness (criteria load + résumé check) per campaign, and it backs
        # ``require_automated_work`` — polled by agent_status, digest, and agent-runs
        # every 45-60s from every surface. Wrap it in a short-TTL memo (see
        # ``TTLCachedGate`` for the safety reasoning) so the expensive scan runs at
        # most once per TTL window instead of once per poll. Wrapping the closure
        # here — rather than caching inside ``SetupService.is_automated_work_allowed``
        # — keeps unit tests that build a bare ``SetupService`` with their own
        # real-time gate closure unaffected (they must keep seeing changes
        # immediately); only this real, expensive, container-wired closure is cached.
        _onboarding_gate_cached = TTLCachedGate(
            _onboarding_gate, DEFAULT_ONBOARDING_GATE_CACHE_TTL_S
        )

        # The matching "what's still missing" reporter for the gate: the FIRST campaign's
        # readiness drives the setup-status payload + chat copy so the front door can say
        # "I can't start applying until I know: ..." with the real remaining items. Reads
        # real campaign data only; never fabricated.
        def _apply_readiness():
            from applicant.core.ids import SYSTEM_CAMPAIGN_ID

            # Exclude the reserved __system__ campaign (instance secrets only — it has no
            # criteria/résumé). Including it made the "what's still missing" surface fall
            # back to ITS emptiness (campaigns[0]) and report every essential missing —
            # e.g. claiming a résumé is needed right after one was uploaded to the real
            # campaign. Mirror campaign_service.list_campaigns(), which already excludes it.
            campaigns = [
                c for c in a_storage.campaigns.list() if str(c.id) != SYSTEM_CAMPAIGN_ID
            ]
            for c in campaigns:
                r = onboarding_service.apply_readiness(str(c.id))
                if r.ready:
                    return r
            if campaigns:
                return onboarding_service.apply_readiness(str(campaigns[0].id))
            return None

        # Setup service so the persisted ladder can configure the LLM adapter; its
        # automated-work gate now requires ONLY the LLM + apply-readiness gates (channels
        # and the sandbox moved into Settings and are optional). The channels gate is
        # still wired so the status payload reports channel state for the Settings UI;
        # it reads the wizard-persisted channel config OR env defaults.
        setup_service = SetupService(
            llm_configured=settings.llm_configured,
            config_store=a_config_store,
            credentials=credentials,
            onboarding_gate=_onboarding_gate_cached,
            sandbox_backend=settings.sandbox_backend,
            # P2-11: local-only private mode filters the effective ladder AND the
            # LLM gate inside SetupService (single chokepoint for every consumer).
            local_only=settings.llm_local_only,
            # P5-3: env-sourced telemetry DEFAULTS only; Settings > System can
            # override at runtime (persisted like every other Settings knob), and
            # the real send-or-not decision is recomputed fresh by
            # ``telemetry_status`` on every call, folding in ``local_only`` too.
            telemetry_enabled_default=settings.telemetry_enabled,
            telemetry_endpoint_default=settings.telemetry_endpoint,
        )
        setup_service.set_apply_readiness_reporter(_apply_readiness)

        def _channels_gate() -> bool:
            return setup_service.channels_configured() or bool(
                settings.discord_webhook_url or settings.apprise_urls
            )

        setup_service.set_channels_gate(_channels_gate)
        # The gate cache is returned so the boot caller can invalidate it immediately
        # after each readiness-flipping write path (see ``_invalidate_gate_after``);
        # the per-tick caller discards it (a per-tick cache lives and dies with the tick).
        return setup_service, onboarding_service, _onboarding_gate_cached

    # Boot-time stack, bound to the process-lived boot Session (``config_store`` above).
    setup_service, onboarding_service, _onboarding_gate_cached = _build_setup_stack(
        storage, config_store
    )

    # G07 / lens 11 #22: pre-submit safety parameters -- built ONCE and shared by
    # every AgentLoop (pipeline-start block) AND every DigestService (digest-row
    # warning, product-gaps backlog) instance below, so the digest warning always
    # reflects the SAME operator-configured thresholds as the actual pipeline block
    # instead of two independently-drifting literals. A live-re-reading proxy (NOT a
    # plain dict) so a Settings > Automation save actually governs the checks without
    # a restart -- see ``_LivePresubmitSafetyParams``.
    presubmit_safety_params = _LivePresubmitSafetyParams(
        {
            "max_age_days": settings.presubmit_max_listing_age_days,
            "duplicate_cooldown_days": settings.presubmit_duplicate_cooldown_days,
            "max_apps_per_company_per_day": settings.presubmit_max_apps_per_company_per_day,
            "eligibility_enabled": settings.presubmit_eligibility_enabled,
        },
        setup_service,
    )
    # The LLM env-seed below seals the key in the credential store (campaign-FK).
    # Ensure the reserved __system__ campaign exists FIRST, or the env-config path
    # crashes on boot against a real DB — lifespan's seed runs only later. See
    # ensure_system_campaign.
    ensure_system_campaign(storage)
    # Seed L1 from env on first boot if the UI hasn't set a ladder yet (FR-LLM-2).
    if settings.llm_configured and not setup_service.get_tiers():
        from applicant.ports.driving.setup_wizard import LLMSettings as _LLMSettings

        setup_service.configure_llm(
            _LLMSettings(
                provider=settings.llm_provider,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
            )
        )

    # Setup-page model sources: add a local/cloud endpoint and auto-list its models.
    from applicant.application.services.model_endpoint_service import ModelEndpointService

    model_endpoint_service = ModelEndpointService(
        config_store=config_store,
        credentials=credentials,
    )

    # FR-MIND-8: bound the context (compress middle turns over a token budget) and
    # apply provider prefix-cache breakpoints where supported. Threshold 0 (default)
    # keeps the manager a no-op, so default behavior is unchanged.
    from applicant.adapters.llm.context_window import ContextWindowManager
    from applicant.application.services.context_manager import ContextManager

    # FR-MIND-8/-13: the richer, lineage-aware application context manager. It
    # summarizes the MIDDLE turns (parent/child lineage recorded) once context
    # crosses the threshold; threshold 0 (default) disables it, so ``.compress`` is
    # an identity and the default path is a strict no-op (byte-identical behavior).
    # An OPTIONAL/defaulted dependency of the LLM adapter — when wired it supersedes
    # the placeholder window manager. Its summarizer defaults to a deterministic
    # heuristic now; the cheap-model summarizer is wired in AFTER ``llm`` exists
    # (below) to avoid a construction cycle, mirroring the curation summarizer.
    app_context_manager = ContextManager(
        threshold=settings.context_compress_threshold,
    )
    # #298: smart routing (config-gated, default OFF). When ON, a SmartLlmRouter
    # reorders the tier ladder so a router-preferred endpoint (e.g. a local
    # Ollama/OpenAI-compatible model under local-preference) is the FIRST tier
    # OpenAICompatibleLLM walks — which is exactly what makes the engine CALL the
    # local model (the adapter dispatches _call_ollama/_call_openai off the active
    # tier's base_url). The existing context-window fallback still walks the rest.
    # OFF: the ladder is built straight from build_ladder(), byte-identical to today.
    smart_router = None
    if settings.llm_smart_routing:
        from applicant.adapters.llm.smart_router import SmartLlmRouter

        smart_router = SmartLlmRouter(model_endpoint_service)

    def _resolve_llm_ladder():
        """Re-read the tier ladder from the config store + apply smart routing.

        This is the SINGLE source of the live ladder, called both at boot and again
        whenever a model is (re)configured at runtime (the LLM adapter re-invokes it
        after ``setup_service`` fires its config-change hook). Re-reading here is what
        lets a model connected through the OOBE take effect with NO engine restart —
        the boot-time adapter used to freeze the initially-empty ladder. OFF: the
        ladder is built straight from ``build_ladder()``, byte-identical to today.
        """
        ladder = setup_service.build_ladder()
        if smart_router is not None and ladder is not None:
            from applicant.adapters.llm.smart_router import order_ladder_by_router
            from applicant.ports.driven.llm_router import CostTier, TaskType

            ladder = order_ladder_by_router(
                ladder,
                smart_router,
                task=TaskType.CHAT,
                cost_tier=(
                    CostTier.LOWEST
                    if settings.llm_smart_routing_prefer_local
                    else CostTier.BALANCED
                ),
                prefer_local=settings.llm_smart_routing_prefer_local,
            )
        return ladder

    # #48 dark-engine audit: LLM_RATE_LIMIT/LLM_RATE_PERIOD were configured but never
    # gated a call. Wire the rolling-window gate into the ONE shared adapter singleton
    # below. ``llm_rate_limit == 0`` disables it (the config comment's "0 disables"),
    # in which case ``LLMRateLimiter`` is a zero-overhead no-op, so the default request
    # path is unaffected unless an operator sets a real limit.
    from applicant.adapters.llm.rate_limit import LLMRateLimiter

    llm_rate_limiter = LLMRateLimiter(
        limit=settings.llm_rate_limit, period=settings.llm_rate_period
    )
    # P1-6 (cost & pace guardrails): ONE process-lived ledger for the whole engine,
    # fed by the shared ``llm`` singleton below from EVERY completion that reports
    # usage (chat, discovery, material generation, résumé parse-verify, ...). Drained
    # into ``agent_runs.stats`` by AgentLoop's per-tick flush (see agent_loop.py).
    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from applicant.application.services.usage_ledger import UsageLedger
    from applicant.core.rules.cost_estimate import estimate_cost_usd

    usage_ledger = UsageLedger()

    def _record_llm_usage(provider: str, model: str, usage: dict) -> None:  # noqa: ARG001
        cost = estimate_cost_usd(
            int(usage.get("tokens_in", 0)),
            int(usage.get("tokens_out", 0)),
            input_price_per_1k=settings.llm_cost_per_1k_input_usd,
            output_price_per_1k=settings.llm_cost_per_1k_output_usd,
        )
        usage_ledger.record(
            _datetime.now(_UTC).date(),
            tokens_in=int(usage.get("tokens_in", 0)),
            tokens_out=int(usage.get("tokens_out", 0)),
            cost_usd=cost,
        )

    llm = OpenAICompatibleLLM(
        # Resolve the ladder lazily through the provider so a runtime model-connect
        # (which re-fires this) is picked up without rebuilding the adapter — the chat,
        # agent, prefill and material paths all share THIS singleton.
        ladder_provider=_resolve_llm_ladder,
        context_manager=ContextWindowManager(
            token_budget=settings.context_compress_threshold
        ),
        app_context_manager=app_context_manager,
        prefix_cache=settings.prefix_cache,
        rate_limiter=llm_rate_limiter,
        usage_recorder=_record_llm_usage,
    )
    # Connecting a model at runtime persists the new tier and then re-arms this exact
    # adapter, so the next completion walks the freshly-configured ladder (no restart).
    setup_service.register_llm_config_change_hook(llm.refresh_ladder)
    # P1-1a: late-bind the ladder into the parse-verify layer (the parser was built
    # before ``llm`` existed). The singleton resolves its ladder lazily, so a model
    # connected at runtime is picked up on the next résumé ingest automatically.
    resume_parser.bind_llm(llm, enabled=settings.parse_verify_enabled)
    # FR-MIND-8/-13: upgrade the context summarizer to the CHEAP, OPTIONAL cheap-model
    # path now that ``llm`` exists. Defensive: ``build_llm_summarizer`` returns the
    # deterministic heuristic when no model is configured, so the hermetic lane stays
    # byte-identical and a flaky completion degrades per-pass rather than raising.
    from applicant.application.services.context_manager import (
        build_llm_summarizer as _build_context_summarizer,
    )

    app_context_manager.summarizer = _build_context_summarizer(llm)
    # Master aggregator (FR-DISC-2). Offline fake clients by default (hermetic boot
    # + tests); live boards opt-in via DISCOVERY_LIVE (FR-DISC-4 network boundary).
    discovery_proxies = tuple(
        p.strip() for p in settings.discovery_proxies.split(",") if p.strip()
    )
    # Item 80 (B7): operator-added job-board RSS feeds are injected here the same way
    # proxies are — the app/config layer reads the setting and threads it into the
    # discovery adapter, which never imports app.config itself (hexagonal layering).
    discovery_rss_feeds = tuple(
        f.strip() for f in settings.discovery_rss_feeds.split(",") if f.strip()
    )
    discovery = build_default_discovery(
        live=settings.discovery_live,
        searxng_url=settings.searxng_url,
        proxies=discovery_proxies,
        rss_feeds=discovery_rss_feeds,
    )
    # P1-9: single-URL posting fetcher for the paste-a-URL/bookmarklet intake.
    # Same live/fake split as the discovery clients above (FR-DISC-4 hermeticity):
    # the fake never touches the network and the intake service then saves an
    # honest, clearly URL-derived row instead of pretending it read the page.
    from applicant.adapters.discovery.url_intake import (
        FakeUrlPostingFetcher,
        LiveUrlPostingFetcher,
    )

    url_posting_fetcher = (
        LiveUrlPostingFetcher(proxies=discovery_proxies)
        if settings.discovery_live
        else FakeUrlPostingFetcher()
    )
    embedding = LocalEmbedding()
    # FR-STEALTH-4: residential egress is enforced up front — a configured proxy is
    # threaded into the real browser launch; residential-proxy mode without a proxy
    # (or a self-flagged datacenter exit) refuses to launch.
    from applicant.adapters.browser.stealth import EgressPolicy

    egress = EgressPolicy.from_settings(
        mode=settings.egress_mode,
        proxy_url=settings.egress_proxy_url,
        residential=settings.egress_residential,
    )
    browser = PatchrightBrowser(
        egress=egress,
        # Drive a real Chrome/Chromium for pre-fill in the deploy (BROWSER_REAL=true);
        # tests/CI leave it off and use the hermetic in-memory FakePageSource. Without
        # this the engine only ever SIMULATES pre-fill (FR-PREFILL-1/2).
        use_real_browser=settings.browser_real,
        # ADR-0004: gate for automated account creation (default OFF). Threaded into the
        # boundary so the create-account submit is permitted only when opted in.
        automated_accounts=settings.allow_automated_accounts,
        # FR-STEALTH-3: persist per-tenant signed-in sessions on a configured (deploy:
        # volume-backed) dir so the user signs in once and the session is reused.
        profiles_dir=settings.browser_profiles_dir,
        # The browser engine all outbound automation traffic routes through
        # (FR-STEALTH-1): ``camoufox`` (default) or the patchright/Chrome ``chromium``
        # path. ``channel`` only matters when the chromium engine is selected.
        engine=settings.browser_engine,
        channel=settings.browser_channel,
        egress_timezone=settings.egress_timezone,
        egress_locale=settings.egress_locale,
        # FR-STEALTH-1: ``native`` for the proxmox-windows backend (real Windows +
        # real Chrome, no spoof); ``linux`` (coherent honest spoof) for local.
        persona=settings.stealth_persona_resolved,
    )
    detection = DetectionMonitor()
    # FR-SANDBOX-2/3: the swappable remote-view sub-port. Default is the full Ubuntu
    # webtop desktop (DE from TAKEOVER_DESKTOP -> resolved image); Neko (browser-only)
    # stays selectable via REMOTE_VIEW_BACKEND=neko. Image selection + URL/token are
    # real here; the container/room control plane is integration-gated in the adapter.
    sandbox = _build_sandbox(settings, setup_service)
    # Desktop control (FR-CUA): the swappable computer-use sub-port of the sandbox.
    # Default ``noop`` (records calls, NO side effects) so the hermetic lane needs no
    # cua-driver/display stack; ``COMPUTER_USE_BACKEND=cua`` selects the real adapter,
    # which itself degrades to noop semantics until the driver is baked into the sandbox
    # image (FR-CUA-12). Import-safe — the factory pulls in no heavy deps at boot.
    from applicant.adapters.sandbox.computer_use import build_computer_use

    computer_use = build_computer_use(settings)
    # Render fidelity (FR-RESUME-4): auto-enable the real compile/convert when the
    # engine binary is present at runtime (RESUME_RENDER=auto|on|off, default auto).
    latex_tailor = LatexTailor(render_mode=settings.resume_render)
    docx_tailor = DocxTailor(render_mode=settings.resume_render)
    font_installer = FontInstaller(install_root=settings.fonts_dir)
    # Channel config: wizard-persisted (FR-OOBE-2) overrides env defaults; real
    # network send is opt-in (NOTIFICATIONS_LIVE) so the default lane is hermetic.
    # Quiet hours (FR-NOTIF-5) are persisted alongside the channels and rehydrated on
    # boot so the deferral window survives restarts; ``enabled=False`` is 24/7 mode
    # (always_on), which the notifier treats as "no quiet hours" — errors always fire.
    chan = setup_service.get_channels()
    quiet = setup_service.get_quiet_hours()
    notification = AppriseNotifier(
        discord_webhook_url=chan.get("discord_webhook_url") or settings.discord_webhook_url,
        apprise_urls=chan.get("apprise_urls") or settings.apprise_urls,
        # #300: ntfy push channel — opt-in, empty by default (no push). Persisted
        # alongside the other channels so it survives restarts.
        ntfy_url=chan.get("ntfy_url") or settings.ntfy_url,
        quiet_hours=(quiet["start"], quiet["end"]) if quiet["enabled"] else None,
        quiet_tz=quiet["tz"],
        always_on=not quiet["enabled"],
        # The UI-configurable email-escalation delay (FR-NOTIF-2) persists across
        # restarts via the channels config (default 15 min).
        email_timeout_seconds=setup_service.get_email_timeout_minutes() * 60,
        send_real=settings.notifications_live,
    )
    orchestrator = _build_orchestrator(settings, setup_service)
    # Stage 2.5: outbound client for the engine -> workspace callback channel. The
    # shared secret gates it (available() is False when unset) so the default/test
    # lane never tries to reach the workspace.
    from applicant.adapters.workspace.http_workspace_client import HttpWorkspaceClient

    workspace = HttpWorkspaceClient(
        base_url=settings.workspace_url,
        token=settings.applicant_internal_token,
    )
    # Tool registry persisted to tool_settings when a DB session is available
    # (FR-UI-4: toggles survive restarts); in-memory otherwise (hermetic boot).
    tool_sink = (
        SqlAlchemyToolSettingsSink(session)
        if session is not None
        else InMemoryToolSettingsSink()
    )
    tool_registry = ToolRegistry(sink=tool_sink)

    # Register durable workflows (recovered on startup in lifespan).
    application_pipeline.register(orchestrator)

    campaign_service = CampaignService(storage)
    # #363: campaign-delete purge + PII retention cascade. Cascades across the
    # relational store and the sealed credential vault, bounded by PII_RETENTION_DAYS.
    data_lifecycle_service = DataLifecycleService(
        storage,
        credentials,
        pii_retention_days=settings.pii_retention_days,
    )
    # P1-6: cost & pace guardrails read model (today's applications/spend vs. the
    # daily target/hard cap; monthly projection). Read-only over ``agent_runs.stats``
    # (see agent_loop.py's ``_drain_usage_stats``) — no ledger reference needed here.
    from applicant.application.services.cost_service import CostService

    cost_service = CostService(storage)
    font_service = FontService(font_installer)
    conversion_service = ConversionService(latex_tailor=latex_tailor, config_store=config_store)
    # #44 (dark-engine audit): ONE process-lived EpisodicLessonLedger for the whole
    # process. LearningService is rebuilt fresh every scheduler tick AND every
    # request (``_build_tick_services`` / ``_build_request_services``, CONC-REQ-1),
    # so a Reflexion lesson kept on a per-instance dict would vanish before the very
    # next recall — exactly like resume_ledger/digest_ledger/RoutineStore below.
    # Injected into every LearningService construction so a lesson learned on one
    # tick's failure is still there for the next tick's (or request's) recall.
    lesson_ledger = EpisodicLessonLedger()
    learning_service = LearningService(storage, embedding, lesson_ledger=lesson_ledger)
    # Phase 4 real-conversion depth layered over the cheap Phase 1 base (FR-LEARN-2/3/4).
    advanced_learning_service = AdvancedLearningService(base=learning_service, storage=storage)

    # Surface engine-proposed attributes on the setup-status payload (#273) so the
    # front-door "suggested attribute" approval card has a data source. Mirrors the
    # apply-readiness reporter: reads real campaigns' stored inputs only, never
    # fabricated. A reporter hiccup degrades to an empty list (status never breaks).
    # P1-10 (multi-campaign): fans out over EVERY real campaign — reading only the
    # first campaign's proposals would silently hide a second campaign's suggestions —
    # deduped on (name, value) since the payload is deployment-level.
    def _suggested_attributes() -> list[dict]:
        from applicant.core.ids import SYSTEM_CAMPAIGN_ID

        campaigns = [
            c for c in storage.campaigns.list() if str(c.id) != SYSTEM_CAMPAIGN_ID
        ]
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for campaign in campaigns:
            for p in advanced_learning_service.suggest_attributes(campaign.id):
                key = (str(p.name), str(p.value))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"name": p.name, "value": p.value, "source": p.source})
        return out

    setup_service.set_suggested_attributes_reporter(_suggested_attributes)

    discovery_service = DiscoveryService(
        storage,
        discovery,
        embedding,
        learning_service,
        tool_registry=tool_registry,
        advanced_learning=advanced_learning_service,
    )
    scoring_service = ScoringService(
        storage,
        llm,
        embedding,
        learning=learning_service,
        advanced_learning=advanced_learning_service,
        tool_registry=tool_registry,
    )
    criteria_service = CriteriaService(storage, llm)
    # Phase 2 realtime push (realtime-websocket.md): the ONE process-lived ``notif``
    # publisher, threaded into the notification + pending-action services (main,
    # per-tick, per-request) so every path that creates a notification or mutates the
    # open pending-action set fans a downstream ``notif`` frame to the realtime
    # registry. Like resume_ledger/digest_cache above, it is built ONCE here and
    # injected into every rebuild — the registry it publishes to is a module-global
    # that survives the scheduler's per-tick service rebuilds. BE→FE surfacing only.
    # RT Phase 3 adds the sibling ``agent`` publisher: threaded into every
    # AgentRunService build so each recorded run fans a downstream ``agent`` event to
    # the operator's live tabs (BE→FE surfacing only — the upstream co-steer verbs are
    # gated separately at ``authorize_upstream``, ``approve`` off).
    from applicant.app.realtime import make_agent_publisher, make_notif_publisher

    notif_publisher = make_notif_publisher()
    agent_publisher = make_agent_publisher()
    agent_run_service = AgentRunService(storage, realtime=agent_publisher)
    notification_service = NotificationService(notification, realtime=notif_publisher)
    pending_actions_service = PendingActionsService(storage, realtime=notif_publisher)
    digest_service = DigestService(
        storage,
        notification,
        scoring_service,
        learning=learning_service,
        criteria=criteria_service,
        notification_service=notification_service,
        pending_actions=pending_actions_service,
        presubmit_safety_params=presubmit_safety_params,
        digest_cache=digest_cache,
    )
    attribute_cloud_service = AttributeCloudService(
        storage,
        pending_actions=pending_actions_service,
        advanced_learning=advanced_learning_service,
    )
    # P1-9: direct-URL intake — reuses the existing scoring/pending/criteria path
    # so a pasted or bookmarked posting enters the SAME reviewed pipeline.
    from applicant.application.services.intake_service import IntakeService

    intake_service = IntakeService(
        storage,
        url_posting_fetcher,
        embedding,
        scoring=scoring_service,
        pending_actions=pending_actions_service,
        criteria=criteria_service,
    )
    feedback_service = FeedbackService(
        storage,
        learning_service,
        criteria=criteria_service,
        advanced_learning=advanced_learning_service,
        pending_actions=pending_actions_service,
    )
    # Chatbot (FR-CHAT-1): LLM-backed assistant over the attribute/criteria services,
    # routing integral changes through the shared confirmation gate (FR-FB-3).
    chat_service = ChatService(
        attribute_service=attribute_cloud_service,
        criteria_service=criteria_service,
        # FR-DIGEST: route a chat "approve all today's roles" directive through the
        # same gated digest-approval path the digest/Portal uses.
        digest_service=digest_service,
        llm=llm,
        learning=learning_service,
        storage=storage,
        # Stage 2.5 lane A: inject the workspace callback so the assistant can
        # surface auto-detected upcoming interviews (degrades silently when off).
        workspace=workspace,
        # FR-MIND-4 / FR-AGENT-7 / FR-OBS-2: read-only sources so the chat speaks AS the
        # 24/7 agent and reports its own work truthfully. ``agent_run_service`` (latest
        # next-action intent + today's applied count) and ``pending_actions_service``
        # (what's awaiting the user) already exist here; the scheduler heartbeat and the
        # debug read-model are wired additively below (they are built after this point).
        agent_run_service=agent_run_service,
        pending_actions=pending_actions_service,
        # FR-AGENT-1/2: the run-control seam so the chat can also STEER the loop
        # (pause/resume + daily throughput, clamped to the hard cap) by routing intents
        # to the SAME gated operations the ops surface uses (the run service does both).
        run_control=agent_run_service,
        # The apply-readiness gate's single source of "what's still missing": so the
        # assistant proactively gathers the apply essentials in chat and is truthful that
        # it can't begin applying until they're present (FR-CHAT-1 / FR-ONBOARD).
        onboarding=onboarding_service,
    )
    # Debug / observability read-models (FR-OBS-2 / FR-LOG-3): history, screenshots,
    # workflow state, logs, variant library — backed by real storage + orchestrator.
    admin_query_service = AdminQueryService(storage, orchestrator)
    # FR-OBS-2: give the chatbot the recent-application read-model so "what have you been
    # doing" answers from real history (wired additively — admin_query is built after the
    # chatbot; the scheduler heartbeat is wired the same way once the scheduler exists).
    chat_service._admin_query = admin_query_service

    # Phase 2: durable concurrency + final-approval gate + submission logging.
    from applicant.application.services.capacity_service import CapacityService
    from applicant.application.services.final_approval_service import FinalApprovalService
    from applicant.application.services.prefill_service import (
        PrefillDiagnosticsRing,
        PrefillService,
    )
    from applicant.application.services.submission_service import SubmissionService

    capacity_service = CapacityService(
        orchestrator,
        sandbox_concurrency=settings.sandbox_concurrency,
        llm_limit=settings.llm_rate_limit or None,
        llm_period=settings.llm_rate_period or None,
    )
    final_approval_service = FinalApprovalService(orchestrator, notification_service)
    from applicant.application.services.post_submission_service import PostSubmissionService
    post_submission_service = PostSubmissionService(
        storage,
        notification_service,
        learning=learning_service,
        workspace=workspace,
        # Dark-engine audit B2 items 8/9/60: lets the scheduler-driven ghosting +
        # follow-up-drafting sweep materialize both as Portal-visible pending
        # actions (reuses the SAME substrate every other pending-action already
        # surfaces through -- no new UI).
        pending_actions=pending_actions_service,
    )
    submission_service = SubmissionService(
        storage, browser, learning=learning_service, advanced_learning=advanced_learning_service,
        post_submission=post_submission_service,
    )
    # #305 Plan-as-Data: build the LLMPlanner only when PREFILL_USE_PLANNER=true
    # AND an LLM is configured — otherwise ``None`` and use_planner=False leaves
    # behaviour byte-identical to today.
    _prefill_planner = None
    if settings.prefill_use_planner and llm is not None:
        from applicant.adapters.planner.llm_planner import LLMPlanner
        _prefill_planner = LLMPlanner(llm=llm)

    # #350 CaptchaSolverPort: build the opt-in solver ONLY for a non-default strategy.
    # The shipped default (CAPTCHA_STRATEGY=human) leaves ``captcha_solver=None`` so the
    # pre-fill loop behaves byte-for-byte as today (every captcha → existing hand-off).
    captcha_solver = _build_captcha_solver(settings)

    # #306 self-improvement flywheel: ONE process-lived RoutineStore for the whole
    # process. The scheduler rebuilds a fresh AgentLoop (and its PrefillService) every
    # tick, so the induced per-ATS routines (AWM workflow-induction) + their ACE
    # success/failure counters MUST live OUTSIDE the per-tick instance or they silently
    # reset each tick — exactly like ``resume_ledger`` / ``curation_ledger``. Injected
    # into the main prefill_service AND every per-tick / per-request copy below. It only
    # influences PLANNING priors + reflective re-plan; the STOP boundary is untouched.
    from applicant.adapters.routine import InMemoryRoutineStore
    routine_store = InMemoryRoutineStore()

    # Lens 04 #39 / DISC-3: ONE process-lived PrefillDiagnosticsRing for the whole
    # process, exactly like ``routine_store`` above. The scheduler rebuilds a fresh
    # PrefillService every tick, so the operator-visible silent-degradation
    # diagnostics (#202/#203/#211/#223) must live OUTSIDE the per-tick instance or
    # they vanish the moment that tick's services are discarded — and the admin
    # ``/api/admin/prefill-diagnostics`` route (which reads THIS ``prefill_service``
    # singleton) would always see an empty ring even while a real tick's pre-fill was
    # failing loudly. Injected into the shared singleton AND every per-tick/per-
    # request rebuild below so a diagnostic recorded anywhere is visible everywhere.
    prefill_diagnostics_ring = PrefillDiagnosticsRing()

    prefill_service = PrefillService(
        storage=storage,
        browser=browser,
        detection=detection,
        sandbox=sandbox,
        credentials=credentials,
        notification=notification,
        llm=llm,
        captcha_solver=captcha_solver,
        resume_provider=BaseResumeProvider(storage),
        # FR-CUA: the desktop-assist port, used ONLY to complete a native OS file-picker
        # the DOM can't satisfy during résumé attachment. Defaults to the noop backend,
        # so the upload path degrades exactly as before until a real driver is operable.
        computer_use=computer_use,
        allow_automated_accounts=settings.allow_automated_accounts,
        # #177: flag a probable wrong-ATS / near-empty fill below this match-rate floor
        # for human review rather than offering it for submission.
        match_rate_floor=settings.ats_match_rate_floor,
        # #305 Plan-as-Data: opt-in, default OFF (PREFILL_USE_PLANNER env).
        planner=_prefill_planner,
        use_planner=settings.prefill_use_planner,
        # #306 self-improvement flywheel: the process-lived RoutineStore (AWM + ACE).
        routine_store=routine_store,
        # Lens 11 #22: lets the wrong-ATS check re-read a Settings > Automation
        # ``ats_match_rate_floor`` override live instead of only the env snapshot
        # above (``_effective_match_rate_floor``).
        setup_service=setup_service,
        # Lens 04 #39 / DISC-3: the process-lived diagnostics ring (see above).
        diagnostics_ring=prefill_diagnostics_ring,
    )
    # FR-ATTR-5: resolving a missing attribute resumes the stalled pre-fill using the
    # newly-stored value (wired additively to avoid a construction cycle).
    attribute_cloud_service.set_prefill_service(prefill_service)
    # #6: bridge onboarding intake into the engine (criteria + attribute cloud),
    # wired additively after both services exist (avoids a construction cycle).
    onboarding_service.set_criteria_service(criteria_service)
    onboarding_service.set_attribute_cloud_service(attribute_cloud_service)
    # #6: seed initial criteria at campaign creation (campaign_service is built before
    # criteria_service, so wire it additively here).
    campaign_service.set_criteria_service(criteria_service)

    # Perf item #8 (correctness): the TTL cache on ``_onboarding_gate`` above must
    # never paper over a genuine readiness change for longer than the TTL — and
    # the P0 zero-CLI acceptance scenario (tests/bdd/features/p0_oobe_gate.feature,
    # "automated work may begin" right after onboarding finishes) requires the
    # gate to open the INSTANT the required-to-apply essentials are saved, not
    # after a TTL delay. Invalidate the cache immediately after each write path
    # that can flip campaign readiness — onboarding-section saves, onboarding
    # completion, résumé ingestion, and criteria edits — so the common "just
    # finished onboarding" case never waits out the TTL. ``onboarding_service``
    # is always the container singleton (``deps.get_onboarding_service`` never
    # per-request-rebuilds it, unlike ``criteria_service``), so this reliably
    # covers onboarding/résumé writes in both the hermetic and real-DB lanes; the
    # TTL remains the defensive backstop for any write path this misses (e.g. a
    # per-request ``criteria_service`` rebuild under a real DB, FastAPI's
    # CONC-REQ-1 Session isolation, see ``_build_request_services`` below).
    def _invalidate_gate_after(bound_method):
        def _wrapped(*args, **kwargs):
            result = bound_method(*args, **kwargs)
            _onboarding_gate_cached.invalidate()
            return result

        return _wrapped

    criteria_service.edit_criteria = _invalidate_gate_after(criteria_service.edit_criteria)
    criteria_service.apply_learned_adjustment = _invalidate_gate_after(
        criteria_service.apply_learned_adjustment
    )
    onboarding_service.ingest_base_resume = _invalidate_gate_after(
        onboarding_service.ingest_base_resume
    )
    onboarding_service.complete = _invalidate_gate_after(onboarding_service.complete)
    onboarding_service.save_section = _invalidate_gate_after(onboarding_service.save_section)

    from applicant.application.services.material_service import MaterialService

    material_service = MaterialService(
        storage,
        truth_policy=settings.truth_policy,
        llm=llm,
        resume_tailoring=latex_tailor,
        embedding=embedding,
        docx_tailoring=docx_tailor,
        conversion_service=conversion_service,
        config_store=config_store,
        notifications=notification_service,
        pending_actions=pending_actions_service,
        learning=learning_service,
        advanced_learning=advanced_learning_service,
    )

    # Lane B (Stage 2.5): the capped deep-research tool over the WorkspacePort. One
    # instance per container so its per-campaign budget + dedupe cache are shared by
    # both the agent loop (auto-escalate) and the manual-trigger router.
    from applicant.application.services.research_service import ResearchService

    research_service = ResearchService(workspace=workspace)
    # #299: feed the SAME capped/deduped/cached research tool into the material-gen
    # path so on-demand cover-letter generation can fold in company research (config-
    # gated, budget-aware, best-effort). Wired additively (material_service is built
    # above, before research_service); the per-tick/per-request copies receive it at
    # construction in their factories below.
    material_service._research = research_service
    material_service._research_enabled = settings.material_research_enabled

    # Phase 5: the agent run loop + scheduler — the missing end-to-end drivers.
    from applicant.adapters.storage.ledger_persistence import ConfigLedgerStore
    from applicant.application.services.agent_loop import (
        AgentLoop,
        DigestLedger,
        PresubmitBlockLedger,
        ResumeLedger,
    )
    from applicant.application.services.scheduler import Scheduler

    # ONE resume ledger for the whole process. The scheduler rebuilds a fresh
    # AgentLoop every tick (per-tick Session isolation), so the resume backoff + the
    # failure cap must live OUTSIDE the loop instance or they reset every tick and
    # never take effect. Injected into both the shared loop and each per-tick loop.
    #
    # DISC-2: process-lived made it tick-safe, but a genuine process restart (an
    # update.sh deploy / OOM / crash) still wiped the backoff window, so every parked
    # application looked immediately "due" on the next boot and the loop could
    # re-attempt everything at once — a retry storm. Give it a restart-durable snapshot
    # store over the SAME app_config table the ladder/wizard state uses (no new table
    # or migration). On the real-DB lane the store opens a FRESH session per write via
    # ``session_factory`` (scheduler-thread-safe — it must NOT touch the boot Session,
    # CONC-2), exactly like AuditLogService's per-event writes; with no DB it round-
    # trips through the in-memory config store (nothing survives a restart there
    # anyway). ``restore()`` reloads the snapshot at boot — call it BEFORE any loop
    # binds the ledger's dicts (below) so the reloaded state is what the loops see.
    resume_ledger = ResumeLedger(
        persister=ConfigLedgerStore(
            "agent.resume_ledger",
            session_factory=session_factory,
            memory_store=config_store if session_factory is None else None,
        )
    )
    resume_ledger.restore()
    # ONE digest ledger for the whole process (same reasoning: the per-tick rebuild
    # would reset the "already delivered today" guard, re-sending the digest every
    # tick). Injected into both the shared loop and each per-tick loop.
    digest_ledger = DigestLedger()
    # ONE pre-submit-block ledger for the whole process (dark-engine audit #61):
    # the per-tick rebuild would otherwise lose every block reason (and any operator
    # override) the moment the next tick's fresh AgentLoop is built. Injected into
    # both the shared loop (admin reads) and each per-tick loop (the tick that writes
    # it), exactly like resume_ledger/digest_ledger above.
    presubmit_block_ledger = PresubmitBlockLedger()

    # FR-MIND: the agent-learning substrate. Build the curated-memory / skills / recall
    # adapter trio (default ``in_memory`` — hermetic, no deps; ``bridge`` reaches the
    # front-door substrate over the WorkspacePort per agent-intelligence.md §10), and
    # ONE process-lived CurationLedger for the whole process. Like resume_ledger, the
    # scheduler rebuilds the per-tick services every tick, so the curation dedupe state
    # must live OUTSIDE the loop/service instance or it resets every tick (FR-MIND-10).
    from applicant.adapters.memory import build_agent_memory
    from applicant.application.services.curation_service import (
        CurationLedger,
        CurationService,
        build_llm_summarizer,
    )
    from applicant.application.services.run_history import RunHistoryProvider

    agent_memory = build_agent_memory(settings, workspace)
    # FR-MIND-5: give the already-built chatbot the advisory curated-memory + saved-
    # playbook context (the main ChatService is constructed above, before the substrate;
    # wire it additively so reasoning can consult memory without a construction cycle).
    # The per-request ChatService gets it directly in the request factory below.
    chat_service._agent_memory = agent_memory
    # FR-MIND-1/2/5: likewise give the already-built scoring + material services the
    # advisory curated-memory / saved-playbook substrate (both are constructed above,
    # before the substrate; wire it additively so viability scoring + generation can
    # consult learned context without a construction cycle). The per-tick and
    # per-request copies receive it directly in their factories below.
    scoring_service._agent_memory = agent_memory
    material_service._agent_memory = agent_memory
    # FR-LEARN-5 + FR-MIND-3: give the conversion-learning service the recall index so
    # its discovery/scoring/variant-selection bias can also run the advisory "roles like
    # the ones that converted" probe. Additive (the singleton advanced service is built
    # above, before the substrate); the per-tick/per-request copies receive recall at
    # construction in their factories below. No-op when recall is absent.
    advanced_learning_service._recall = agent_memory.recall
    # FR-MIND-1/3: let onboarding completion SEED the agent from the user's own profile/
    # résumé — a bounded set of curated memory entries + recall index of their history —
    # so the agent is not cold-start on day one. Optional/additive: with the in-memory
    # default substrate it seeds into that store; absent a substrate it is a no-op.
    onboarding_service.set_agent_memory(agent_memory)
    curation_ledger = CurationLedger()
    # FR-MIND-7/-13: a CHEAP, OPTIONAL LLM-backed summarizer from CURATION_MODEL. It
    # falls back to the trivial heuristic when no LLM is configured, so the hermetic
    # lane (no model) behaves exactly as before. Reuses the main ``llm`` ladder (the
    # CURATION_MODEL id is advisory until a dedicated curation tier is pinned).
    curation_summarizer = build_llm_summarizer(llm, model=settings.curation_model)

    def _make_curation(mem, skills, recall) -> CurationService:
        return CurationService(
            memory_store=mem,
            skill_store=skills,
            ledger=curation_ledger,
            # FR-MIND-3: index each curated run into recall so ``recall.search`` returns
            # real hits. Local/cheap (in-memory default; bridge no-ops when OFF).
            recall=recall,
            summarizer=curation_summarizer,
            memory_write_approval=settings.memory_write_approval,
            skills_write_approval=settings.skills_write_approval,
        )

    curation_service = _make_curation(
        agent_memory.memory, agent_memory.skills, agent_memory.recall
    )
    # FR-MIND-6: is a desktop-assist driver operable? Only then is the bounded
    # ``desktop`` chat tool offered (a noop/absent driver => never offered). Derived
    # from the driver's own preflight (server-side ground truth), defaulting safely to
    # False so the tool stays dark unless a real driver reports healthy.
    try:
        _desktop_operable = bool(computer_use.health().ok)
    except Exception:
        _desktop_operable = False
    # FR-MIND-6: give the chat ASSISTANT its self-callable tool surface. Additive +
    # capability-gated: ``CHAT_TOOLS=auto`` only engages the tool loop when the model
    # advertises tool calling; writes stage through curation (FR-MIND-9); each tool is
    # gated by the FR-UI-4 registry. ``off`` (default) keeps the single-shot path.
    chat_service._curation_service = curation_service
    chat_service._tool_registry = tool_registry
    chat_service._computer_use = computer_use
    chat_service._desktop_operable = _desktop_operable
    chat_service._chat_tools = (settings.chat_tools or "off").strip().lower()
    # FR-MIND-7 + FR-LEARN-3: feed the scheduled nudge BOTH real run history (recent
    # applications + outcomes, mapped to RunSummaries) AND the user's OWN feedback —
    # digest decline reasons (FR-DIG-5) + résumé/answer revision instructions
    # (FR-RESUME-8), mapped to preference-tagged summaries — composed into one provider
    # so both reach the curated-memory loop. Bounded + cheap; byte-identical when empty.
    from applicant.application.services.feedback_history import FeedbackSummaryProvider

    run_summaries_provider = _compose_summary_providers(
        RunHistoryProvider(), FeedbackSummaryProvider()
    )

    # FR-MIND-6 / FR-CUA-2: the AUTONOMOUS loop's agent-callable tool set. A factory that
    # builds the SAME guarded tools the chat assistant uses (``ChatToolbox`` via
    # ``LoopToolset``) per campaign, ONLY when ``LOOP_TOOLS`` is opted in AND the model
    # advertises tool calling — otherwise it returns ``None`` and the loop runs exactly as
    # today (default OFF ⇒ no tools registered). The factory binds whichever curation
    # service the call site owns so loop-initiated writes stage into the SAME process-lived
    # review queue (FR-MIND-9/-10); the registry + desktop driver are process-lived too.
    from applicant.application.services.loop_tools import build_loop_toolset

    def _make_loop_toolset_factory(curation):
        def _factory(campaign_id, tick_llm):
            return build_loop_toolset(
                setting=settings.loop_tools,
                llm=tick_llm,
                campaign_id=campaign_id,
                agent_memory=agent_memory,
                curation_service=curation,
                tool_registry=tool_registry,
                computer_use=computer_use,
                desktop_operable=_desktop_operable,
            )

        return _factory

    agent_loop = AgentLoop(
        storage=storage,
        agent_run_service=agent_run_service,
        discovery_service=discovery_service,
        scoring_service=scoring_service,
        digest_service=digest_service,
        criteria_service=criteria_service,
        prefill_service=prefill_service,
        material_service=material_service,
        submission_service=submission_service,
        learning_service=learning_service,
        notification_service=notification_service,
        capacity_service=capacity_service,
        final_approval_service=final_approval_service,
        sandbox=sandbox,
        orchestrator=orchestrator,
        setup_service=setup_service,
        research_service=research_service,
        resume_ledger=resume_ledger,
        digest_ledger=digest_ledger,
        llm=llm,
        loop_toolset_factory=_make_loop_toolset_factory(curation_service),
        # G07: pre-submit safety parameters from settings.
        presubmit_safety_params=presubmit_safety_params,
        # dark-engine audit #61: process-lived block ledger (reason + override).
        presubmit_block_ledger=presubmit_block_ledger,
        # P1-6: process-lived usage ledger the shared ``llm`` singleton feeds.
        usage_ledger=usage_ledger,
    )
    # CONC-2: the 24/7 scheduler thread MUST NOT share the request-scoped Session
    # (SQLAlchemy Sessions are not thread-safe). When a real DB is configured, build a
    # FRESH Session + SqlAlchemyStorage + storage-bound services for each tick and
    # close the session afterwards. The stateless adapters (llm/embedding/notifier/
    # orchestrator/sandbox/...) and session-free services are reused. With in-memory
    # storage (tests / no-DB) there is no Session to isolate, so the shared loop is used.
    def _build_tick_services(tick_storage):
        # CONC-2: a per-tick setup/onboarding stack bound to THIS tick's fresh Session
        # (never the process-lived boot Session the request gate reads), so the 24/7
        # scheduler thread's automated-work gate + apply-readiness reads can never race
        # a concurrent gated request handler on one non-thread-safe Session. Mirrors the
        # per-tick storage isolation below; the scheduler + this tick's AgentLoop/
        # PrefillService all read the gate through ``tick_setup_service``.
        tick_session = getattr(tick_storage, "_session", None)
        tick_config_store = (
            SqlAlchemyAppConfigStore(tick_session)
            if tick_session is not None
            else InMemoryAppConfigStore()
        )
        tick_setup_service, _tick_onboarding, _tick_gate_cache = _build_setup_stack(
            tick_storage, tick_config_store
        )
        # #44: share the ONE process-lived EpisodicLessonLedger (not a per-tick
        # instance), so a lesson reflected on in one tick is recalled in the next.
        ls = LearningService(tick_storage, embedding, lesson_ledger=lesson_ledger)
        adv = AdvancedLearningService(
            base=ls, storage=tick_storage, recall=agent_memory.recall
        )
        ds = DiscoveryService(
            tick_storage,
            discovery,
            embedding,
            ls,
            tool_registry=tool_registry,
            advanced_learning=adv,
        )
        ss = ScoringService(
            tick_storage,
            llm,
            embedding,
            learning=ls,
            advanced_learning=adv,
            tool_registry=tool_registry,
            agent_memory=agent_memory,
        )
        cs = CriteriaService(tick_storage, llm)
        # RT Phase 3: the per-tick run recorder fans the live ``agent`` event — this
        # is the path the 24/7 scheduler drives, so it is what surfaces a running
        # agent's progress to the operator's tabs in realtime.
        ars = AgentRunService(tick_storage, realtime=agent_publisher)
        pas = PendingActionsService(tick_storage, realtime=notif_publisher)
        dg = DigestService(
            tick_storage,
            notification,
            ss,
            learning=ls,
            criteria=cs,
            notification_service=notification_service,
            pending_actions=pas,
            presubmit_safety_params=presubmit_safety_params,
            digest_cache=digest_cache,
        )
        from applicant.application.services.post_submission_service import PostSubmissionService
        post_sub = PostSubmissionService(
            tick_storage,
            notification_service,
            learning=ls,
            workspace=workspace,
            # B2 items 8/9/60: this tick's isolated PendingActionsService (CONC-2),
            # sharing this tick's Session -- see Scheduler._run_post_submission_sweep.
            pending_actions=pas,
        )
        sub = SubmissionService(
            tick_storage, browser, learning=ls, advanced_learning=adv,
            post_submission=post_sub,
        )
        pf = PrefillService(
            storage=tick_storage,
            browser=browser,
            detection=detection,
            sandbox=sandbox,
            credentials=credentials,
            notification=notification,
            llm=llm,
            resume_provider=BaseResumeProvider(tick_storage),
            # FR-CUA: process-lived desktop-assist port (built ONCE above, never rebuilt
            # per tick) so the autonomous pre-fill loop can complete a native OS
            # file-picker the DOM can't satisfy. Defaults to noop → degrades as before.
            computer_use=computer_use,
            # #177: flag a probable wrong-ATS / near-empty fill below this floor.
            match_rate_floor=settings.ats_match_rate_floor,
            # #305 Plan-as-Data: reuse the same planner as the main prefill_service.
            planner=_prefill_planner,
            use_planner=settings.prefill_use_planner,
            # #350: process-lived opt-in captcha solver (None for the default hand-off).
            captcha_solver=captcha_solver,
            # #306: share the ONE process-lived RoutineStore (NOT a per-tick instance),
            # so induced routines + ACE counters survive the per-tick loop rebuild.
            routine_store=routine_store,
            # Lens 11 #22: live re-read of a Settings > Automation match-rate-floor
            # override (see the main ``prefill_service`` build above). CONC-2: the
            # per-tick, Session-isolated setup service so this tick's re-read never
            # touches the boot Session the request gate reads.
            setup_service=tick_setup_service,
            # Lens 04 #39 / DISC-3: share the ONE process-lived diagnostics ring (NOT
            # a per-tick instance), so silent-degradation diagnostics recorded during
            # this tick survive the per-tick loop rebuild.
            diagnostics_ring=prefill_diagnostics_ring,
        )
        mat = MaterialService(
            tick_storage,
            truth_policy=settings.truth_policy,
            llm=llm,
            resume_tailoring=latex_tailor,
            embedding=embedding,
            docx_tailoring=docx_tailor,
            conversion_service=conversion_service,
            config_store=config_store,
            notifications=notification_service,
            pending_actions=pas,
            learning=ls,
            advanced_learning=adv,
            agent_memory=agent_memory,
            research_service=research_service,
            research_enabled=settings.material_research_enabled,
        )
        # FR-MIND-10: rebuild the per-tick CurationService but share the SAME
        # process-lived CurationLedger + agent-memory adapters (+ recall + summarizer)
        # as the main service, so the curation dedupe state survives the per-tick
        # rebuild instead of resetting. Built before the loop so the loop's tool set
        # (FR-MIND-6) stages writes into this SAME process-lived review queue.
        tick_curation = _make_curation(
            agent_memory.memory, agent_memory.skills, agent_memory.recall
        )
        loop = AgentLoop(
            storage=tick_storage,
            agent_run_service=ars,
            discovery_service=ds,
            scoring_service=ss,
            digest_service=dg,
            criteria_service=cs,
            prefill_service=pf,
            material_service=mat,
            submission_service=sub,
            learning_service=ls,
            notification_service=notification_service,
            capacity_service=capacity_service,
            final_approval_service=final_approval_service,
            sandbox=sandbox,
            orchestrator=orchestrator,
            # CONC-2: the per-tick, Session-isolated setup service (see the top of this
            # factory) so the loop's automated-work gate reads this tick's fresh Session,
            # never the boot Session a concurrent request handler's gate is reading.
            setup_service=tick_setup_service,
            research_service=research_service,
            resume_ledger=resume_ledger,
            digest_ledger=digest_ledger,
            llm=llm,
            # FR-MIND-6 / FR-CUA-2: the per-tick loop's tool set stages through this
            # tick's curation service (shared process-lived ledger). Default OFF ⇒ None.
            loop_toolset_factory=_make_loop_toolset_factory(tick_curation),
            # G07: pre-submit safety parameters from settings.
            presubmit_safety_params=presubmit_safety_params,
            # dark-engine audit #61: process-lived block ledger (reason + override).
            presubmit_block_ledger=presubmit_block_ledger,
            # P1-6: SAME process-lived usage ledger as the shared loop above, so
            # per-tick usage is drained into THIS tick's durable agent_runs.stats.
            usage_ledger=usage_ledger,
        )
        return {
            "storage": tick_storage,
            "agent_loop": loop,
            "digest_service": dg,
            "notification_service": notification_service,
            "final_approval_service": final_approval_service,
            "curation_service": tick_curation,
            # B2 items 8/9/60: the per-tick, Session-isolated PostSubmissionService so
            # the scheduler's ghosting/follow-up sweep runs against THIS tick's storage
            # (CONC-2), same pattern as ``curation_service`` above.
            "post_submission_service": post_sub,
            # CONC-2: the per-tick, Session-isolated setup service so the scheduler's own
            # automated-work gate + automation-prefs reads use THIS tick's fresh Session
            # (see Scheduler.tick), never the boot Session the request gate reads.
            "setup_service": tick_setup_service,
        }

    # CONC-REQ-1: build the storage-bound services for ONE request from a per-request
    # storage. Stateless adapters (llm/embedding/notifier/orchestrator/sandbox/...) and
    # session-free services (setup/notification ladder/capacity/final-approval) are
    # reused; everything that touches the Session is rebuilt against ``req_storage``.
    def _build_request_services(req_storage) -> dict:
        rs_config_store = (
            SqlAlchemyAppConfigStore(getattr(req_storage, "_session", None))
            if getattr(req_storage, "_session", None) is not None
            else InMemoryAppConfigStore()
        )
        # #44: share the ONE process-lived EpisodicLessonLedger across request-scoped
        # LearningService instances too, so the admin/Mind-panel read reflects the
        # SAME lessons the running loop has recorded.
        rs_ls = LearningService(req_storage, embedding, lesson_ledger=lesson_ledger)
        rs_adv = AdvancedLearningService(
            base=rs_ls, storage=req_storage, recall=agent_memory.recall
        )
        rs_criteria = CriteriaService(req_storage, llm)
        rs_pas = PendingActionsService(req_storage, realtime=notif_publisher)
        rs_scoring = ScoringService(
            req_storage,
            llm,
            embedding,
            learning=rs_ls,
            advanced_learning=rs_adv,
            tool_registry=tool_registry,
            agent_memory=agent_memory,
        )
        rs_conversion = ConversionService(
            latex_tailor=latex_tailor, config_store=rs_config_store
        )
        rs_digest = DigestService(
            req_storage,
            notification,
            rs_scoring,
            learning=rs_ls,
            criteria=rs_criteria,
            notification_service=notification_service,
            pending_actions=rs_pas,
            presubmit_safety_params=presubmit_safety_params,
            digest_cache=digest_cache,
        )
        rs_attr = AttributeCloudService(
            req_storage, pending_actions=rs_pas, advanced_learning=rs_adv
        )
        # P1-9: request-scoped direct-URL intake, sharing this request's Session-
        # bound scoring/pending/criteria services (the fetcher is process-lived).
        from applicant.application.services.intake_service import IntakeService as _IntakeService

        rs_intake = _IntakeService(
            req_storage,
            url_posting_fetcher,
            embedding,
            scoring=rs_scoring,
            pending_actions=rs_pas,
            criteria=rs_criteria,
        )
        rs_feedback = FeedbackService(
            req_storage, rs_ls, criteria=rs_criteria, advanced_learning=rs_adv,
            pending_actions=rs_pas,
        )
        rs_admin = AdminQueryService(req_storage, orchestrator)
        # FR-AGENT-7: per-request, req-storage-bound run reader (read-only ``status``) so
        # the chatbot's own-work report uses this request's isolated Session. The SAME
        # service is the run-control seam (FR-AGENT-1/2) for steering from chat — a
        # pause/resume/throughput change persists on THIS request's session (CONC-REQ-1).
        rs_agent_runs = AgentRunService(req_storage, realtime=agent_publisher)
        # Request-scoped onboarding so the chat's apply-readiness gate ("what's still
        # missing before I can apply") reads THIS request's criteria + résumé state on its
        # own isolated Session (CONC-REQ-1). Bound to rs_criteria so a free-text criteria
        # statement the user gives in chat counts toward the gate immediately.
        rs_onboarding = OnboardingService(
            storage=req_storage,
            config_store=rs_config_store,
            resume_parser=resume_parser,
        )
        rs_onboarding.set_criteria_service(rs_criteria)
        rs_onboarding.set_attribute_cloud_service(rs_attr)
        rs_chat = ChatService(
            attribute_service=rs_attr,
            criteria_service=rs_criteria,
            # FR-DIGEST: request-scoped digest service so a chat bulk-approve persists
            # on this request's session (mirrors the main ChatService build).
            digest_service=rs_digest,
            llm=llm,
            learning=rs_ls,
            storage=req_storage,
            workspace=workspace,  # Stage 2.5 lane A (see main ChatService build)
            # FR-MIND-5: advisory curated-memory + saved-playbook context. Shares the
            # process-lived adapter trio; read fresh per call (FR-MIND-10).
            agent_memory=agent_memory,
            # FR-MIND-4 / FR-AGENT-7 / FR-OBS-2: the agent speaks AS the 24/7 agent and
            # reports its own work from real, request-scoped read-only sources. The
            # scheduler heartbeat is the process-lived singleton (no Session), wired
            # additively below since it is built after this factory is defined.
            agent_run_service=rs_agent_runs,
            pending_actions=rs_pas,
            admin_query=rs_admin,
            # FR-AGENT-1/2: same req-storage-bound run service is the control seam so a
            # pause/resume/throughput steered from chat persists on this request's session.
            run_control=rs_agent_runs,
            # FR-MIND-6: the assistant's self-callable tool surface (additive +
            # capability-gated). The agent-memory stores + the CurationLedger are
            # process-lived (shared), so the main ``curation_service`` stages chat-
            # initiated memory/skill writes into the SAME review queue. The FR-UI-4
            # registry + the bounded desktop driver are likewise process-lived.
            curation_service=curation_service,
            tool_registry=tool_registry,
            computer_use=computer_use,
            desktop_operable=_desktop_operable,
            chat_tools=(settings.chat_tools or "off").strip().lower(),
            # Apply-readiness gate source for the proactive essentials-gathering in chat.
            onboarding=rs_onboarding,
        )
        rs_chat._scheduler = scheduler
        from applicant.application.services.post_submission_service import PostSubmissionService
        rs_post_sub = PostSubmissionService(
            req_storage,
            notification_service,
            learning=rs_ls,
            workspace=workspace,
            # B2 items 8/9/60: this request's isolated PendingActionsService
            # (CONC-REQ-1), so a request-triggered write (e.g. the new read
            # endpoint below) sees this request's own Session-scoped data.
            pending_actions=rs_pas,
        )
        rs_submission = SubmissionService(
            req_storage, browser, learning=rs_ls, advanced_learning=rs_adv,
            post_submission=rs_post_sub,
        )
        rs_prefill = PrefillService(
            storage=req_storage,
            browser=browser,
            detection=detection,
            sandbox=sandbox,
            credentials=credentials,
            notification=notification,
            llm=llm,
            resume_provider=BaseResumeProvider(req_storage),
            # FR-CUA: same process-lived desktop-assist port (defaults to noop).
            computer_use=computer_use,
            # #177: flag a probable wrong-ATS / near-empty fill below this floor.
            match_rate_floor=settings.ats_match_rate_floor,
            # #305 Plan-as-Data: reuse the same planner as the main prefill_service.
            planner=_prefill_planner,
            use_planner=settings.prefill_use_planner,
            # #350: process-lived opt-in captcha solver (None for the default hand-off).
            captcha_solver=captcha_solver,
            # #306: share the ONE process-lived RoutineStore across request scopes too.
            routine_store=routine_store,
            # Lens 11 #22: live re-read of a Settings > Automation match-rate-floor
            # override (see the main ``prefill_service`` build above).
            setup_service=setup_service,
            # Lens 04 #39 / DISC-3: share the ONE process-lived diagnostics ring
            # across request scopes too (see the main ``prefill_service`` build above).
            diagnostics_ring=prefill_diagnostics_ring,
        )
        rs_attr.set_prefill_service(rs_prefill)
        rs_material = MaterialService(
            req_storage,
            truth_policy=settings.truth_policy,
            llm=llm,
            resume_tailoring=latex_tailor,
            embedding=embedding,
            docx_tailoring=docx_tailor,
            conversion_service=rs_conversion,
            config_store=rs_config_store,
            notifications=notification_service,
            pending_actions=rs_pas,
            learning=rs_ls,
            advanced_learning=rs_adv,
            agent_memory=agent_memory,
            research_service=research_service,
            research_enabled=settings.material_research_enabled,
        )
        rs_campaign = CampaignService(req_storage)
        rs_campaign.set_criteria_service(rs_criteria)
        # #363: request-scoped purge/retention so a campaign-delete cascades on THIS
        # request's isolated Session (CONC-REQ-1). The credential store is process-lived.
        rs_data_lifecycle = DataLifecycleService(
            req_storage,
            credentials,
            pii_retention_days=settings.pii_retention_days,
        )
        # P1-6: request-scoped cost & pace guardrails read model (CONC-REQ-1).
        rs_cost = CostService(req_storage)
        return {
            "storage": req_storage,
            "data_lifecycle_service": rs_data_lifecycle,
            "cost_service": rs_cost,
            "pending_actions_service": rs_pas,
            "digest_service": rs_digest,
            "attribute_cloud_service": rs_attr,
            "intake_service": rs_intake,
            "feedback_service": rs_feedback,
            "chat_service": rs_chat,
            "admin_query_service": rs_admin,
            "submission_service": rs_submission,
            "post_submission_service": rs_post_sub,
            "prefill_service": rs_prefill,
            "material_service": rs_material,
            "criteria_service": rs_criteria,
            "campaign_service": rs_campaign,
            "conversion_service": rs_conversion,
            "scoring_service": rs_scoring,
            "learning_service": rs_ls,
        }

    tick_services_factory = None
    request_services_factory = None
    if session_factory is not None:
        from applicant.adapters.storage.repositories import SqlAlchemyStorage

        def tick_services_factory():  # noqa: F811 - per-tick isolated session (CONC-2)
            tick_session = session_factory()
            services = _build_tick_services(SqlAlchemyStorage(tick_session))
            services["_session"] = tick_session
            return services

        def request_services_factory():  # noqa: F811 - per-request isolated session
            req_session = session_factory()
            services = _build_request_services(SqlAlchemyStorage(req_session))
            services["_session"] = req_session
            return services

    # RT Phase 3 (realtime-websocket.md): the upstream ``agent`` co-steer dispatcher.
    # An authorized ``agent/pause``/``agent/redirect``/``agent/approve`` frame is PURE
    # TRANSPORT to an EXISTING owner-gated service (the SAME methods the HTTP surface
    # uses: ``set_active`` for pause, ``configure_run`` for redirect, and
    # ``MaterialService.approve`` for approve — the identical review-before-submit gate
    # ``POST /api/documents/{id}/approve`` calls). The socket adds NO new authority, and
    # every OTHER submit/authorize verb never reaches here (default-denied at the
    # envelope seam). The WS handler runs on the app loop, so each command gets a FRESH,
    # session-isolated service (never the request/boot Session) exactly like the
    # per-request factory above; the no-DB lane falls back to the shared singleton.
    from applicant.app.realtime import get_registry, make_agent_control_dispatcher

    def _agent_control_service():
        if session_factory is not None:
            from applicant.adapters.storage.repositories import SqlAlchemyStorage

            cmd_session = session_factory()
            svc = AgentRunService(SqlAlchemyStorage(cmd_session), realtime=agent_publisher)

            def _close() -> None:
                try:
                    cmd_session.close()
                except Exception:  # pragma: no cover - defensive: close never raises
                    pass

            return svc, _close
        # In-memory / no-DB lane: no Session to isolate, reuse the shared service.
        return agent_run_service, (lambda: None)

    def _approval_service():
        # ``agent/approve`` delegates to the EXISTING owner-gated review gate,
        # ``MaterialService.approve`` — the SAME method the HTTP approve router calls.
        # Reuse the per-request services factory so the MaterialService is wired
        # (and Session-isolated) identically to a normal request; the no-DB lane
        # falls back to the shared singleton. Never a NEW authority: it can only do
        # what ``POST /api/documents/{id}/approve`` already does, review gate included.
        if request_services_factory is not None:
            services = request_services_factory()
            mat = services["material_service"]
            req_session = services.get("_session")

            def _close() -> None:
                try:
                    if req_session is not None:
                        req_session.close()
                except Exception:  # pragma: no cover - defensive: close never raises
                    pass

            return mat, _close
        return material_service, (lambda: None)

    get_registry().bind_agent_control(
        make_agent_control_dispatcher(_agent_control_service, _approval_service)
    )

    # FR-AGENT-7 / FR-OBS-2: the proactive periodic agent status update — the PUSH
    # sibling of the chatbot self-report. Assembles a short, first-person, white-labeled
    # summary from READ-ONLY sources (run status + next-action intent, recent history,
    # the pending count, the scheduler heartbeat) and pushes it through the EXISTING
    # notification path (in-app inbox + opt-in fan-out). All sources are optional/defensive
    # (no fabrication); the scheduler gates the cadence (default off => dormant, no
    # behavior change). ``STATUS_UPDATE_SCHEDULE`` is read through Settings (like its
    # siblings) so the deploy surface stays uniform; ``off``/``daily``.
    from applicant.application.services.status_update import StatusUpdateService

    status_update_service = StatusUpdateService(
        notification_service=notification_service,
        agent_run_service=agent_run_service,
        admin_query=admin_query_service,
        pending_actions=pending_actions_service,
        # scheduler is wired additively below (it is built after this point).
    )
    status_update_schedule = settings.status_update_schedule

    # FR-NOTIF / FR-ONBOARD: the proactive "I'm still blocked on essentials" nudge. When
    # automated work is BLOCKED specifically because apply-essentials are missing (read
    # from ``onboarding_service.apply_readiness().missing`` — never fabricated) and the
    # user has gone idle, it pushes ONE friendly first-person notification naming exactly
    # what's still needed, through the EXISTING notification path (in-app inbox + opt-in
    # fan-out). Default schedule ``off`` => dormant (byte-identical hermetic behavior).
    from applicant.application.services.essentials_nudge import EssentialsNudgeService

    essentials_nudge_service = EssentialsNudgeService(
        notification_service=notification_service,
        onboarding_service=onboarding_service,
    )

    scheduler = Scheduler(
        storage=storage,
        agent_loop=agent_loop,
        digest_service=digest_service,
        notification_service=notification_service,
        final_approval_service=final_approval_service,
        tick_services_factory=tick_services_factory,
        setup_service=setup_service,
        interval_seconds=settings.scheduler_interval_seconds,
        # FR-MIND-7: drive the closed-loop curation nudge on the configured cadence
        # (default ``off`` => dormant). The shared curation_service is the fallback; the
        # per-tick factory supplies the isolated-session one sharing the SAME ledger.
        curation_service=curation_service,
        curation_schedule=settings.curation_schedule,
        # FR-MIND-7 / FR-LEARN-3: the nudge reviews ACTUAL runs + the user's own
        # feedback (composed provider above), mapped to RunSummaries, bounded + cheap.
        run_summaries_provider=run_summaries_provider,
        # FR-AGENT-7 / FR-OBS-2: the periodic status update on the configured cadence
        # (default ``off`` => dormant, byte-identical hermetic behavior).
        status_update_service=status_update_service,
        status_update_schedule=status_update_schedule,
        # FR-NOTIF / FR-ONBOARD: the proactive "still blocked on essentials" nudge on the
        # configured cadence (default ``off`` => dormant, byte-identical hermetic behavior).
        essentials_nudge_service=essentials_nudge_service,
        essentials_nudge_schedule=settings.essentials_nudge_schedule,
        # Top-25 #18: the weekly recap (applications sent + best-performing source) on
        # the configured cadence (default ``off`` => dormant, byte-identical hermetic
        # behavior). Reuses the already-wired ``digest_service`` above — no new service.
        weekly_recap_schedule=settings.weekly_recap_schedule,
        # #363: PII retention sweep — prunes stored PII/EEO older than the configured
        # window once per UTC day (default ``off`` => dormant, byte-identical behavior).
        retention_service=RetentionService(
            storage,
            pii_retention_days=settings.pii_retention_days,
        ),
        retention_schedule=settings.pii_retention_schedule,
        # Dark-engine audit B2 items 8/9/60: drives PostSubmissionService's
        # check_ghosting + follow-up-drafting sweep once per (campaign, UTC day) —
        # runs unconditionally (like the daily digest), gated only by the SAME
        # automated-work gate every other proactive push already respects; the
        # shared singleton here is the fallback when no per-tick factory is
        # configured (in-memory / no-DB), mirroring every sibling service above.
        post_submission_service=post_submission_service,
        # FR-OBS-2 / NFR-OPS: how many CONSECUTIVE failed ticks raise ONE operator alert
        # through the existing notification ladder (idempotent). Uses the process-lived
        # metrics singleton so the agent-status surface reads the same registry.
        failure_alert_threshold=settings.loop_failure_alert_threshold,
    )
    # FR-OBS-2: give the chatbot the live scheduler heartbeat so "what are you doing now /
    # when do you run next" answer from the real tick state (wired additively — the
    # scheduler is built after the chatbot).
    chat_service._scheduler = scheduler
    # Same live heartbeat for the proactive status update ("right now I'm running a cycle").
    status_update_service._scheduler = scheduler

    # P5-3: opt-in error telemetry. ``status_fn`` reads ``setup_service.telemetry_status()``
    # fresh on every capture -- never a snapshot taken at boot -- so a runtime Settings
    # toggle (or local-only mode flipping) is honored immediately, with no restart.
    telemetry = TelemetryReporter(
        status_fn=setup_service.telemetry_status,
        app_version=__version__,
    )

    return Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        storage=storage,
        llm=llm,
        discovery=discovery,
        embedding=embedding,
        browser=browser,
        detection=detection,
        sandbox=sandbox,
        computer_use=computer_use,
        latex_tailor=latex_tailor,
        docx_tailor=docx_tailor,
        font_installer=font_installer,
        credentials=credentials,
        notification=notification,
        orchestrator=orchestrator,
        tool_registry=tool_registry,
        workspace=workspace,
        resume_parser=resume_parser,
        setup_service=setup_service,
        campaign_service=campaign_service,
        data_lifecycle_service=data_lifecycle_service,
        cost_service=cost_service,
        onboarding_service=onboarding_service,
        font_service=font_service,
        conversion_service=conversion_service,
        discovery_service=discovery_service,
        scoring_service=scoring_service,
        learning_service=learning_service,
        advanced_learning_service=advanced_learning_service,
        criteria_service=criteria_service,
        agent_run_service=agent_run_service,
        notification_service=notification_service,
        pending_actions_service=pending_actions_service,
        digest_service=digest_service,
        attribute_cloud_service=attribute_cloud_service,
        intake_service=intake_service,
        feedback_service=feedback_service,
        chat_service=chat_service,
        admin_query_service=admin_query_service,
        capacity_service=capacity_service,
        final_approval_service=final_approval_service,
        post_submission_service=post_submission_service,
        submission_service=submission_service,
        prefill_service=prefill_service,
        material_service=material_service,
        model_endpoint_service=model_endpoint_service,
        llm_router=smart_router,
        research_service=research_service,
        agent_loop=agent_loop,
        scheduler=scheduler,
        status_update_service=status_update_service,
        essentials_nudge_service=essentials_nudge_service,
        agent_memory=agent_memory,
        curation_service=curation_service,
        curation_ledger=curation_ledger,
        request_services_factory=request_services_factory,
        telemetry=telemetry,
    )
