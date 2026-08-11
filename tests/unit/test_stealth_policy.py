"""Unit tests for ``applicant.core.stealth_policy`` (EPIC STEALTH — ST-2/ST-5).

The pure decision layer that keeps residential-proxy bandwidth / IP reputation
spent ONLY on block-prone scrape sources and on block-detect. No network here.
"""

from __future__ import annotations

import pytest

from applicant.core.stealth_policy import (
    BLOCK_STATUS_CODES,
    PROXY_POLICY_DIRECT,
    PROXY_POLICY_RESIDENTIAL,
    PROXY_POLICY_VPS,
    StealthConfig,
    apply_sessid,
    build_stealth_config,
    is_block_error,
    is_block_prone,
    new_sessid,
    parse_source_proxy_policy,
)

RESIDENTIAL = "http://10.8.0.1:8880"


@pytest.mark.unit
class TestBlockProne:
    def test_jobspy_sources_are_block_prone(self):
        for site in ("linkedin", "indeed", "glassdoor", "google", "zip_recruiter"):
            assert is_block_prone(f"jobspy:{site}") is True

    def test_keyless_ats_and_apis_are_not_block_prone(self):
        for key in ("greenhouse:acme", "lever:widgets", "searxng", "rss:hn-hiring", "sample"):
            assert is_block_prone(key) is False

    def test_block_prone_is_case_insensitive(self):
        assert is_block_prone("JOBSPY:LinkedIn") is True


@pytest.mark.unit
class TestIsBlockError:
    @pytest.mark.parametrize("code", sorted(BLOCK_STATUS_CODES))
    def test_int_block_status_codes(self, code):
        assert is_block_error(code) is True

    def test_non_block_status_code(self):
        assert is_block_error(404) is False
        assert is_block_error(200) is False

    def test_message_markers(self):
        assert is_block_error(RuntimeError("glassdoor blocked (HTTP 403)")) is True
        assert is_block_error(RuntimeError("429 Too Many Requests")) is True
        assert is_block_error(RuntimeError("Cloudflare challenge")) is True
        assert is_block_error(RuntimeError("DataDome bot detected")) is True

    def test_non_block_message(self):
        assert is_block_error(ValueError("connection reset by peer")) is False
        assert is_block_error(RuntimeError("timeout after 15s")) is False

    def test_none_and_bool_are_not_blocks(self):
        assert is_block_error(None) is False
        # ``True`` is an int subclass (== 1); it must not be read as a status code.
        assert is_block_error(True) is False

    def test_status_code_attribute_on_exception(self):
        class _HttpErr(Exception):
            status_code = 503

        assert is_block_error(_HttpErr("upstream")) is True

    def test_response_status_attribute(self):
        class _Resp:
            status_code = 429

        class _HttpErr(Exception):
            response = _Resp()

        assert is_block_error(_HttpErr("blocked")) is True


@pytest.mark.unit
class TestParseSourceProxyPolicy:
    def test_empty_is_empty_dict(self):
        assert parse_source_proxy_policy("") == {}
        assert parse_source_proxy_policy(None) == {}

    def test_parses_pairs(self):
        out = parse_source_proxy_policy("jobspy:glassdoor=residential, searxng=vps")
        assert out == {"jobspy:glassdoor": "residential", "searxng": "vps"}

    def test_mapping_input_is_validated(self):
        out = parse_source_proxy_policy({"jobspy:indeed": "DIRECT"})
        assert out == {"jobspy:indeed": "direct"}

    def test_unknown_policy_rejected(self):
        with pytest.raises(ValueError):
            parse_source_proxy_policy("jobspy:indeed=datacenter")

    def test_malformed_entry_rejected(self):
        with pytest.raises(ValueError):
            parse_source_proxy_policy("jobspy:indeed")  # no '='


@pytest.mark.unit
class TestSessid:
    def test_deterministic_from_flow_key(self):
        assert new_sessid("campaign-42") == new_sessid("campaign-42")
        assert new_sessid("campaign-42") != new_sessid("campaign-43")

    def test_random_without_flow_key(self):
        assert new_sessid() != new_sessid()

    def test_apply_sessid_no_userinfo(self):
        assert apply_sessid("http://10.8.0.1:8880", "abc123") == (
            "http://sessid-abc123@10.8.0.1:8880"
        )

    def test_apply_sessid_with_userpass_appends_to_username(self):
        out = apply_sessid("http://user:pass@host:8880", "abc123")
        assert out == "http://user-sessid-abc123:pass@host:8880"

    def test_apply_sessid_custom_label(self):
        out = apply_sessid("http://host:8880", "z9", label_format="di-{sessid}-us")
        assert out == "http://di-z9-us@host:8880"

    def test_blank_inputs_returned_unchanged(self):
        assert apply_sessid("", "abc") == ""
        assert apply_sessid("http://host", "") == "http://host"


@pytest.mark.unit
class TestStealthConfigResolution:
    def _cfg(self, **kw) -> StealthConfig:
        base = dict(residential_proxy_url=RESIDENTIAL, residential_proxy_enabled=True)
        base.update(kw)
        return StealthConfig(**base)

    def test_block_prone_source_gets_residential(self):
        cfg = self._cfg()
        assert cfg.proxy_urls_for("jobspy:linkedin") == (RESIDENTIAL,)

    def test_keyless_ats_stays_direct(self):
        cfg = self._cfg()
        assert cfg.proxy_urls_for("greenhouse:acme") == ()
        assert cfg.proxy_urls_for("lever:widgets") == ()
        assert cfg.proxy_urls_for("searxng") == ()

    def test_sticky_sessid_is_applied_to_residential(self):
        cfg = self._cfg()
        assert cfg.proxy_urls_for("jobspy:indeed", sessid="s1") == (
            "http://sessid-s1@10.8.0.1:8880",
        )

    def test_sticky_disabled_leaves_url_bare(self):
        cfg = self._cfg(sticky_sessions=False)
        assert cfg.proxy_urls_for("jobspy:indeed", sessid="s1") == (RESIDENTIAL,)

    def test_residential_disabled_downgrades_to_vps(self):
        cfg = self._cfg(residential_proxy_enabled=False, vps_proxy_url="http://vps:3128")
        assert cfg.policy_for("jobspy:linkedin") == PROXY_POLICY_VPS
        assert cfg.proxy_urls_for("jobspy:linkedin") == ("http://vps:3128",)

    def test_residential_disabled_no_vps_is_direct(self):
        cfg = self._cfg(residential_proxy_enabled=False)
        assert cfg.proxy_urls_for("jobspy:linkedin") == ()

    def test_per_source_override_wins(self):
        cfg = self._cfg(source_policy_overrides={"greenhouse:acme": "residential"})
        assert cfg.proxy_urls_for("greenhouse:acme") == (RESIDENTIAL,)
        # and a block-prone source can be pinned direct
        cfg2 = self._cfg(source_policy_overrides={"jobspy:google": "direct"})
        assert cfg2.proxy_urls_for("jobspy:google") == ()

    def test_extra_residential_proxies_merged(self):
        cfg = self._cfg(extra_residential_proxies=("http://pool2:8880",))
        assert cfg.proxy_urls_for("jobspy:indeed") == (RESIDENTIAL, "http://pool2:8880")

    def test_escalation_pool_is_residential_regardless_of_baseline(self):
        cfg = self._cfg(block_prone_policy=PROXY_POLICY_VPS)
        # baseline for a block-prone source is vps (direct here) ...
        assert cfg.proxy_urls_for("jobspy:indeed") == ()
        # ... but block-detect escalates to residential.
        assert cfg.escalation_pool() == (RESIDENTIAL,)

    def test_escalation_pool_empty_when_residential_unavailable(self):
        cfg = self._cfg(residential_proxy_enabled=False)
        assert cfg.escalation_pool() == ()

    def test_backoff_is_exponential_and_clamped(self):
        cfg = self._cfg(backoff_base_seconds=2.0, backoff_multiplier=2.0, backoff_max_seconds=10.0)
        assert cfg.backoff_delay(0) == 2.0
        assert cfg.backoff_delay(1) == 4.0
        assert cfg.backoff_delay(2) == 8.0
        assert cfg.backoff_delay(3) == 10.0  # clamped
        assert cfg.backoff_delay(-5) == 2.0  # negative attempt floored to 0


@pytest.mark.unit
class TestBuildStealthConfig:
    def test_defaults(self):
        cfg = build_stealth_config(residential_proxy_url=RESIDENTIAL)
        assert cfg.block_prone_policy == PROXY_POLICY_RESIDENTIAL
        assert cfg.default_policy == PROXY_POLICY_DIRECT
        assert cfg.proxy_urls_for("jobspy:linkedin") == (RESIDENTIAL,)

    def test_parses_source_policy_string(self):
        cfg = build_stealth_config(
            residential_proxy_url=RESIDENTIAL,
            source_proxy_policy="searxng=residential",
        )
        assert cfg.proxy_urls_for("searxng") == (RESIDENTIAL,)

    def test_rejects_bad_block_policy(self):
        with pytest.raises(ValueError):
            build_stealth_config(block_prone_policy="datacenter")

    def test_rejects_bad_default_policy(self):
        with pytest.raises(ValueError):
            build_stealth_config(default_policy="datacenter")
