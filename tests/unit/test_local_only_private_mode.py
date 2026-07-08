"""P2-11 — the verified local-only private mode, pinned.

THE CLAIM (`docs/private-mode.md`): with ``LLM_LOCAL_ONLY=true``, profile/job
data never goes to a third-party LLM API. Enforced at the ONE place the tier
ladder is built (``SetupService``), so the effective ladder, the
LLM-configured gate, and setup-status can never disagree: a cloud-only config
under the mode honestly reads "not configured" instead of keeping a silent
cloud fallback (H2).

Reproduce:
    DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
      uv run pytest -q tests/unit/test_local_only_private_mode.py
"""

from __future__ import annotations

import pytest

from applicant.application.services.setup_service import SetupService
from applicant.core.rules.private_endpoints import is_private_host_url
from applicant.ports.driving.setup_wizard import LLMSettings

# ── the host classifier: strict accept/refuse table ─────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://localhost:8000/v1",
        "https://[::1]:8443",
        "http://0.0.0.0:11434",
        "http://10.0.0.5:8000",
        "http://172.16.9.2:11434",
        "http://192.168.1.50:5000/v1",
        "http://169.254.10.10:11434",
        "http://gpu-box.local:11434",
        "http://models.lan:8000",
        "http://llm.internal:9000",
        "http://server.home.arpa:11434",
        "http://ollama:11434",  # Docker service name on the compose network
        "vllm:8000",  # scheme-less single-label host
        "http://[fd00::1]:11434",  # IPv6 unique-local (the RFC-1918 analog)
        "http://[fe80::1]:11434",  # IPv6 link-local
        "http://[::ffff:127.0.0.1]:11434",  # IPv4-mapped loopback, unwrapped
        "http://[::ffff:192.168.1.50]:11434",  # IPv4-mapped RFC-1918, unwrapped
    ],
)
def test_private_hosts_are_accepted(url):
    assert is_private_host_url(url), url


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "https://openrouter.ai/api/v1",
        "https://api.anthropic.com",
        # The trap the loose preference heuristic would bless: a public FQDN
        # containing a friendly word must still be refused.
        "https://ollama.example.com",
        "http://172.32.0.1:8000",  # just OUTSIDE the 172.16/12 private block
        "http://8.8.8.8:11434",
        # IPv4-mapped PUBLIC IPv6 — the classic bypass of naive private-IP
        # checks; the classifier unwraps to 8.8.8.8 and refuses on every
        # Python version, whatever stdlib is_private says about the block.
        "http://[::ffff:8.8.8.8]:443",
        "http://[2606:4700:4700::1111]:443",  # global IPv6
        "",
        "   ",
        "http://",
    ],
)
def test_public_or_unparseable_hosts_are_refused(url):
    assert not is_private_host_url(url), url


# ── the enforcement chokepoint: SetupService ─────────────────────────────────


def _local(svc_kwargs=None, **kwargs) -> SetupService:
    return SetupService(local_only=True, **(svc_kwargs or {}), **kwargs)


def _cloud_llm() -> LLMSettings:
    return LLMSettings(
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="some/cloud-model",
        api_key="k",
    )


def _local_llm() -> LLMSettings:
    return LLMSettings(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="llama3.1:8b",
        api_key="",
    )


@pytest.mark.unit
def test_a_cloud_only_config_reads_not_configured_and_builds_no_ladder():
    """The dangerous failure mode: mode on + cloud config must NOT half-work.
    Gate closed, ladder None, status honest — all three from the same filter."""
    svc = _local()
    svc.configure_llm(_cloud_llm())

    assert svc.is_setup_gate_open() is False
    assert svc.build_ladder() is None
    assert svc.status().llm_configured is False


@pytest.mark.unit
def test_a_private_tier_opens_the_gate_and_builds_the_ladder():
    svc = _local()
    svc.configure_llm(_local_llm())

    assert svc.is_setup_gate_open() is True
    ladder = svc.build_ladder()
    assert ladder is not None
    assert [t.base_url for t in ladder.tiers] == ["http://127.0.0.1:11434"]
    assert svc.status().llm_configured is True


@pytest.mark.unit
def test_a_mixed_ladder_keeps_only_private_tiers_in_order():
    """Stored config keeps BOTH tiers (the mode never rewrites it); the
    effective ladder keeps only the private ones, order preserved."""
    from applicant.application.services.setup_service import TierSettings

    svc = _local()
    records = [
        svc._tier_to_record(
            TierSettings(
                provider="ollama",
                base_url="http://192.168.1.50:11434",
                model="llama3.1:8b",
                api_key="",
            ),
            tier_no=1,
        ),
        svc._tier_to_record(
            TierSettings(
                provider="openrouter",
                base_url="https://openrouter.ai/api/v1",
                model="some/cloud-model",
                api_key="k",
            ),
            tier_no=2,
        ),
        svc._tier_to_record(
            TierSettings(
                provider="ollama",
                base_url="http://ollama:11434",
                model="qwen2.5:7b",
                api_key="",
            ),
            tier_no=3,
        ),
    ]
    svc._save_tiers(records)

    assert len(svc.get_tiers()) == 3, "stored config is untouched by the mode"
    ladder = svc.build_ladder()
    assert ladder is not None
    assert [t.base_url for t in ladder.tiers] == [
        "http://192.168.1.50:11434",
        "http://ollama:11434",
    ]


@pytest.mark.unit
def test_the_env_preconfigured_shortcut_cannot_bypass_the_mode():
    """``llm_configured=True`` (env-preconfigured) opens the gate on its own in
    normal mode — under local-only it must not: only a private tier counts."""
    svc = SetupService(llm_configured=True, local_only=True)
    assert svc.is_setup_gate_open() is False

    normal = SetupService(llm_configured=True, local_only=False)
    assert normal.is_setup_gate_open() is True


@pytest.mark.unit
def test_mode_off_is_byte_identical_cloud_configs_still_work():
    svc = SetupService()
    svc.configure_llm(_cloud_llm())
    assert svc.is_setup_gate_open() is True
    ladder = svc.build_ladder()
    assert ladder is not None and len(ladder.tiers) == 1


# ── reachability: the mode is visible where the front door looks ────────────


@pytest.mark.unit
def test_the_setup_status_payload_surfaces_the_mode():
    from applicant.app.routers.setup import _status_dict

    on = _status_dict(_local())
    off = _status_dict(SetupService())
    assert on["llm_local_only"] is True
    assert off["llm_local_only"] is False


@pytest.mark.unit
def test_the_settings_field_reads_the_env(monkeypatch):
    from applicant.app.config import Settings

    monkeypatch.setenv("LLM_LOCAL_ONLY", "true")
    assert Settings().llm_local_only is True
    monkeypatch.delenv("LLM_LOCAL_ONLY")
    assert Settings().llm_local_only is False
