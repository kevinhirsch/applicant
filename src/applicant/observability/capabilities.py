"""Runtime capability status — REAL vs stub/degraded detection.

The engine silently degrades to stubs when external binaries or services are
absent (no TeX → stub PDF, no LibreOffice → stub DOCX, no fc-cache → no font
refresh, no real browser → FakePageSource, no Postgres → in-memory storage).
This module detects each capability at startup using the SAME ``shutil.which()``
/ connection checks the adapters already use, so there is no duplicate logic —
we query the adapters' own detection helpers where they exist and fall back to a
direct ``shutil.which()`` call for the rest.

The result is a plain dict suitable for structured logging and for extending the
``/healthz`` response body so operators can see at a glance which capabilities
are live.
"""

from __future__ import annotations

import shutil


def _tex_status() -> str:
    """TeX render engine (xelatex or lualatex) — needed for LaTeX PDF resume render."""
    engine = (
        shutil.which("lualatex")
        or shutil.which("xelatex")
    )
    if engine:
        return f"ok ({engine})"
    return "NOT FOUND (using stub PDF)"


def _libreoffice_status() -> str:
    """LibreOffice headless — needed for DOCX-to-PDF resume render."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        return f"ok ({soffice})"
    return "NOT FOUND (using stub DOCX)"


def _fc_cache_status() -> str:
    """fontconfig fc-cache — needed to activate uploaded fonts system-wide."""
    fc = shutil.which("fc-cache")
    if fc:
        return f"ok ({fc})"
    return "NOT FOUND (font-cache refresh skipped)"


def _browser_status(browser_real: bool) -> str:
    """Browser for pre-fill / stealth automation.

    Uses the same flag the container wires: ``BROWSER_REAL=true`` enables the
    real Playwright/camoufox path; the default is the in-memory FakePageSource.
    Rather than launching a browser at startup (slow, side-effectful) we inspect
    the configured flag and the presence of known binaries.
    """
    if not browser_real:
        return "disabled (BROWSER_REAL not set — using in-memory fake)"
    # browser_real=True: check whether the configured engine binary is present.
    camoufox = shutil.which("camoufox") or shutil.which("camoufox-browser")
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chrome")
    if camoufox:
        return f"ok (camoufox: {camoufox})"
    if chrome:
        return f"ok (chrome/chromium: {chrome})"
    return "NOT FOUND (BROWSER_REAL=true but no camoufox/chrome binary on PATH)"


def _postgres_status(engine: object | None) -> str:
    """Postgres reachability — determines whether a real SQL store is used.

    Reuses the already-built SQLAlchemy engine (None when no DB is configured);
    no new connection is opened here — if the engine exists it means
    ``_build_storage`` already verified a successful ``healthcheck()``.
    """
    if engine is not None:
        return "ok (connected)"
    return "NOT REACHABLE (using in-memory storage)"


def capability_status(
    *,
    browser_real: bool = False,
    postgres_engine: object | None = None,
) -> dict[str, str]:
    """Return a dict mapping each optional capability to its REAL/stub status.

    Each value is a short human-readable string: ``"ok (...)"`` when the real
    capability is available, or a ``"NOT FOUND/disabled (...)"`` description
    when degraded. Designed to be logged at startup and embedded in ``/healthz``.

    Args:
        browser_real: The ``Settings.browser_real`` flag (True when BROWSER_REAL=true).
        postgres_engine: The SQLAlchemy engine object, or None when no DB is configured.
    """
    return {
        "tex": _tex_status(),
        "libreoffice": _libreoffice_status(),
        "fc_cache": _fc_cache_status(),
        "browser": _browser_status(browser_real),
        "postgres": _postgres_status(postgres_engine),
    }
