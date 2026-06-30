"""Runtime LLM reload — a model connected AT RUNTIME takes effect with no restart.

Regression for the CRITICAL bug where connecting an LLM through the OOBE opened the
engine gate (``setup/status.llm_configured`` true) but the live chat/agent kept
serving the canned deterministic reply until the engine PROCESS restarted, because
``OpenAICompatibleLLM`` froze the (initially-empty) tier ladder at construction and
``setup_service.configure_llm`` only persisted to the config store — it never
re-armed the live adapter.

The fix wires the adapter with a ``ladder_provider`` (re-reads ``build_ladder()`` +
smart routing) and registers ``llm.refresh_ladder`` as a setup-service config-change
hook, exactly as the composition root does. These tests mirror that wiring and prove
the adapter flips from the deterministic path to the live model path WITHOUT being
reconstructed. On ``origin/main`` (frozen ``self._ladder``, no provider/hook) they
fail; with the fix they pass.
"""

from __future__ import annotations

import httpx

from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.chat_service import ChatService
from applicant.application.services.criteria_service import CriteriaService
from applicant.application.services.setup_service import SetupService
from applicant.core.ids import CampaignId, new_id
from applicant.ports.driven.llm import ChatMessage
from applicant.ports.driving.setup_wizard import LLMSettings


def _live_adapter(setup: SetupService, hits: list[str]) -> OpenAICompatibleLLM:
    """Build the adapter exactly as the container does: ladder resolved through a
    provider that re-reads the setup service, plus the refresh hook registered."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/chat"):  # local Ollama chat
            hits.append("local")
            return httpx.Response(200, json={"message": {"content": "live-reply"}})
        if path.endswith("/chat/completions"):  # OpenAI-compatible chat
            hits.append("cloud")
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "live-reply"}}]}
            )
        return httpx.Response(404)

    llm = OpenAICompatibleLLM(
        ladder_provider=setup.build_ladder,
        transport=httpx.MockTransport(handler),
    )
    setup.register_llm_config_change_hook(llm.refresh_ladder)
    return llm


def test_adapter_picks_up_runtime_configure_without_reconstruct():
    """is_configured()/supports the live path flips True after a runtime connect."""
    setup = SetupService(config_store=InMemoryAppConfigStore())
    hits: list[str] = []
    llm = _live_adapter(setup, hits)

    # No model yet: gate closed, adapter NOT configured (degrades to deterministic).
    assert setup.is_setup_gate_open() is False
    assert llm.is_configured() is False

    # Connect a model AT RUNTIME (the OOBE path) — do NOT rebuild the adapter.
    setup.configure_llm(
        LLMSettings(provider="ollama", base_url="http://localhost:11434/v1", api_key="", model="llama3.1")
    )

    # The SAME adapter instance now reports configured and actually calls the model.
    assert llm.is_configured() is True
    result = llm.complete([ChatMessage(role="user", content="hi")])
    assert result.text == "live-reply"
    assert hits == ["local"]  # the live model path was taken, not a frozen-empty ladder


def test_runtime_configure_swaps_the_active_tier():
    """A second runtime reconfigure repoints the live adapter at the new endpoint."""
    setup = SetupService(config_store=InMemoryAppConfigStore())
    hits: list[str] = []
    llm = _live_adapter(setup, hits)

    setup.configure_llm(
        LLMSettings(provider="ollama", base_url="http://localhost:11434/v1", api_key="", model="llama3.1")
    )
    assert llm.complete([ChatMessage(role="user", content="a")]).text == "live-reply"
    assert hits[-1] == "local"

    # Switch to a cloud OpenAI-compatible endpoint at runtime; same adapter instance.
    setup.configure_llm(
        LLMSettings(provider="openai", base_url="https://api.openai.com/v1", api_key="sk-x", model="gpt-4o")
    )
    assert llm.complete([ChatMessage(role="user", content="b")]).text == "live-reply"
    assert hits[-1] == "cloud"  # the active tier swapped to the cloud endpoint


def test_chat_service_calls_model_after_runtime_configure():
    """End-to-end through ChatService: the canned reply gives way to the live model.

    Proves reachability of the fix at the call site that the bug report flagged: the
    ChatService singleton holds the SAME adapter the container built; once a model is
    connected at runtime the chat reply comes from the model, not the deterministic
    fallback — with no container/adapter rebuild.
    """
    setup = SetupService(config_store=InMemoryAppConfigStore())
    hits: list[str] = []
    llm = _live_adapter(setup, hits)
    storage = InMemoryStorage()
    chat = ChatService(
        attribute_service=AttributeCloudService(storage),
        criteria_service=CriteriaService(storage),
        llm=llm,
    )
    cid = CampaignId(new_id())

    # Before connecting a model, the LLM path is not configured (deterministic only).
    assert llm.is_configured() is False

    setup.configure_llm(
        LLMSettings(provider="ollama", base_url="http://localhost:11434/v1", api_key="", model="llama3.1")
    )

    reply = chat.converse(cid, "hello there").message
    assert "live-reply" in reply
    assert hits and hits[-1] == "local"


def test_no_model_configured_still_degrades_deterministically():
    """With nothing connected, the adapter stays unconfigured (no behavior change)."""
    setup = SetupService(config_store=InMemoryAppConfigStore())
    hits: list[str] = []
    llm = _live_adapter(setup, hits)

    assert llm.is_configured() is False
    storage = InMemoryStorage()
    chat = ChatService(
        attribute_service=AttributeCloudService(storage),
        criteria_service=CriteriaService(storage),
        llm=llm,
    )
    reply = chat.converse(CampaignId(new_id()), "hello there").message
    assert reply  # a non-empty deterministic reply
    assert hits == []  # the model was never called
