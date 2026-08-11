import pytest

from applicant.core.rules.url_safety import ip_is_blocked, ip_chain_is_blocked, scheme_is_allowed


# ---------------------------------------------------------------------------
# autouse fixture for xdist parallel safety (no module-level state to reset)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _xdist_safe() -> None:
    """Isolate tests for parallel xdist execution (no-op; module is stateless)."""
    yield


# ---------------------------------------------------------------------------
# scheme_is_allowed
# ---------------------------------------------------------------------------

class TestSchemeIsAllowed:
    """Only http and https are allowed for untrusted browser-navigable URLs."""

    @pytest.mark.parametrize(
        "scheme",
        ["http", "HTTPS", "Http", "https", "  http  ", "  HTTPS  ", "http", "https"],
    )
    def test_allowed_schemes(self, scheme: str) -> None:
        assert scheme_is_allowed(scheme) is True

    @pytest.mark.parametrize(
        "scheme",
        [
            "file",
            "ftp",
            "data",
            "javascript",
            "gopher",
            "FILE",
            "FTP",
            "Gopher",
        ],
    )
    def test_blocked_schemes(self, scheme: str) -> None:
        assert scheme_is_allowed(scheme) is False

    @pytest.mark.parametrize("scheme", ["", None])
    def test_empty_or_none(self, scheme: str | None) -> None:
        assert scheme_is_allowed(scheme) is False


# ---------------------------------------------------------------------------
# ip_is_blocked
# ---------------------------------------------------------------------------

class TestIpIsBlockedPrivatesAndReserved:
    """Loopback, private, link-local, multicast, reserved, and unspecified
    addresses must be blocked."""

    @pytest.mark.parametrize(
        "ip",
        [
            # loopback
            "127.0.0.1",
            "127.255.255.255",
            "::1",
            # private (RFC1918)
            "10.0.0.1",
            "10.255.255.255",
            "192.168.1.1",
            "192.168.255.255",
            "172.16.0.1",
            "172.31.255.255",
            # link-local / cloud metadata
            "169.254.169.254",
            "169.254.1.1",
            "fe80::1",
            "fe80::1%eth0",
            "fe80::dead:beef",
            # IPv4-mapped IPv6 (must normalize before the block test)
            "::ffff:169.254.169.254",
            "::ffff:10.0.0.1",
            "::ffff:192.168.1.1",
            # multicast
            "224.0.0.1",
            "239.255.255.255",
            "ff02::1",
            # reserved
            "240.0.0.1",
            "250.0.0.1",
            # unspecified
            "0.0.0.0",
            "::",
        ],
    )
    def test_blocked_addresses(self, ip: str) -> None:
        assert ip_is_blocked(ip) is True


class TestIpIsBlockedPublic:
    """Globally-routable public unicast addresses must NOT be blocked."""

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "93.184.216.34",
            "2001:4860:4860::8888",
            "2606:4700:4700::1111",
        ],
    )
    def test_public_addresses_allowed(self, ip: str) -> None:
        assert ip_is_blocked(ip) is False


class TestIpIsBlockedInvalidInput:
    """Any value that is not a valid IP literal is blocked (fail-closed)."""

    @pytest.mark.parametrize(
        "ip",
        [
            "",
            None,
            "   ",
            "not-an-ip",
            "localhost",
            "example.com",
            "256.0.0.1",
            "10.10.10.256",
            "300.300.300.300",
            "1234::5678::9abc",  # ambiguous IPv6
        ],
    )
    def test_invalid_or_empty_returns_blocked(self, ip: str | None) -> None:
        assert ip_is_blocked(ip) is True


# ---------------------------------------------------------------------------
# ip_chain_is_blocked
# ---------------------------------------------------------------------------

class TestIpChainIsBlocked:
    """Chain-based test: a single blocked address poisons the whole chain."""

    def test_empty_chain_blocked(self) -> None:
        assert ip_chain_is_blocked([]) is True
        assert ip_chain_is_blocked(None) is True

    def test_all_public_not_blocked(self) -> None:
        assert (
            ip_chain_is_blocked(["8.8.8.8", "1.1.1.1", "93.184.216.34"])
            is False
        )

    @pytest.mark.parametrize(
        "chain",
        [
            ["127.0.0.1"],
            ["8.8.8.8", "10.0.0.1"],
            ["1.1.1.1", "192.168.1.1", "8.8.8.8"],
            ["93.184.216.34", "::1"],
            ["169.254.169.254"],
            ["2001:4860:4860::8888", "fe80::1"],
        ],
    )
    def test_any_blocked_blocks_chain(self, chain: list[str]) -> None:
        assert ip_chain_is_blocked(chain) is True

