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

from dataclasses import dataclass
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
from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.resume_tailoring.docx_tailor import DocxTailor
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
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
from applicant.application.services.digest_service import DigestService
from applicant.application.services.discovery_service import DiscoveryService
from applicant.application.services.feedback_service import FeedbackService
from applicant.application.services.font_service import FontService
from applicant.application.services.learning_advanced import AdvancedLearningService
from applicant.application.services.learning_service import LearningService
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.onboarding_service import OnboardingService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.application.services.scoring_service import ScoringService
from applicant.application.services.setup_service import SetupService
from applicant.application.workflows import application_pipeline


@dataclass
class Container:
    """Holds every adapter + service. Built once at startup, injected via deps."""

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
    latex_tailor: Any
    docx_tailor: Any
    font_installer: Any
    credentials: Any
    notification: Any
    orchestrator: Any
    tool_registry: Any

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
    # Phase 2 services (sandbox concurrency, final-approval gate, submission log).
    capacity_service: Any = None
    final_approval_service: Any = None
    submission_service: Any = None
    prefill_service: Any = None
    material_service: Any = None
    # Phase 5: the agent run loop + scheduler that finally drive everything end-to-end.
    agent_loop: Any = None
    scheduler: Any = None


def _build_storage(settings: Settings) -> tuple[Any, Any, Any]:
    """Return (engine, session_factory, storage). Falls back to in-memory."""
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
    except Exception:
        pass
    # No reachable DB (tests / first boot) — use in-memory storage.
    return None, None, InMemoryStorage()


def _build_orchestrator(settings: Settings) -> Any:
    if settings.orchestrator_backend == "dbos":
        # STAGE B: DBOS requires a live Postgres; only select when truly available.
        from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator

        return DbosOrchestrator(settings.database_url)
    return CheckpointShimOrchestrator(settings.checkpoint_dir)


def build_container(settings: Settings | None = None) -> Container:
    """Build the fully-wired container."""
    settings = settings or get_settings()

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
    resume_parser = ResumeParser()
    onboarding_service = OnboardingService(
        storage=storage,
        config_store=config_store,
        resume_parser=resume_parser,
    )

    # The onboarding gate (FR-ONBOARD-2) reports True once ANY campaign has a
    # completed intake. Channels are modeled until Phase 1 wires real backends.
    def _onboarding_gate() -> bool:
        for c in storage.campaigns.list():
            if onboarding_service.is_complete(str(c.id)):
                return True
        return False

    # Setup service so the persisted ladder can configure the LLM adapter; its
    # automated-work gate now consults the real onboarding + channels gates. The
    # channels gate reads the wizard-persisted channel config OR env defaults.
    setup_service = SetupService(
        llm_configured=settings.llm_configured,
        config_store=config_store,
        credentials=credentials,
        onboarding_gate=_onboarding_gate,
    )

    def _channels_gate() -> bool:
        return setup_service.channels_configured() or bool(
            settings.discord_webhook_url or settings.apprise_urls
        )

    setup_service.set_channels_gate(_channels_gate)
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

    llm = OpenAICompatibleLLM(ladder=setup_service.build_ladder())
    # Master aggregator (FR-DISC-2). Offline fake clients by default (hermetic boot
    # + tests); live boards opt-in via DISCOVERY_LIVE (FR-DISC-4 network boundary).
    discovery_proxies = tuple(
        p.strip() for p in settings.discovery_proxies.split(",") if p.strip()
    )
    discovery = build_default_discovery(
        live=settings.discovery_live,
        searxng_url=settings.searxng_url,
        proxies=discovery_proxies,
    )
    embedding = LocalEmbedding()
    browser = PatchrightBrowser()
    detection = DetectionMonitor()
    sandbox = LocalSandbox()
    latex_tailor = LatexTailor()
    docx_tailor = DocxTailor()
    font_installer = FontInstaller(install_root=settings.fonts_dir)
    # Channel config: wizard-persisted (FR-OOBE-2) overrides env defaults; real
    # network send is opt-in (NOTIFICATIONS_LIVE) so the default lane is hermetic.
    chan = setup_service.get_channels()
    notification = AppriseNotifier(
        discord_webhook_url=chan.get("discord_webhook_url") or settings.discord_webhook_url,
        apprise_urls=chan.get("apprise_urls") or settings.apprise_urls,
        send_real=settings.notifications_live,
    )
    orchestrator = _build_orchestrator(settings)
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
    font_service = FontService(font_installer)
    conversion_service = ConversionService(latex_tailor=latex_tailor, config_store=config_store)
    learning_service = LearningService(storage, embedding)
    # Phase 4 real-conversion depth layered over the cheap Phase 1 base (FR-LEARN-2/3/4).
    advanced_learning_service = AdvancedLearningService(base=learning_service, storage=storage)
    discovery_service = DiscoveryService(
        storage, discovery, embedding, learning_service, tool_registry=tool_registry
    )
    scoring_service = ScoringService(
        storage, llm, embedding, learning=learning_service, tool_registry=tool_registry
    )
    criteria_service = CriteriaService(storage, llm)
    agent_run_service = AgentRunService(storage)
    notification_service = NotificationService(notification)
    pending_actions_service = PendingActionsService(storage)
    digest_service = DigestService(
        storage,
        notification,
        scoring_service,
        learning=learning_service,
        criteria=criteria_service,
        notification_service=notification_service,
        pending_actions=pending_actions_service,
    )
    attribute_cloud_service = AttributeCloudService(
        storage, pending_actions=pending_actions_service
    )
    feedback_service = FeedbackService(storage, learning_service, criteria=criteria_service)
    # Chatbot (FR-CHAT-1): LLM-backed assistant over the attribute/criteria services,
    # routing integral changes through the shared confirmation gate (FR-FB-3).
    chat_service = ChatService(
        attribute_service=attribute_cloud_service,
        criteria_service=criteria_service,
        llm=llm,
    )
    # Debug / observability read-models (FR-OBS-2 / FR-LOG-3): history, screenshots,
    # workflow state, logs, variant library — backed by real storage + orchestrator.
    admin_query_service = AdminQueryService(storage, orchestrator)

    # Phase 2: durable concurrency + final-approval gate + submission logging.
    from applicant.application.services.capacity_service import CapacityService
    from applicant.application.services.final_approval_service import FinalApprovalService
    from applicant.application.services.prefill_service import PrefillService
    from applicant.application.services.submission_service import SubmissionService

    capacity_service = CapacityService(
        orchestrator,
        sandbox_concurrency=settings.sandbox_concurrency,
        llm_limit=settings.llm_rate_limit or None,
        llm_period=settings.llm_rate_period or None,
    )
    final_approval_service = FinalApprovalService(orchestrator, notification_service)
    submission_service = SubmissionService(storage, browser, learning=learning_service)
    prefill_service = PrefillService(
        storage=storage,
        browser=browser,
        detection=detection,
        sandbox=sandbox,
        credentials=credentials,
        notification=notification,
        llm=llm,
    )
    # FR-ATTR-5: resolving a missing attribute resumes the stalled pre-fill using the
    # newly-stored value (wired additively to avoid a construction cycle).
    attribute_cloud_service.set_prefill_service(prefill_service)
    from applicant.application.services.material_service import MaterialService

    material_service = MaterialService(
        storage,
        llm=llm,
        resume_tailoring=latex_tailor,
        embedding=embedding,
        docx_tailoring=docx_tailor,
        conversion_service=conversion_service,
        notifications=notification_service,
        pending_actions=pending_actions_service,
        learning=learning_service,
    )

    # Phase 5: the agent run loop + scheduler — the missing end-to-end drivers.
    from applicant.application.services.agent_loop import AgentLoop
    from applicant.application.services.scheduler import Scheduler

    agent_loop = AgentLoop(
        storage=storage,
        agent_run_service=agent_run_service,
        discovery_service=discovery_service,
        scoring_service=scoring_service,
        digest_service=digest_service,
        prefill_service=prefill_service,
        material_service=material_service,
        submission_service=submission_service,
        learning_service=learning_service,
        notification_service=notification_service,
        capacity_service=capacity_service,
        final_approval_service=final_approval_service,
        orchestrator=orchestrator,
    )
    scheduler = Scheduler(
        storage=storage,
        agent_loop=agent_loop,
        digest_service=digest_service,
        notification_service=notification_service,
        final_approval_service=final_approval_service,
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
        latex_tailor=latex_tailor,
        docx_tailor=docx_tailor,
        font_installer=font_installer,
        credentials=credentials,
        notification=notification,
        orchestrator=orchestrator,
        tool_registry=tool_registry,
        resume_parser=resume_parser,
        setup_service=setup_service,
        campaign_service=campaign_service,
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
        feedback_service=feedback_service,
        chat_service=chat_service,
        admin_query_service=admin_query_service,
        capacity_service=capacity_service,
        final_approval_service=final_approval_service,
        submission_service=submission_service,
        prefill_service=prefill_service,
        material_service=material_service,
        agent_loop=agent_loop,
        scheduler=scheduler,
    )
