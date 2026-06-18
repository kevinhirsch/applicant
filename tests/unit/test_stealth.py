"""Stealth / fingerprint-normalization + human-interaction tests (FR-STEALTH-1..5).

Hermetic: no browser, no network, no wall-clock sleeps. Randomness is pinned via an
injected ``random.Random(seed)`` so cadence/mouse/scroll assertions are exact, and
"time" is the model's logical clock (``elapsed_ms``), never ``time.sleep``.
"""

from __future__ import annotations

import random

import pytest

from applicant.adapters.browser.stealth import (
    NORMALIZED_FINGERPRINT,
    STEALTH_CAVEAT,
    BrowserProfile,
    DatacenterEgressRefused,
    EgressPolicy,
    HumanInteraction,
    ProfileStore,
    fingerprint_is_coherent,
)


@pytest.mark.unit
class TestFingerprintCoherence:
    def test_default_fingerprint_is_coherent(self):
        # FR-STEALTH-1: a single internally-consistent honest identity.
        assert fingerprint_is_coherent(NORMALIZED_FINGERPRINT) is True
        assert NORMALIZED_FINGERPRINT["locale"] == "en-US"
        assert NORMALIZED_FINGERPRINT["timezone"] == "America/Phoenix"

    def test_windows_ua_with_apple_renderer_is_incoherent(self):
        bad = dict(NORMALIZED_FINGERPRINT)
        bad["webgl_renderer"] = "Apple M1 (Metal)"  # contradicts the Linux UA
        assert fingerprint_is_coherent(bad) is False

    def test_mac_ua_with_windows_platform_is_incoherent(self):
        bad = dict(NORMALIZED_FINGERPRINT)
        bad["user_agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        assert fingerprint_is_coherent(bad) is False

    def test_mac_ua_with_d3d_renderer_is_incoherent(self):
        bad = dict(NORMALIZED_FINGERPRINT)
        bad["user_agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        bad["platform"] = "MacIntel"
        # An ANGLE/Direct3D renderer never appears on real macOS.
        assert fingerprint_is_coherent(bad) is False

    def test_missing_locale_is_incoherent(self):
        bad = dict(NORMALIZED_FINGERPRINT)
        bad["locale"] = ""
        assert fingerprint_is_coherent(bad) is False


@pytest.mark.unit
class TestHumanInteraction:
    def test_typing_cadence_is_deterministic_under_seed(self):
        # FR-STEALTH-2: timing varies per character but is reproducible under a seed.
        a = HumanInteraction(random.Random(7)).type_cadence("hello world")
        b = HumanInteraction(random.Random(7)).type_cadence("hello world")
        assert [k.delay_ms for k in a] == [k.delay_ms for k in b]
        assert [k.char for k in a] == list("hello world")

    def test_cadence_varies_per_character(self):
        plan = HumanInteraction(random.Random(1)).type_cadence("aaaa")
        delays = {k.delay_ms for k in plan}
        assert len(delays) > 1  # not a constant robotic delay

    def test_space_adds_word_boundary_hesitation(self):
        rng = random.Random(3)
        human = HumanInteraction(rng)
        plan = human.type_cadence("a b")
        space_delay = next(k.delay_ms for k in plan if k.char == " ")
        letter_delay = next(k.delay_ms for k in plan if k.char == "a")
        assert space_delay > letter_delay

    def test_clock_is_logical_not_wallclock(self):
        human = HumanInteraction(random.Random(9))
        assert human.elapsed_ms == 0.0
        human.type_cadence("hi")
        assert human.elapsed_ms > 0.0  # advanced the logical clock, never slept

    def test_mouse_path_is_curved_not_teleport(self):
        path = HumanInteraction(random.Random(2)).mouse_path((0, 0), (100, 50), steps=10)
        assert path[0] == path[0]  # endpoints anchored
        assert (path[0].x, path[0].y) == (0.0, 0.0)
        assert (path[-1].x, path[-1].y) == (100.0, 50.0)
        assert len(path) == 11  # steps + 1
        # Interior points are jittered off the straight line.
        assert any(abs(p.y - p.x * 0.5) > 0.01 for p in path[1:-1])

    def test_scroll_plan_sums_to_total(self):
        deltas = HumanInteraction(random.Random(4)).scroll_plan(500)
        assert sum(deltas) == 500
        assert len(deltas) > 1  # chunked, not one jump


@pytest.mark.unit
class TestProfileStore:
    def test_same_tenant_returns_same_profile(self):
        # FR-STEALTH-3: persistent per-tenant profile (same identity on return).
        store = ProfileStore()
        p1 = store.for_tenant("workday:acme")
        p2 = store.for_tenant("workday:acme")
        assert p1 is p2
        assert isinstance(p1, BrowserProfile)
        assert fingerprint_is_coherent(p1.fingerprint)

    def test_visit_count_marks_returning_visitor(self):
        store = ProfileStore()
        store.for_tenant("workday:acme")
        assert store.is_returning("workday:acme") is False  # first visit
        store.for_tenant("workday:acme")
        assert store.is_returning("workday:acme") is True

    def test_distinct_tenants_get_distinct_dirs(self):
        store = ProfileStore()
        a = store.for_tenant("workday:acme")
        b = store.for_tenant("workday:other")
        assert a.user_data_dir != b.user_data_dir


@pytest.mark.unit
class TestEgressPolicy:
    def test_direct_is_residential_by_default(self):
        # FR-STEALTH-4: default is the user's direct residential connection.
        policy = EgressPolicy()
        policy.validate()
        assert policy.is_direct_residential is True

    def test_datacenter_exit_is_refused(self):
        policy = EgressPolicy(proxy_url="http://dc-proxy:8080", residential=False)
        with pytest.raises(DatacenterEgressRefused):
            policy.validate()

    def test_residential_proxy_is_allowed(self):
        policy = EgressPolicy(proxy_url="http://home-exit:8080", residential=True)
        policy.validate()  # no raise
        assert policy.is_direct_residential is False


    def test_residential_proxy_mode_without_proxy_is_refused(self):
        # FR-STEALTH-4: selecting residential-proxy mode with no proxy must REFUSE
        # to launch (don't silently egress from the datacenter).
        from applicant.adapters.browser.stealth import EGRESS_RESIDENTIAL_PROXY

        policy = EgressPolicy(mode=EGRESS_RESIDENTIAL_PROXY, proxy_url=None)
        with pytest.raises(DatacenterEgressRefused):
            policy.validate()

    def test_residential_proxy_mode_with_proxy_is_allowed(self):
        from applicant.adapters.browser.stealth import EGRESS_RESIDENTIAL_PROXY

        policy = EgressPolicy(mode=EGRESS_RESIDENTIAL_PROXY, proxy_url="http://home:8080")
        policy.validate()  # no raise
        assert policy.launch_proxy() == {"server": "http://home:8080"}

    def test_direct_mode_has_no_launch_proxy(self):
        assert EgressPolicy().launch_proxy() is None

    def test_from_settings_builds_residential_proxy_policy(self):
        from applicant.adapters.browser.stealth import EGRESS_RESIDENTIAL_PROXY

        policy = EgressPolicy.from_settings(
            mode="residential-proxy", proxy_url="http://home:8080", residential=True
        )
        assert policy.mode == EGRESS_RESIDENTIAL_PROXY
        assert policy.launch_proxy() == {"server": "http://home:8080"}
        policy.validate()  # no raise (operator attested the proxy is residential)


@pytest.mark.unit
class TestEgressThreadedIntoLaunch:
    """FR-STEALTH-4: the proxy is ACTUALLY threaded into the browser launch kwargs."""

    def test_launch_kwargs_includes_residential_proxy(self):
        from applicant.adapters.browser.page_source import PlaywrightPageSource

        kwargs = PlaywrightPageSource.launch_kwargs(
            NORMALIZED_FINGERPRINT, proxy={"server": "http://home:8080"}
        )
        # FR-STEALTH-4: proxy threaded into launch_persistent_context(proxy=...).
        assert kwargs["proxy"] == {"server": "http://home:8080"}
        # FR-STEALTH-1: the coherent fingerprint is still carried through.
        assert kwargs["user_agent"] == NORMALIZED_FINGERPRINT["user_agent"]
        assert kwargs["locale"] == "en-US"

    def test_launch_kwargs_omits_proxy_for_direct_egress(self):
        from applicant.adapters.browser.page_source import PlaywrightPageSource

        kwargs = PlaywrightPageSource.launch_kwargs(NORMALIZED_FINGERPRINT, proxy=None)
        assert "proxy" not in kwargs

    def test_launch_kwargs_keeps_webgl_on_gpuless_host(self):
        """FR-STEALTH-1: a WebGL context must exist even on a GPU-less host.

        The default deploy launches the browser inside the api container (no GPU).
        Recent Chrome/Chromium return a NULL WebGL context there unless software
        rendering is allowed, and a missing context is itself a coherence tell (a
        real Chrome-on-Linux always exposes WebGL). The launch must force the
        SwiftShader fallback so the fingerprint init script has a context to mask.
        """
        from applicant.adapters.browser.page_source import PlaywrightPageSource

        args = PlaywrightPageSource.launch_kwargs(NORMALIZED_FINGERPRINT, proxy=None)["args"]
        assert "--enable-unsafe-swiftshader" in args
        # The automation tell stays removed.
        assert "--disable-blink-features=AutomationControlled" in args
        # We still reveal NO automation flags.
        assert not any("--headless" in a or "--enable-automation" in a for a in args)

    def test_browser_passes_egress_proxy_to_source(self, monkeypatch):
        # The adapter must hand the EgressPolicy's launch_proxy() to the page source.
        from applicant.adapters.browser import patchright_browser as pb
        from applicant.adapters.browser.stealth import EGRESS_RESIDENTIAL_PROXY
        from applicant.core.ids import ApplicationId, new_id

        captured: dict = {}

        class _FakeSource:
            def __init__(
                self,
                fingerprint,
                *,
                proxy=None,
                user_data_dir="",
                channel="chrome",
                cdp_endpoint="",
                persona="linux",
            ):
                captured["proxy"] = proxy
                captured["user_data_dir"] = user_data_dir
                captured["channel"] = channel
                captured["cdp_endpoint"] = cdp_endpoint
                captured["persona"] = persona

            def open(self, url):  # noqa: D401
                captured["opened"] = url

            def current(self):
                from applicant.ports.driven.browser_automation import PageState

                return PageState(url="https://acme.wd1.myworkdayjobs.com/x", fields=())

        # Use real-browser path but swap PlaywrightPageSource for the fake.
        monkeypatch.setattr(pb, "PlaywrightPageSource", _FakeSource, raising=False)
        import applicant.adapters.browser.page_source as ps

        monkeypatch.setattr(ps, "PlaywrightPageSource", _FakeSource, raising=False)

        egress = EgressPolicy(mode=EGRESS_RESIDENTIAL_PROXY, proxy_url="http://home:8080")
        browser = pb.PatchrightBrowser(use_real_browser=True, egress=egress)
        browser.open(ApplicationId(new_id()), "https://acme.wd1.myworkdayjobs.com/x")
        assert captured["proxy"] == {"server": "http://home:8080"}


@pytest.mark.unit
def test_honest_caveat_copy_present():
    # FR-STEALTH-5: honest best-effort caveat surfaced in UX copy.
    assert "best-effort" in STEALTH_CAVEAT
    assert "live session" in STEALTH_CAVEAT.lower() or "irreducible" in STEALTH_CAVEAT.lower()
