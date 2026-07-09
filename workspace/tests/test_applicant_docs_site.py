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


# The full set of top-level modules the generator is allowed to import. Kept
# to the stdlib so the generator runs anywhere python3 runs, with no network
# and no `pip install`. An AST walk (below) is stricter than a substring scan:
# it catches `from markdown import X`, aliased imports, and indented imports
# that a naive `"import markdown" in source` check would miss.
_ALLOWED_TOP_LEVEL_IMPORTS = {
    "__future__",
    "argparse",
    "html",
    "re",
    "sys",
    "pathlib",
}


def test_generator_script_exists_and_is_dependency_free_stdlib():
    import ast

    assert GENERATOR.exists(), "scripts/build_docs_site.py must exist (P3-4)"
    tree = ast.parse(GENERATOR.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:  # ignore relative imports
                imported.add(node.module.split(".")[0])
    unexpected = imported - _ALLOWED_TOP_LEVEL_IMPORTS
    assert not unexpected, (
        f"generator must be stdlib-only; unexpected top-level imports: {unexpected}. "
        "If a new stdlib module is genuinely needed, add it to "
        "_ALLOWED_TOP_LEVEL_IMPORTS; never a third-party dep."
    )


def test_generator_runs_clean_and_produces_expected_page_set():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = pathlib.Path(tmp) / "site"
        result = _run_generator(out_dir)
        assert result.returncode == 0, f"generator failed:\n{result.stderr}"
        produced = {p.name for p in out_dir.glob("*.html")}
        assert produced == EXPECTED_PAGES, f"unexpected page set: {produced}"


def test_generator_output_is_byte_deterministic():
    """Same repo state -> BYTE-identical output on two independent runs. This
    is the 'generated so it can't drift' pin: the output has no timestamp or
    any other machine-/time-dependent value, so two runs (even on different
    days) must produce identical bytes. If this ever needs a strip step to
    pass, that means non-determinism crept back in — fix the generator, not
    this test."""
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        out1 = pathlib.Path(tmp1) / "site"
        out2 = pathlib.Path(tmp2) / "site"
        r1 = _run_generator(out1)
        r2 = _run_generator(out2)
        assert r1.returncode == 0 and r2.returncode == 0

        for fname in EXPECTED_PAGES:
            a = (out1 / fname).read_bytes()
            b = (out2 / fname).read_bytes()
            assert a == b, f"{fname} is not byte-deterministic across two runs"
        # Guard against a reintroduced date/timestamp specifically.
        combined = b"".join((out1 / f).read_bytes() for f in EXPECTED_PAGES)
        assert b"Generated from the repo on" not in combined, (
            "footer reintroduced a date — output must stay byte-deterministic"
        )


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
    # The /privacy pointer must be a real clickable link, not bare text.
    assert '<a href="/privacy">' in page
    assert "lxml" in page and "XXE" in page  # docs/security-review.md finding #2
    assert "LLM_LOCAL_ONLY" in page  # docs/private-mode.md


def _load_generator_module():
    """Import scripts/build_docs_site.py as a module for direct unit tests of
    its helpers (it lives under scripts/, not on the default path)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_docs_site", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_strip_spec_jargon_removes_bare_and_parenthesized_spec_ids():
    """The white-label guard must strip BOTH a parenthesized spec id
    '(FR-RESUME-3/4)' AND a BARE one 'FR-RESUME-3' with no wrapping parens —
    a bare id is just as much a public-facing violation."""
    mod = _load_generator_module()
    paren = mod.strip_spec_jargon("Resume rendering (FR-RESUME-3/4) uses TeX.")
    assert "FR-" not in paren and "NFR-" not in paren
    assert "Resume rendering uses TeX." in paren

    bare = mod.strip_spec_jargon("Zero-CLI onboarding NFR-ZEROCLI-1 gates the flow.")
    assert "NFR-" not in bare and "FR-" not in bare
    # No doubled interior spaces left behind by the removal.
    assert "  " not in bare.strip()

    mixed = mod.strip_spec_jargon("Pre-fill (FR-PREFILL, FR-STEALTH) plus FR-VAULT-3 sealing.")
    assert "FR-" not in mixed and "NFR-" not in mixed


def test_strip_spec_jargon_preserves_list_continuation_indentation():
    """The per-line tidy must not eat leading indentation — md_block_to_html
    detects list-item continuation via `line.startswith('  ')`."""
    mod = _load_generator_module()
    text = "- item one (FR-X-1)\n  continued line\n- item two"
    out = mod.strip_spec_jargon(text)
    lines = out.split("\n")
    assert lines[1].startswith("  "), "continuation-line indentation was corrupted"


def test_faq_extraction_fails_closed_when_section_missing(tmp_path, monkeypatch):
    """If landing.html has no #faq section, the generator must raise rather
    than silently scrape unrelated <summary>/<p> pairs from the whole page."""
    import pytest

    mod = _load_generator_module()

    def fake_read(relpath):
        if relpath.endswith("landing.html"):
            return "<html><body><p>no faq here</p></body></html>"
        return (REPO_ROOT / relpath).read_text(encoding="utf-8")

    monkeypatch.setattr(mod, "read", fake_read)
    with pytest.raises(RuntimeError, match="faq"):
        mod.get_faq_items()


def test_quickstart_commands_are_extracted_from_the_real_scripts():
    """The install/proxmox one-liners and mode list on the Quickstart page are
    pulled from the scripts themselves, so they can't drift. Verify the
    rendered commands actually appear in the source scripts."""
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = pathlib.Path(tmp) / "site"
        result = _run_generator(out_dir)
        assert result.returncode == 0, result.stderr
        quickstart_html = (out_dir / "quickstart.html").read_text(encoding="utf-8")

    install_sh = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    proxmox_sh = (REPO_ROOT / "scripts" / "proxmox-deploy.sh").read_text(encoding="utf-8")
    # The advertised one-liners rendered on the page must exist verbatim in the scripts.
    assert 'scripts/install.sh)" -- --apply' in install_sh
    assert 'scripts/install.sh)&quot; -- --apply' in quickstart_html or \
        'scripts/install.sh)" -- --apply' in quickstart_html
    assert 'scripts/proxmox-deploy.sh)"' in proxmox_sh
    # A real mode description lifted from install.sh's Usage block.
    assert "health-check until green" in install_sh
    assert "health-check until green" in quickstart_html
