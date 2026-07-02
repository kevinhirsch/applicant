"""style.css defines the redline diff classes, theme-aware.

Before the fix, `static/js/documentLibrary.js` inserted the engine's redline
`rendered_html` (`<ins class="redline-add">`/`<del class="redline-sub">`/
`.redline-eq`) as-is, but the workspace stylesheet defined zero rules for
those classes, so the diff silently fell back to a bare unstyled underline/
strikethrough. This pins: the selectors exist, they resolve to *something*
other than default browser styling, they lean on the shared theme tokens
(``var(--...)``) rather than hardcoded light-mode-only hex literals (so dark
mode doesn't regress to unreadable colors), and the stylesheet itself isn't
corrupted (balanced braces).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STYLE = _REPO_ROOT / "workspace" / "static" / "style.css"


def _read_css() -> str:
    return _STYLE.read_text(encoding="utf-8")


def _rule_block(css: str, selector: str) -> str:
    """Return the ``{ ... }`` body of the first rule whose selector list
    contains ``selector`` (matched as a whole comma-separated selector, not
    merely a substring inside an unrelated word or a comment)."""
    # Match `selector` (optionally preceded by a tag name like `ins.`) as one
    # of the comma-separated selectors immediately before the opening brace.
    pattern = re.compile(
        r"(?:^|[,{}])\s*(?:[a-zA-Z]*" + re.escape(selector) + r")\s*(?:,[^{]*)?\{([^}]*)\}",
        re.MULTILINE,
    )
    match = pattern.search(css)
    assert match, f"no CSS rule block found for selector {selector!r}"
    return match.group(1)


def test_redline_add_and_sub_selectors_exist():
    css = _read_css()
    assert ".redline-add" in css
    assert ".redline-sub" in css
    # Confirmed as real selectors (not just a comment mention) by successfully
    # extracting a rule body for each below.
    add_body = _rule_block(css, ".redline-add")
    sub_body = _rule_block(css, ".redline-sub")
    assert add_body.strip()
    assert sub_body.strip()


def test_redline_add_and_sub_cover_ins_del_tags():
    css = _read_css()
    assert "ins.redline-add" in css
    assert "del.redline-sub" in css


def test_redline_eq_selector_exists():
    css = _read_css()
    eq_body = _rule_block(css, ".redline-eq")
    assert eq_body.strip()


def test_redline_add_and_sub_use_theme_tokens_not_hardcoded_hex():
    css = _read_css()
    add_body = _rule_block(css, ".redline-add")
    sub_body = _rule_block(css, ".redline-sub")

    # Theme-aware: the color-carrying declarations reference a CSS custom
    # property, not only a raw hex literal — this is what makes the diff
    # legible in both light and dark mode instead of regressing to a fixed
    # light-mode-only color.
    assert "var(--" in add_body, f".redline-add does not reference a theme token: {add_body!r}"
    assert "var(--" in sub_body, f".redline-sub does not reference a theme token: {sub_body!r}"

    # And add/sub must be visually distinct from each other (not both wired
    # to the same token), otherwise the diff still can't be told apart.
    add_tokens = set(re.findall(r"var\((--[\w-]+)", add_body))
    sub_tokens = set(re.findall(r"var\((--[\w-]+)", sub_body))
    assert add_tokens, ".redline-add has no var(--token) reference"
    assert sub_tokens, ".redline-sub has no var(--token) reference"
    assert add_tokens != sub_tokens, "redline-add/sub resolve to the same theme token(s)"


def test_stylesheet_braces_balanced():
    css = _read_css()
    assert css.count("{") == css.count("}")
