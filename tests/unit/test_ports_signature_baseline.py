import pytest

from applicant.ports.signature_baseline import (
    PORT_SIGNATURE_BASELINE,
    PortSignatureDrift,
    _is_port_protocol,
    assert_ports_unchanged,
    collect_port_signatures,
)
from applicant.ports.driven.browser_automation import BrowserAutomationPort


class TestParallelSafety:
    """Confirm the module is naturally parallel-safe (no mutable state to clear)."""

    @pytest.fixture(autouse=True)
    def noop_autouse(self):
        """Module uses read-only reflection + sys.modules caching — no state to reset."""
        pass


class TestCollectPortSignatures:
    """Tests for collect_port_signatures — recomputes live protocol signatures."""

    def test_returns_dict(self):
        sigs = collect_port_signatures()
        assert isinstance(sigs, dict)

    def test_keys_are_strings(self):
        sigs = collect_port_signatures()
        for k in sigs:
            assert isinstance(k, str), f"key {k!r} is not a string"

    def test_values_are_strings(self):
        sigs = collect_port_signatures()
        for v in sigs.values():
            assert isinstance(v, str), f"value {v!r} is not a string"

    def test_keys_have_module_prefix(self):
        """Keys should match pattern module.ClassName.method (three parts separated by dots)."""
        sigs = collect_port_signatures()
        for k in sigs:
            parts = k.split(".")
            assert len(parts) >= 3, f"key {k!r} doesn't have module.ClassName.method structure"

    def test_known_driven_port_exists(self):
        """browser_automation is a known driven port."""
        sigs = collect_port_signatures()
        bw_keys = [k for k in sigs if k.startswith("browser_automation.BrowserAutomationPort.")]
        assert len(bw_keys) > 0, "no browser_automation keys found"

    def test_known_driving_port_exists(self):
        """attribute_editing is a known driving port."""
        sigs = collect_port_signatures()
        ae_keys = [k for k in sigs if k.startswith("attribute_editing.AttributeEditingPort.")]
        assert len(ae_keys) > 0, "no attribute_editing keys found"

    def test_browser_automation_method_signature(self):
        """Verify BrowserAutomationPort.open has expected parameters."""
        sigs = collect_port_signatures()
        key = "browser_automation.BrowserAutomationPort.open"
        assert key in sigs, f"{key} not found in signatures"
        sig = sigs[key]
        assert "self" in sig
        assert "application_id" in sig
        assert "url" in sig


class TestPortSignatureBaseline:
    """Tests for the module-level PORT_SIGNATURE_BASELINE constant."""

    def test_is_non_empty_dict(self):
        assert isinstance(PORT_SIGNATURE_BASELINE, dict)
        assert len(PORT_SIGNATURE_BASELINE) > 0

    def test_large_baseline(self):
        """Expect many entries with ~240 port methods."""
        assert len(PORT_SIGNATURE_BASELINE) > 50

    def test_matches_collect_port_signatures(self):
        """Baseline should equal the live collected signatures at import time."""
        assert PORT_SIGNATURE_BASELINE == collect_port_signatures()


class TestAssertPortsUnchanged:
    """Tests for assert_ports_unchanged — drift detector."""

    def test_passes_with_baseline(self):
        """No error when the live signatures match the original baseline."""
        assert_ports_unchanged(PORT_SIGNATURE_BASELINE)

    def test_passes_with_none_default(self):
        """No error when called with None (defaults to PORT_SIGNATURE_BASELINE)."""
        assert_ports_unchanged()

    def test_raises_on_added_key(self):
        modified = dict(PORT_SIGNATURE_BASELINE)
        modified["driven.fake.FakePort.added_method"] = "(self)"
        with pytest.raises(PortSignatureDrift):
            assert_ports_unchanged(modified)

    def test_raises_on_removed_key(self):
        modified = dict(PORT_SIGNATURE_BASELINE)
        first_key = next(iter(modified))
        del modified[first_key]
        with pytest.raises(PortSignatureDrift):
            assert_ports_unchanged(modified)

    def test_raises_on_changed_signature(self):
        modified = dict(PORT_SIGNATURE_BASELINE)
        target_key = next(
            k for k in modified
            if modified[k] not in ("<unintrospectable>",)
        )
        modified[target_key] = "(self, tampered_param)"
        with pytest.raises(PortSignatureDrift):
            assert_ports_unchanged(modified)

    def test_raises_with_descriptive_message(self):
        modified = dict(PORT_SIGNATURE_BASELINE)
        modified["driven.fake.FakePort.added_method"] = "(self)"
        with pytest.raises(PortSignatureDrift, match="Frozen port Protocol signatures drifted"):
            assert_ports_unchanged(modified)


class TestPortSignatureDrift:
    """Tests for the PortSignatureDrift exception class."""

    def test_is_assertion_error_subclass(self):
        assert issubclass(PortSignatureDrift, AssertionError)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(PortSignatureDrift):
            raise PortSignatureDrift("drift detected")

    def test_can_be_raised_as_assertion_error(self):
        with pytest.raises(AssertionError):
            raise PortSignatureDrift("drift detected")


class TestIsPortProtocol:
    """Tests for _is_port_protocol — identifies port Protocol classes."""

    def test_browser_automation_port_is_protocol(self):
        assert _is_port_protocol(BrowserAutomationPort) is True

    def test_bare_protocol_is_not_port(self):
        from typing import Protocol
        assert _is_port_protocol(Protocol) is False

    def test_regular_class_is_not_protocol(self):
        class NotAPort:
            pass
        assert _is_port_protocol(NotAPort) is False

    def test_non_class_is_not_protocol(self):
        assert _is_port_protocol(42) is False
        assert _is_port_protocol("hello") is False
        assert _is_port_protocol(None) is False
        assert _is_port_protocol([1, 2, 3]) is False


class TestMethodSignatures:
    """Tests for specific method signature correctness."""

    def test_open_has_expected_params(self):
        sigs = collect_port_signatures()
        key = "browser_automation.BrowserAutomationPort.open"
        sig = sigs[key]
        params = [p.strip() for p in sig.strip("()").split(",")]
        assert params == ["self", "application_id", "url"]

    def test_screenshot_has_expected_params(self):
        sigs = collect_port_signatures()
        key = "browser_automation.BrowserAutomationPort.screenshot"
        sig = sigs[key]
        params = [p.strip() for p in sig.strip("()").split(",")]
        assert params == ["self", "application_id"]

    def test_upsert_attribute_defaults_exist(self):
        sigs = collect_port_signatures()
        key = "attribute_editing.AttributeEditingPort.upsert_attribute"
        assert key in sigs
        sig = sigs[key]
        assert "kw:user_confirmed=False" in sig, f"expected keyword default in {sig}"

    def test_list_campaigns_key_exists(self):
        sigs = collect_port_signatures()
        key = "campaign_management.CampaignManagementPort.list_campaigns"
        assert key in sigs
