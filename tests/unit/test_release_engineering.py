"""Release engineering (P3-5) — hermetic pins for the version/changelog/release-
workflow machinery, so a future edit that breaks any of it fails the default
(non-integration) test suite, not just a manual `python3 scripts/ci/...` run.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- VERSION / pyproject.toml / applicant.version.__version__ consistency ---


def test_check_release_version_script_passes_on_this_checkout():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "ci" / "check_release_version.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_version_file_is_valid_semver():
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.match(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$", version), version


def test_applicant_version_module_matches_version_file():
    from applicant.version import __version__

    version_file = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert __version__ == version_file


def test_pyproject_version_matches_version_file():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    assert match, "pyproject.toml has no [project].version"
    version_file = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert match.group(1) == version_file


# --- CHANGELOG.md (Keep a Changelog format) ----------------------------------


def test_changelog_exists_and_has_keep_a_changelog_markers():
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Keep a Changelog" in text
    assert "Semantic Versioning" in text
    assert re.search(r"^##\s*\[Unreleased\]", text, re.MULTILINE)


def test_changelog_has_an_entry_for_the_current_version():
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version_file = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.search(rf"^##\s*\[{re.escape(version_file)}\]", text, re.MULTILINE)


# --- .github/workflows/release.yml is syntactically valid + correctly gated -


@pytest.fixture(scope="module")
def release_workflow() -> dict:
    path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_release_workflow_parses_as_valid_yaml(release_workflow):
    assert isinstance(release_workflow, dict)
    assert "jobs" in release_workflow


def test_release_workflow_is_gated_on_tags_and_manual_dispatch(release_workflow):
    # YAML parses the bare `on:` key as the boolean True (YAML 1.1 quirk) —
    # read via both possible keys so this doesn't silently pass on an empty dict.
    triggers = release_workflow.get("on", release_workflow.get(True))
    assert isinstance(triggers, dict)
    assert "push" in triggers and "tags" in triggers["push"]
    tag_patterns = triggers["push"]["tags"]
    assert any("[0-9]" in p for p in tag_patterns), tag_patterns
    assert "workflow_dispatch" in triggers


def test_release_tag_globs_are_actions_globs_not_regex(release_workflow):
    # Regression guard for the Greptile P1 on PR #782: GitHub Actions `on.push.
    # tags` uses GLOB filters, not regex — a regex-shaped `v[0-9]+.[0-9]+.[0-9]+`
    # treats `+` literally and would NEVER match a real tag like `v0.1.0`, so
    # the whole workflow would silently never fire. Two things must hold:
    #   1. no regex quantifier (`+`) leaks into the glob patterns, and
    #   2. the real documented tags actually match at least one pattern while
    #      obvious non-release refs do not.
    # fnmatch is a faithful stand-in for Actions glob semantics here: `*` = any
    # run of chars, `[0-9]` = a single-digit class, `.`/`-` literal.
    triggers = release_workflow.get("on", release_workflow.get(True))
    tag_patterns = triggers["push"]["tags"]

    for pat in tag_patterns:
        assert "+" not in pat, (
            f"{pat!r} uses a regex '+' quantifier — Actions tag filters are globs, "
            "not regex, so this would never match a real tag"
        )

    def _matches_any(ref: str) -> bool:
        return any(fnmatch.fnmatch(ref, pat) for pat in tag_patterns)

    # Real release tags this repo documents MUST get through the glob.
    for tag in ("v0.1.0", "v1.4.0", "v1.5.0-beta.1", "v1.5.0-rc.2", "v10.20.30"):
        assert _matches_any(tag), f"documented release tag {tag!r} must match {tag_patterns}"

    # Non-release refs / obviously malformed tags MUST NOT match (a branch name,
    # a two-part version, a bare word).
    for ref in ("main", "release", "v1.2", "1.4.0"):
        assert not _matches_any(ref), f"{ref!r} should not match the release tag glob {tag_patterns}"


def test_release_workflow_is_never_a_per_pr_gate(release_workflow):
    triggers = release_workflow.get("on", release_workflow.get(True))
    assert "pull_request" not in triggers
    # A plain push-to-main trigger (no tag filter) would make every merge try
    # to publish/sign — must not be present alongside the tag-gated push.
    push = triggers["push"]
    assert "branches" not in push


def test_release_workflow_requests_ghcr_and_oidc_permissions(release_workflow):
    perms = release_workflow.get("permissions", {})
    assert perms.get("packages") == "write"
    assert perms.get("id-token") == "write"


def test_release_workflow_builds_both_shipped_images(release_workflow):
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "docker/Dockerfile" in text
    assert "workspace/Dockerfile" in text


def test_release_workflow_signs_with_cosign(release_workflow):
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "cosign-installer" in text
    assert "cosign sign" in text


def test_release_workflow_tags_stable_and_beta_channels(release_workflow):
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "stable" in text
    assert "beta" in text
    # :latest must move ONLY for stable releases, never beta.
    assert '"${CHANNEL}" == "stable"' in text


def test_release_workflow_verifies_version_file_matches_the_tag(release_workflow):
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "VERSION file" in text
    assert "does not match tag" in text


def test_release_workflow_honestly_documents_the_not_yet_run_live_gap(release_workflow):
    # Universal DoD / H-series honesty: the workflow's own header must say, in
    # plain terms, that it has not yet been exercised against real GHCR/cosign
    # credentials — this repo is not allowed to claim a signed image exists
    # until a maintainer with real access has actually run it.
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "has not yet been exercised" in text or "not yet run" in text.lower()
