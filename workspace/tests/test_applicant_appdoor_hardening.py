"""App-door hardening (P2-9): strong passwords, rate-limited logins, TOTP reachability.

Three DoD bullets, each pinned here:

* **Strong password enforced wherever one is set** — the shared server-side
  policy (`src/password_policy.py`, pure stdlib) is tested BEHAVIORALLY, and
  its wiring into all four password-setting routes (first-run setup, signup,
  change-password, admin create-user) is pinned by source composition, the
  same way other front-door contracts are pinned in this suite. The policy is
  deliberately passphrase-friendly (length + denylists, no composition rules).
* **Login attempts rate-limited** — pinned that the login handler consults the
  limiter BEFORE any password verification.
* **TOTP 2FA surfaced** — the auth routes expose enrollment/confirm/disable and
  the Settings UI actually calls them (reachability, not just existence).

The reverse-proxy/HTTPS guide (the fourth DoD line) is pinned as a shipped,
linked doc with all three proxy snippets.
"""

from __future__ import annotations

import pathlib

from src.password_policy import MIN_PASSWORD_LENGTH, assess_password

WORKSPACE = pathlib.Path(__file__).resolve().parents[1]
REPO = WORKSPACE.parent

AUTH_ROUTES = (WORKSPACE / "routes" / "auth_routes.py").read_text(encoding="utf-8")
SETTINGS_JS = (WORKSPACE / "static" / "js" / "settings.js").read_text(encoding="utf-8")
ADMIN_JS = (WORKSPACE / "static" / "js" / "admin.js").read_text(encoding="utf-8")
LOGIN_HTML = (WORKSPACE / "static" / "login.html").read_text(encoding="utf-8")


# ── the policy itself (behavioral) ───────────────────────────────────────────


def test_short_passwords_fail_with_an_actionable_reason():
    ok, reason = assess_password("short12345")  # 10 chars
    assert not ok
    assert str(MIN_PASSWORD_LENGTH) in reason
    assert "passphrase" in reason.lower()


def test_a_lowercase_passphrase_passes_no_composition_rules():
    """NIST-style pin: length + unpredictability is the bar — an all-lowercase
    multi-word passphrase must NOT be rejected for lacking symbols/digits."""
    ok, reason = assess_password("correct horse battery staple")
    assert ok, reason


def test_the_username_cannot_hide_inside_the_password():
    ok, reason = assess_password("kevins-house-1234", username="kevin")
    assert not ok
    assert "username" in reason.lower()


def test_tiny_usernames_do_not_poison_the_check():
    """A 1-2 character username matches half of all strings; the containment
    rule only engages from 3 characters."""
    ok, _ = assess_password("absolutely fine password", username="ab")
    assert ok


def test_the_worst_passwords_list_is_matched_case_and_space_insensitively():
    for pw in ("password1234", "Password 1234", "ADMINISTRATOR"):
        ok, reason = assess_password(pw)
        assert not ok, pw
        assert "common" in reason.lower()


def test_repeated_units_and_straight_runs_fail():
    for pw in (
        "aaaaaaaaaaaa",  # 1-char unit
        "abababababab",  # 2-char unit
        "abcabcabcabc",  # 3-char unit
        "123456789012",  # digit run
        "210987654321",  # reversed digit run
        "abcdefghijkl",  # alphabet run
        "qwertyuiopas",  # keyboard run
    ):
        ok, reason = assess_password(pw)
        assert not ok, pw
        assert "pattern" in reason.lower()


def test_realistic_strong_passwords_pass():
    for pw in ("Blue-Falcon Kettle 42", "N0v4-tr@il-maps!", "window thunder pocket lamp"):
        ok, reason = assess_password(pw, username="kevin")
        assert ok, (pw, reason)


# ── wiring: every password-setting route runs the shared policy ─────────────


def _handler_segment(source: str, handler: str) -> str:
    """The source slice of one route handler (from its def to the next route)."""
    start = source.index(f"async def {handler}")
    nxt = source.find("@router.", start)
    return source[start:nxt] if nxt != -1 else source[start:]


def test_all_four_password_setting_routes_enforce_the_shared_policy():
    assert "from src.password_policy import assess_password" in AUTH_ROUTES
    for handler in ("first_run_setup", "signup", "change_password", "admin_create_user"):
        segment = _handler_segment(AUTH_ROUTES, handler)
        assert "assess_password(" in segment, (
            f"{handler} must run the shared strong-password policy"
        )


def test_the_old_eight_character_floor_is_gone_server_side():
    assert "at least 8 characters" not in AUTH_ROUTES
    assert "< 8" not in AUTH_ROUTES


def test_the_front_end_hints_mirror_the_twelve_character_floor():
    """Client hints are UX only (the server is the authority) but they must not
    promise a weaker rule than the server enforces."""
    for name, text in (("login.html", LOGIN_HTML), ("settings.js", SETTINGS_JS), ("admin.js", ADMIN_JS)):
        assert "at least 8 characters" not in text, name
        assert "at least 12 characters" in text, name
    assert "password.length < 12" in LOGIN_HTML


# ── rate limiting: consulted before any credential work ─────────────────────


def test_login_consults_the_rate_limiter_before_verifying_credentials():
    login = _handler_segment(AUTH_ROUTES, "login")
    check = login.index("_login_limiter.check")
    verify = login.index("verify_password")
    assert check < verify, "the limiter must run before password verification"
    assert "429" in login


def test_setup_and_signup_are_rate_limited_too():
    assert "_setup_limiter.check" in _handler_segment(AUTH_ROUTES, "first_run_setup")
    assert "_signup_limiter.check" in _handler_segment(AUTH_ROUTES, "signup")


# ── TOTP 2FA: exposed by the routes AND reachable from Settings ─────────────


def test_totp_routes_are_exposed():
    for route in ('"/2fa/setup"', '"/2fa/confirm"', '"/2fa/disable"'):
        assert route in AUTH_ROUTES, route
    login = _handler_segment(AUTH_ROUTES, "login")
    assert "totp_enabled" in login and "requires_totp" in login, (
        "login must demand the second factor when 2FA is enabled"
    )


def test_totp_is_reachable_from_the_settings_ui():
    for endpoint in ("/api/auth/2fa/setup", "/api/auth/2fa/confirm", "/api/auth/2fa/disable"):
        assert endpoint in SETTINGS_JS, endpoint


# ── the HTTPS guide ships and is linked ──────────────────────────────────────


def test_the_reverse_proxy_https_guide_ships_with_all_three_proxies():
    guide = (REPO / "docs" / "reverse-proxy-https.md").read_text(encoding="utf-8")
    assert "reverse_proxy 127.0.0.1:7000" in guide  # Caddy
    assert "certresolver" in guide  # Traefik
    assert "proxy_pass http://127.0.0.1:7000" in guide  # nginx
    assert "X-Forwarded-Proto" in guide
    assert "SECURE_COOKIES" in guide


def test_the_overview_links_the_guide():
    overview = (REPO / "docs" / "overview.md").read_text(encoding="utf-8")
    assert "reverse-proxy-https.md" in overview
