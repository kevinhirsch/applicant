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
    # Phase 2 services (sandbox concurrency, final-approval gate, submission log).
    capacity_service: Any = None
    final_approval_service: Any = None
    submission_service: Any = None
    prefill_service: Any = None
    material_service: Any = None
    # Setup-page model sources (add a local/cloud endpoint; auto-list its models).
    model_endpoint_service: Any = None
    # Lane B (Stage 2.5): capped/deduped/cached deep-research tool over the
    # WorkspacePort — the agent escalates to it on a company/role knowledge gap and
    # the manual-trigger research router calls it for user-initiated runs.
    research_service: Any = None
    # Phase 5: the agent run loop + scheduler that finally drive everything end-to-end.
    agent_loop: Any = None
    scheduler: Any = None
    # CONC-REQ-1: builds a PER-REQUEST SqlAlchemyStorage(session_factory()) + the
    # storage-bound services for it, so concurrent sync requests (run in FastAPI's
    # threadpool) never interleave on one non-thread-safe Session. ``None`` when no DB
    # is configured (in-memory storage is thread-safe enough for the no-DB lane and is
    # shared). Each call returns a dict including ``_session`` to close in ``finally``.
    request_services_factory: Any = None


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
    # automated-work gate now requires ONLY the LLM + onboarding gates (channels
    # and the sandbox moved into Settings and are optional). The channels gate is
    # still wired so the status payload reports channel state for the Settings UI;
    # it reads the wizard-persisted channel config OR env defaults.
    setup_service = SetupService(
        llm_configured=settings.llm_configured,
        config_store=config_store,
        credentials=credentials,
        onboarding_gate=_onboarding_gate,
        sandbox_backend=settings.sandbox_backend,
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

    # Setup-page model sources: add a local/cloud endpoint and auto-list its models.
    from applicant.application.services.model_endpoint_service import ModelEndpointService

    model_endpoint_service = ModelEndpointService(
        config_store=config_store,
        credentials=credentials,
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
        quiet_hours=(quiet["start"], quiet["end"]) if quiet["enabled"] else None,
        quiet_tz=quiet["tz"],
        always_on=not quiet["enabled"],
        send_real=settings.notifications_live,
    )
    orchestrator = _build_orchestrator(settings)
    # Stage 2.5: outbound client for the engine -> workspace callback channel. The
    # shared secret gates it (available() is False when unset) so the default/test
    # lane never tries to reach the workspace.
    from applicant.adapters.workspace.http_workspace_client import HttpWorkspaceClient

    workspace = HttpWorkspaceClient(
        base_url=settings.workspace_url,
        token=settings.applicant_internal_token,
    )
    # Lane C (Cookbook auto-register): let the model-endpoint service surface the
    # workspace's Cookbook-served local models as auto-discovered LLM endpoints.
    # Injected post-construction (workspace is built after the service) so the
    # service stays decoupled and the dependency is optional/None in tests.
    model_endpoint_service.workspace = workspace
    model_endpoint_service.cookbook_local_host = settings.cookbook_local_host
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
        storage,
        pending_actions=pending_actions_service,
        advanced_learning=advanced_learning_service,
    )
    feedback_service = FeedbackService(
        storage,
        learning_service,
        criteria=criteria_service,
        advanced_learning=advanced_learning_service,
    )
    # Chatbot (FR-CHAT-1): LLM-backed assistant over the attribute/criteria services,
    # routing integral changes through the shared confirmation gate (FR-FB-3).
    chat_service = ChatService(
        attribute_service=attribute_cloud_service,
        criteria_service=criteria_service,
        llm=llm,
        learning=learning_service,
        storage=storage,
        # Stage 2.5 lane A: inject the workspace callback so the assistant can
        # surface auto-detected upcoming interviews (degrades silently when off).
        workspace=workspace,
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
    submission_service = SubmissionService(
        storage, browser, learning=learning_service, advanced_learning=advanced_learning_service
    )
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
    # #6: bridge onboarding intake into the engine (criteria + attribute cloud),
    # wired additively after both services exist (avoids a construction cycle).
    onboarding_service.set_criteria_service(criteria_service)
    onboarding_service.set_attribute_cloud_service(attribute_cloud_service)
    # #6: seed initial criteria at campaign creation (campaign_service is built before
    # criteria_service, so wire it additively here).
    campaign_service.set_criteria_service(criteria_service)
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
        advanced_learning=advanced_learning_service,
    )

    # Lane B (Stage 2.5): the capped deep-research tool over the WorkspacePort. One
    # instance per container so its per-campaign budget + dedupe cache are shared by
    # both the agent loop (auto-escalate) and the manual-trigger router.
    from applicant.application.services.research_service import ResearchService

    research_service = ResearchService(workspace=workspace)

    # Phase 5: the agent run loop + scheduler — the missing end-to-end drivers.
    from applicant.application.services.agent_loop import AgentLoop
    from applicant.application.services.scheduler import Scheduler

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
    )
    # CONC-2: the 24/7 scheduler thread MUST NOT share the request-scoped Session
    # (SQLAlchemy Sessions are not thread-safe). When a real DB is configured, build a
    # FRESH Session + SqlAlchemyStorage + storage-bound services for each tick and
    # close the session afterwards. The stateless adapters (llm/embedding/notifier/
    # orchestrator/sandbox/...) and session-free services are reused. With in-memory
    # storage (tests / no-DB) there is no Session to isolate, so the shared loop is used.
    def _build_tick_services(tick_storage):
        ls = LearningService(tick_storage, embedding)
        adv = AdvancedLearningService(base=ls, storage=tick_storage)
        ds = DiscoveryService(
            tick_storage, discovery, embedding, ls, tool_registry=tool_registry
        )
        ss = ScoringService(
            tick_storage, llm, embedding, learning=ls, tool_registry=tool_registry
        )
        cs = CriteriaService(tick_storage, llm)
        ars = AgentRunService(tick_storage)
        pas = PendingActionsService(tick_storage)
        dg = DigestService(
            tick_storage,
            notification,
            ss,
            learning=ls,
            criteria=cs,
            notification_service=notification_service,
            pending_actions=pas,
        )
        sub = SubmissionService(
            tick_storage, browser, learning=ls, advanced_learning=adv
        )
        pf = PrefillService(
            storage=tick_storage,
            browser=browser,
            detection=detection,
            sandbox=sandbox,
            credentials=credentials,
            notification=notification,
            llm=llm,
        )
        mat = MaterialService(
            tick_storage,
            llm=llm,
            resume_tailoring=latex_tailor,
            embedding=embedding,
            docx_tailoring=docx_tailor,
            conversion_service=conversion_service,
            notifications=notification_service,
            pending_actions=pas,
            learning=ls,
            advanced_learning=adv,
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
            setup_service=setup_service,
            research_service=research_service,
        )
        return {
            "storage": tick_storage,
            "agent_loop": loop,
            "digest_service": dg,
            "notification_service": notification_service,
            "final_approval_service": final_approval_service,
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
        rs_ls = LearningService(req_storage, embedding)
        rs_adv = AdvancedLearningService(base=rs_ls, storage=req_storage)
        rs_criteria = CriteriaService(req_storage, llm)
        rs_pas = PendingActionsService(req_storage)
        rs_scoring = ScoringService(
            req_storage, llm, embedding, learning=rs_ls, tool_registry=tool_registry
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
        )
        rs_attr = AttributeCloudService(
            req_storage, pending_actions=rs_pas, advanced_learning=rs_adv
        )
        rs_feedback = FeedbackService(
            req_storage, rs_ls, criteria=rs_criteria, advanced_learning=rs_adv
        )
        rs_chat = ChatService(
            attribute_service=rs_attr,
            criteria_service=rs_criteria,
            llm=llm,
            learning=rs_ls,
            storage=req_storage,
            workspace=workspace,  # Stage 2.5 lane A (see main ChatService build)
        )
        rs_admin = AdminQueryService(req_storage, orchestrator)
        rs_submission = SubmissionService(
            req_storage, browser, learning=rs_ls, advanced_learning=rs_adv
        )
        rs_prefill = PrefillService(
            storage=req_storage,
            browser=browser,
            detection=detection,
            sandbox=sandbox,
            credentials=credentials,
            notification=notification,
            llm=llm,
        )
        rs_attr.set_prefill_service(rs_prefill)
        rs_material = MaterialService(
            req_storage,
            llm=llm,
            resume_tailoring=latex_tailor,
            embedding=embedding,
            docx_tailoring=docx_tailor,
            conversion_service=rs_conversion,
            notifications=notification_service,
            pending_actions=rs_pas,
            learning=rs_ls,
            advanced_learning=rs_adv,
        )
        rs_campaign = CampaignService(req_storage)
        rs_campaign.set_criteria_service(rs_criteria)
        return {
            "storage": req_storage,
            "pending_actions_service": rs_pas,
            "digest_service": rs_digest,
            "attribute_cloud_service": rs_attr,
            "feedback_service": rs_feedback,
            "chat_service": rs_chat,
            "admin_query_service": rs_admin,
            "submission_service": rs_submission,
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

    scheduler = Scheduler(
        storage=storage,
        agent_loop=agent_loop,
        digest_service=digest_service,
        notification_service=notification_service,
        final_approval_service=final_approval_service,
        tick_services_factory=tick_services_factory,
        setup_service=setup_service,
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
        workspace=workspace,
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
        model_endpoint_service=model_endpoint_service,
        research_service=research_service,
        agent_loop=agent_loop,
        scheduler=scheduler,
        request_services_factory=request_services_factory,
    )
