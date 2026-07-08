"""Server-side strong-password policy (P2-9 app-door hardening).

One shared assessment for every place a password is set — first-run admin
setup, self-serve signup, admin create-user, and change-password — so the
app door has a single, testable definition of "strong enough".

Deliberately NIST-800-63B-flavored: a LENGTH floor plus denylists, and **no
character-composition rules** — "correct horse battery staple" style
passphrases are the easiest strong passwords to remember and must pass.
What gets rejected instead:

* fewer than :data:`MIN_PASSWORD_LENGTH` characters;
* the username hiding inside the password;
* the classic worst-passwords list (lowercased, space-insensitive);
* trivial patterns that meet the length bar without adding entropy — a
  repeated 1-3 character unit ("aaaaaaaaaaaa", "abcabcabcabc") or a straight
  keyboard/number run ("123456789012", "abcdefghijkl").

Pure stdlib on purpose: importable (and unit-testable) without the app's
heavier dependency stack. The routes stay the single enforcement point; the
front-end mirrors the length hint for fast feedback but the server is the
authority.
"""

from __future__ import annotations

#: The length floor for every password the app accepts (first-run admin,
#: signup, admin-created users, password changes).
MIN_PASSWORD_LENGTH = 12

#: The classic worst passwords that clear a 12-character bar (lowercase,
#: spaces stripped before comparison). Small and curated on purpose — the
#: length floor already removes almost the entire common-password corpus.
_COMMON_PASSWORDS = frozenset(
    {
        "password1234",
        "password12345",
        "password123456",
        "passw0rd1234",
        "mypassword123",
        "qwertyuiop12",
        "qwertyuiop123",
        "letmein12345",
        "welcome12345",
        "administrator",
        "adminpassword",
        "changemeplease",
        "iloveyou1234",
        "sunshine1234",
        "princess1234",
        "football1234",
        "baseball1234",
        "dragon123456",
        "monkey123456",
        "superman1234",
        "computer1234",
        "internet1234",
    }
)

_DIGIT_RUN = "1234567890" * 4
_ALPHA_RUN = "abcdefghijklmnopqrstuvwxyz" * 2
_QWERTY_RUN = "qwertyuiopasdfghjklzxcvbnm" * 2


def _is_repeated_unit(text: str) -> bool:
    """True when ``text`` is one 1-3 character unit repeated end to end."""
    for size in (1, 2, 3):
        if len(text) < size * 2:
            continue
        unit = text[:size]
        repeats = len(text) // size + 1
        if (unit * repeats)[: len(text)] == text:
            return True
    return False


def _is_straight_run(text: str) -> bool:
    """True for a straight number/alphabet/keyboard run (or its reverse)."""
    for run in (_DIGIT_RUN, _ALPHA_RUN, _QWERTY_RUN):
        if text in run or text in run[::-1]:
            return True
    return False


def assess_password(password: str, username: str = "") -> tuple[bool, str]:
    """Assess a candidate password; returns ``(ok, reason)``.

    ``reason`` is a plain-language, user-facing sentence when ``ok`` is False
    (and ``""`` when the password passes). The username check only engages for
    usernames of 3+ characters so a one-letter account name cannot make most
    passwords unusable.
    """
    pw = password or ""
    if len(pw) < MIN_PASSWORD_LENGTH:
        return (
            False,
            f"Use at least {MIN_PASSWORD_LENGTH} characters — a passphrase of a "
            "few random words works well.",
        )
    low = pw.lower()
    user = (username or "").strip().lower()
    if len(user) >= 3 and user in low:
        return False, "The password can't contain your username."
    if low.replace(" ", "") in _COMMON_PASSWORDS:
        return (
            False,
            "That password is on the most-common-passwords list — pick "
            "something more personal.",
        )
    if _is_repeated_unit(low) or _is_straight_run(low):
        return (
            False,
            "That looks like a simple repeated or sequential pattern — pick "
            "something less predictable.",
        )
    return True, ""
