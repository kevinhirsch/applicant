import pytest

from applicant.core.rules.private_endpoints import is_private_host_url


@pytest.fixture(autouse=True)
def _no_cache():
    """Parallel-safe isolation fixture (xdist)."""
    yield


class TestIsPrivateHostUrl:
    """Tests for is_private_host_url single-label/public cases."""

    @pytest.mark.unit
    def test_empty_string(self):
        assert is_private_host_url("") is False

    @pytest.mark.unit
    def test_none_string(self):
        assert is_private_host_url(None) is False

    @pytest.mark.unit
    def test_whitespace_only(self):
        assert is_private_host_url("   ") is False

    @pytest.mark.unit
    def test_single_label_hostname(self):
        """Single-label hostnames (no dot) are private — Docker/LAN."""
        assert is_private_host_url("http://ollama:11434") is True
        assert is_private_host_url("ollama") is True
        assert is_private_host_url("myhost") is True

    @pytest.mark.unit
    def test_public_fqdn(self):
        """Public FQDNs (dotted) are not private."""
        assert is_private_host_url("https://example.com") is False
        assert is_private_host_url("https://api.openai.com/v1") is False
        assert is_private_host_url("example.com") is False

    @pytest.mark.unit
    def test_public_ip(self):
        """Public IPs are not private."""
        assert is_private_host_url("http://8.8.8.8") is False
        assert is_private_host_url("http://1.1.1.1") is False


class TestLocalhost:
    """Tests for localhost exact match."""

    @pytest.mark.unit
    def test_localhost_exact(self):
        assert is_private_host_url("http://localhost:8000") is True
        assert is_private_host_url("http://localhost") is True
        assert is_private_host_url("localhost") is True


class TestPrivateNameSuffixes:
    """Tests for private-use name suffixes."""

    @pytest.mark.unit
    def test_local_suffix(self):
        assert is_private_host_url("http://mybox.local") is True

    @pytest.mark.unit
    def test_lan_suffix(self):
        assert is_private_host_url("http://server.lan") is True

    @pytest.mark.unit
    def test_internal_suffix(self):
        assert is_private_host_url("http://service.internal") is True

    @pytest.mark.unit
    def test_home_arpa_suffix(self):
        assert is_private_host_url("http://router.home.arpa") is True

    @pytest.mark.unit
    def test_localhost_suffix(self):
        assert is_private_host_url("http://something.localhost") is True

    @pytest.mark.unit
    def test_trailing_dot_suffix(self):
        """Trailing dot stripped by rstrip('.'), suffix still matches."""
        assert is_private_host_url("http://mybox.local.") is True

    @pytest.mark.unit
    def test_public_dot_com_not_private(self):
        assert is_private_host_url("example.com") is False
        assert is_private_host_url("localhost.com") is False


class TestLoopbackIps:
    """Tests for loopback IP addresses."""

    @pytest.mark.unit
    def test_ipv4_loopback(self):
        assert is_private_host_url("http://127.0.0.1:8080") is True
        assert is_private_host_url("http://127.255.255.255") is True
        assert is_private_host_url("127.0.0.1") is True

    @pytest.mark.unit
    def test_ipv6_loopback(self):
        assert is_private_host_url("http://[::1]:8080") is True


class TestPrivateIps:
    """Tests for RFC-1918 private IP addresses."""

    @pytest.mark.unit
    def test_10_dot_prefix(self):
        assert is_private_host_url("http://10.0.0.1") is True
        assert is_private_host_url("http://10.255.255.255") is True

    @pytest.mark.unit
    def test_192_168_prefix(self):
        assert is_private_host_url("http://192.168.1.1") is True
        assert is_private_host_url("http://192.168.255.255") is True

    @pytest.mark.unit
    def test_172_16_prefix(self):
        assert is_private_host_url("http://172.16.0.1") is True
        assert is_private_host_url("http://172.31.255.255") is True

    @pytest.mark.unit
    def test_172_dot_not_private(self):
        """172.32.x.x is outside RFC-1918 172.16/12."""
        assert is_private_host_url("http://172.32.0.1") is False


class TestLinkLocalIps:
    """Tests for link-local IP addresses (169.254.x.x)."""

    @pytest.mark.unit
    def test_ipv4_link_local(self):
        assert is_private_host_url("http://169.254.1.1") is True
        assert is_private_host_url("http://169.254.255.255") is True


class TestUnspecifiedIps:
    """Tests for unspecified IP addresses (0.0.0.0)."""

    @pytest.mark.unit
    def test_unspecified_ipv4(self):
        assert is_private_host_url("http://0.0.0.0") is True


class TestUniqueLocalIpv6:
    """Tests for unique-local IPv6 (fc00::/7) — these are is_private."""

    @pytest.mark.unit
    def test_unique_local_fd(self):
        assert is_private_host_url("http://[fd00::1]") is True

    @pytest.mark.unit
    def test_link_local_fe80(self):
        assert is_private_host_url("http://[fe80::1]") is True


class TestIpv4Mapped:
    """Tests for IPv4-mapped IPv6 addresses (::ffff:x.x.x.x)."""

    @pytest.mark.unit
    def test_mapped_public_ip(self):
        """IPv4-mapped public IP unwraps and is judged by embedded IPv4 → False."""
        assert is_private_host_url("http://[::ffff:8.8.8.8]") is False
        assert is_private_host_url("http://[::ffff:1.1.1.1]") is False

    @pytest.mark.unit
    def test_mapped_private_ip(self):
        """IPv4-mapped private IP unwraps and is judged by embedded IPv4 → True."""
        assert is_private_host_url("http://[::ffff:192.168.1.1]") is True
        assert is_private_host_url("http://[::ffff:10.0.0.1]") is True
        assert is_private_host_url("http://[::ffff:127.0.0.1]") is True


class TestMalformedInput:
    """Tests for malformed/unparseable inputs."""

    @pytest.mark.unit
    def test_invalid_url(self):
        """Unparseable URL — catches ValueError, returns False (fail-closed)."""
        assert is_private_host_url("://") is False
