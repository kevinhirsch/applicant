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

from applicant.adapters.credentials.pg_credential_store import PgCredentialStore
from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.discovery.jobspy_searxng import JobSpySearxngDiscovery
from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.fonts.font_installer import FontInstaller
from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.resume_tailoring.docx_tailor import DocxTailor
from applicant.adapters.resume_tailoring.latex_tailor import LatexTailor
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.app_config_store import (
    InMemoryAppConfigStore,
    SqlAlchemyAppConfigStore,
)
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.adapters.tools.tool_registry import ToolRegistry
from applicant.app.config import Settings, get_settings
from applicant.application.services.campaign_service import CampaignService
from applicant.application.services.discovery_service import DiscoveryService
from applicant.application.services.learning_service import LearningService
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

    # services
    setup_service: Any
    campaign_service: Any
    discovery_service: Any
    scoring_service: Any
    learning_service: Any


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

    credentials = PgCredentialStore(settings.credential_keyfile)

    # Setup service first so the persisted ladder can configure the LLM adapter.
    setup_service = SetupService(
        llm_configured=settings.llm_configured,
        config_store=config_store,
        credentials=credentials,
    )
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
    discovery = JobSpySearxngDiscovery()
    embedding = LocalEmbedding()
    browser = PatchrightBrowser()
    detection = DetectionMonitor()
    sandbox = LocalSandbox()
    latex_tailor = LatexTailor()
    docx_tailor = DocxTailor()
    font_installer = FontInstaller()
    notification = AppriseNotifier(
        discord_webhook_url=settings.discord_webhook_url,
        apprise_urls=settings.apprise_urls,
    )
    orchestrator = _build_orchestrator(settings)
    tool_registry = ToolRegistry()

    # Register durable workflows (recovered on startup in lifespan).
    application_pipeline.register(orchestrator)

    campaign_service = CampaignService(storage)
    discovery_service = DiscoveryService(storage, discovery, embedding)
    scoring_service = ScoringService(storage, llm, embedding)
    learning_service = LearningService(storage, embedding)

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
        setup_service=setup_service,
        campaign_service=campaign_service,
        discovery_service=discovery_service,
        scoring_service=scoring_service,
        learning_service=learning_service,
    )
