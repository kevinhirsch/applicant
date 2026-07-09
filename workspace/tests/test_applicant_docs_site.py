"""Regression coverage for P3-4 (Docs site): scripts/build_docs_site.py.

The DoD is "Quickstart, FAQ, troubleshooting, security/privacy pages;
generated from the repo so it can't drift." This pins two things:

1. The generator runs clean (subprocess, stdlib-only, no network) and
   produces exactly the expected page set every time (determinism —
   byte-identical across two independent runs).
2. A section-presence/content contract: each page actually contains content
   pulled live from its named source, not hardcoded prose. These assertions
   are deliberately grounded in specific repo facts (a known-issue ID from
   docs/known-issues.md, a FAQ question from the shipped landing page, a
   compose service name, a security-review finding) so a future edit to any
   of those source docs that breaks the generator's extraction shows up
   here, not silently in the shipped site.

No FastAPI/DB import needed — this only shells out to a stdlib-only script,
so it runs fine in the root uv env alongside the other `test_applicant_*`
front-door tests.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "build_docs_site.py"

EXPECTED_PAGES = {
    "index.html",
    "quickstart.html",
    "faq.html",
    "troubleshooting.html",
    "security-privacy.html",
}


def _run_generator(out_dir: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_generator_script_exists_and_is_dependency_free_stdlib():
    assert GENERATOR.exists(), "scripts/build_docs_site.py must exist (P3-4)"
    source = GENERATOR.read_text(encoding="utf-8")
    # No third-party imports — this must run anywhere python3 runs, no network.
    for banned in ("import markdown", "import mkdocs", "import jinja2", "import requests"):
        assert banned not in source, f"generator should be stdlib-only, found {banned!r}"


def test_generator_runs_clean_and_produces_expected_page_set():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = pathlib.Path(tmp) / "site"
        result = _run_generator(out_dir)
        assert result.returncode == 0, f"generator failed:\n{result.stderr}"
        produced = {p.name for p in out_dir.glob("*.html")}
        assert produced == EXPECTED_PAGES, f"unexpected page set: {produced}"


def test_generator_is_deterministic():
    """Same repo state -> byte-identical output on two independent runs
    (this is the 'generated so it can't drift' pin: nothing here is
    machine- or time-dependent beyond the one visible 'generated on DATE'
    footer line, which we strip before comparing)."""
    import re

    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        out1 = pathlib.Path(tmp1) / "site"
        out2 = pathlib.Path(tmp2) / "site"
        r1 = _run_generator(out1)
        r2 = _run_generator(out2)
        assert r1.returncode == 0 and r2.returncode == 0

        def strip_date(text: str) -> str:
            return re.sub(r"Generated from the repo on \d{4}-\d{2}-\d{2}", "", text)

        for fname in EXPECTED_PAGES:
            a = strip_date((out1 / fname).read_text(encoding="utf-8"))
            b = strip_date((out2 / fname).read_text(encoding="utf-8"))
            assert a == b, f"{fname} is not deterministic across two runs"


def test_faq_page_reuses_the_shipped_landing_page_faq_verbatim():
    """Section-presence contract: the FAQ page must contain the real
    landing-page questions (workspace/static/landing.html #faq), not a
    hand-written duplicate that can drift from what users are shown."""
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = pathlib.Path(tmp) / "site"
        result = _run_generator(out_dir)
        assert result.returncode == 0, result.stderr
        faq_html = (out_dir / "faq.html").read_text(encoding="utf-8")

    landing_html = (REPO_ROOT / "workspace" / "static" / "landing.html").read_text(encoding="utf-8")
    assert "Does it submit applications without asking me?" in landing_html, (
        "landing.html's #faq content changed — update this test's grounding assertion"
    )
    assert "Does it submit applications without asking me?" in faq_html
    assert "EEO / demographic and work-authorization" in faq_html
    assert "there is no Applicant-operated server" in faq_html


def test_troubleshooting_page_pulls_live_known_issues_and_has_no_spec_jargon():
    """Section-presence contract against docs/known-issues.md's OPEN table,
    plus the white-label guard: this is a public docs page, so FR-/NFR-
    spec-ID jargon (present in CLAUDE.md's own runtime-gotchas prose) must
    never leak into it (binding principle #3)."""
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = pathlib.Path(tmp) / "site"
        result = _run_generator(out_dir)
        assert result.returncode == 0, result.stderr
        troubleshooting_html = (out_dir / "troubleshooting.html").read_text(encoding="utf-8")

    known_issues = (REPO_ROOT / "docs" / "known-issues.md").read_text(encoding="utf-8")
    assert "| K1 |" in known_issues, "docs/known-issues.md's OPEN table shape changed — re-check the generator's parser"

    assert "<code>K1</code>" in troubleshooting_html
    assert "shutil.which()" in troubleshooting_html  # from CLAUDE.md's runtime-dependency note
    assert "LibreOffice" in troubleshooting_html

    import re

    spec_ids = re.findall(r"\bFR-[A-Za-z0-9/-]+|\bNFR-[A-Za-z0-9/-]+", troubleshooting_html)
    assert not spec_ids, f"spec-ID jargon leaked into the public docs site: {spec_ids}"


def test_quickstart_page_reflects_the_real_compose_stack():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = pathlib.Path(tmp) / "site"
        result = _run_generator(out_dir)
        assert result.returncode == 0, result.stderr
        quickstart_html = (out_dir / "quickstart.html").read_text(encoding="utf-8")

    compose = (REPO_ROOT / "docker" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    for expected_service in ("applicant-ui", "postgres", "searxng"):
        assert f"  {expected_service}:" in compose, (
            "docker-compose.prod.yml's service list changed — re-check the generator's parser"
        )
        assert expected_service in quickstart_html

    assert "scripts/install.sh --apply" in quickstart_html
    assert "scripts/proxmox-deploy.sh" in quickstart_html


def test_security_privacy_page_links_the_real_privacy_policy_and_findings():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = pathlib.Path(tmp) / "site"
        result = _run_generator(out_dir)
        assert result.returncode == 0, result.stderr
        page = (out_dir / "security-privacy.html").read_text(encoding="utf-8")

    assert (REPO_ROOT / "workspace" / "static" / "privacy.html").exists()
    assert "/privacy" in page
    assert "lxml" in page and "XXE" in page  # docs/security-review.md finding #2
    assert "LLM_LOCAL_ONLY" in page  # docs/private-mode.md
