import pytest
from pathlib import Path

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
A0_WEBUI = PROJECT_ROOT / "a0-webui"
SCRIPTS = PROJECT_ROOT / "scripts"
BRANDING = PROJECT_ROOT / "branding"


class TestOverlayExists:
    """Deliverable 1: a0-webui/ dir with README explaining the overlay pattern."""

    def test_a0_webui_directory_exists(self):
        assert A0_WEBUI.is_dir(), (
            f"a0-webui/ overlay directory missing at {A0_WEBUI}"
        )

    def test_a0_webui_has_readme(self):
        readme = A0_WEBUI / "README.md"
        assert readme.is_file(), "a0-webui/README.md missing"
        content = readme.read_text()
        assert "build-time overlay" in content, (
            "README must explain the overlay pattern"
        )
        assert "/a0/webui" in content, (
            "README must reference the pristine upstream tree"
        )


class TestOverlayHasBrandedFiles:
    """The overlay must contain the branded files the build copies."""

    def test_branded_index_html(self):
        path = A0_WEBUI / "index.html"
        assert path.is_file(), "a0-webui/index.html missing"
        content = path.read_text()
        assert "<title>Applicant</title>" in content, (
            "index.html must have branded <title>"
        )
        assert "Agent Zero" not in content, (
            "index.html should not contain 'Agent Zero'"
        )

    def test_branded_login_html(self):
        path = A0_WEBUI / "login.html"
        assert path.is_file(), "a0-webui/login.html missing"
        content = path.read_text()
        assert "<title>Login - Applicant</title>" in content, (
            "login.html must have branded <title>"
        )
        assert 'alt="Applicant Logo"' in content, (
            "login.html alt text must be branded"
        )
        assert "<h2>Applicant</h2>" in content, (
            "login.html heading must be branded"
        )
        assert "Agent Zero" not in content, (
            "login.html should not contain 'Agent Zero'"
        )

    def test_branded_manifest_json(self):
        path = A0_WEBUI / "js" / "manifest.json"
        assert path.is_file(), "a0-webui/js/manifest.json missing"
        content = path.read_text()
        assert '"name": "Applicant"' in content, (
            "manifest.json name must be branded"
        )
        assert '"short_name": "Applicant"' in content, (
            "manifest.json short_name must be branded"
        )
        assert "Agent Zero" not in content, (
            "manifest.json should not contain 'Agent Zero'"
        )

    def test_branded_svgs_exist(self):
        public = A0_WEBUI / "public"
        assert public.is_dir(), "a0-webui/public/ missing"
        svgs = list(public.glob("*.svg"))
        assert len(svgs) >= 4, (
            f"Expected at least 4 SVG icons in a0-webui/public/, found {len(svgs)}"
        )
        assert (public / "favicon.svg").is_file()
        assert (public / "icon.svg").is_file()


class TestBuildScriptUsesOverlay:
    """Deliverable 1b: apply-branding.sh must reference a0-webui/ as overlay."""

    def test_apply_branding_script_exists(self):
        script = SCRIPTS / "apply-branding.sh"
        assert script.is_file(), "scripts/apply-branding.sh missing"

    def test_apply_branding_references_overlay(self):
        script = SCRIPTS / "apply-branding.sh"
        content = script.read_text()
        assert "a0-webui" in content, (
            "apply-branding.sh must reference a0-webui/"
        )
        assert "OVERLAY_DIR" in content, (
            "apply-branding.sh must define OVERLAY_DIR"
        )
        assert content.startswith("#!/usr/bin/env bash"), (
            "apply-branding.sh must be a bash script"
        )

    def test_apply_branding_is_executable(self):
        script = SCRIPTS / "apply-branding.sh"
        assert script.stat().st_mode & 0o111, (
            "apply-branding.sh must be executable"
        )


class TestCherryPickWorkflowDoc:
    """Deliverable 2: docs/vendor-sync/ui-fork-cherry-pick.md"""

    def test_doc_exists(self):
        doc = PROJECT_ROOT / "docs" / "vendor-sync" / "ui-fork-cherry-pick.md"
        assert doc.is_file(), (
            "docs/vendor-sync/ui-fork-cherry-pick.md missing"
        )

    def test_doc_has_workflow_sections(self):
        doc = PROJECT_ROOT / "docs" / "vendor-sync" / "ui-fork-cherry-pick.md"
        content = doc.read_text()
        assert "cherry-pick" in content.lower(), (
            "Workflow doc must describe the cherry-pick procedure"
        )
        assert "a0-webui" in content, (
            "Workflow doc must reference a0-webui/"
        )
        assert "apply-branding" in content, (
            "Workflow doc must reference the build script"
        )
        assert "overlay" in content.lower(), (
            "Workflow doc must describe the overlay pattern"
        )


class TestBrandingSourceConsistency:
    """The overlay is the source of truth — branding files should not be Agent Zero branded."""

    def test_no_agent_zero_references_in_overlay_html(self):
        """No 'Agent Zero' string should remain in overlay HTML files."""
        for html_file in A0_WEBUI.glob("*.html"):
            content = html_file.read_text()
            assert "Agent Zero" not in content, (
                f"Overlay file {html_file.relative_to(A0_WEBUI)} still contains 'Agent Zero'"
            )


class TestModalTitleOverlay:
    """B12 (docs/APPLICANT-BACKLOG.md): every Applicant panel modal title must be
    derived via friendlyTitleFromPath(), never the raw component path. The fix
    landed only in the DEAD reference copy (agent-zero/webui/js/modals.js) --
    but the deployed a0 image is built FROM the pinned upstream base image and
    only layers on a0-applicant/ + the a0-webui/ overlay (docker/Dockerfile.a0);
    the vendored agent-zero/webui/ subtree ships nowhere. So the fix never
    reached users until it is also placed at the overlay path apply-branding.sh
    actually copies onto /a0/webui/ at image-build time: a0-webui/js/modals.js.

    IMPORTANT (discovered while building this fix, verified live against the
    running containers): agent-zero/webui/js/modals.js (the "dead copy") is
    ITSELF STALE relative to the pinned base image in docker/Dockerfile.a0
    (sha256:7f8bc5cc...) -- the real pinned image's modals.js is 578 lines
    (session-restore via persistRestorableModalStack/focusModal, an
    isModalOpen() export other framework JS extensions depend on, a different
    backdrop/z-index scheme, ...) vs. the dead copy's 393 lines. A verified
    live test proved this: hot-copying the dead copy verbatim onto a running
    instance's /a0/webui/js/modals.js broke JS-extension loading with
    "module does not provide an export named 'isModalOpen'". So the overlay
    here is NOT a straight copy of the dead copy -- it is the REAL pinned
    base's modals.js (pulled from a live container running that exact image
    digest) with ONLY the same two B12 hunks cherry-picked on top (see
    docs/vendor-sync/ui-fork-cherry-pick.md's cherry-pick workflow). This is
    flagged for a maintainer to also refresh the dead copy itself (or accept
    it stays a stale reference and rely on this overlay directly).
    """

    OVERLAY_MODALS = A0_WEBUI / "js" / "modals.js"
    DEAD_COPY_MODALS = PROJECT_ROOT / "agent-zero" / "webui" / "js" / "modals.js"

    def test_overlay_modals_js_exists(self):
        assert self.OVERLAY_MODALS.is_file(), (
            "a0-webui/js/modals.js missing -- without it the build ships the "
            "pristine upstream modals.js (no B12 fix) onto /a0/webui/js/modals.js"
        )

    def test_overlay_has_friendly_title_helper(self):
        content = self.OVERLAY_MODALS.read_text()
        assert "export function friendlyTitleFromPath(path)" in content

    def test_overlay_wires_fallback_through_friendly_title(self):
        content = self.OVERLAY_MODALS.read_text()
        assert "doc.title || friendlyTitleFromPath(modalPath)" in content
        # Regression guard: must never regress to dumping the raw path.
        assert "doc.title || modalPath;" not in content

    def test_overlay_preserves_real_base_functionality_the_stale_dead_copy_lacks(self):
        # Regression guard for the exact live break this fix uncovered: the
        # overlay must be built on the REAL current base file, not the stale
        # dead copy -- proven by still carrying functionality (isModalOpen,
        # used by other framework JS extensions) the dead copy doesn't have.
        content = self.OVERLAY_MODALS.read_text()
        assert "export function isModalOpen(" in content, (
            "a0-webui/js/modals.js must be built on the real pinned base "
            "file (which exports isModalOpen), not the stale dead copy in "
            "agent-zero/webui/js/modals.js -- copying the stale file verbatim "
            "breaks JS-extension loading on a real running instance"
        )

    def test_dead_copy_is_a_known_stale_reference_not_a_deploy_source(self):
        # Documents the drift so nobody "fixes" the overlay back into a
        # byte-for-byte copy of the dead tree: the dead copy predates
        # functionality (isModalOpen and friends) the currently pinned base
        # image already has. It is fine as a place to read/port a semantic
        # fix from; it is not safe to `cp` wholesale onto the overlay.
        assert self.DEAD_COPY_MODALS.is_file(), (
            f"reference copy missing at {self.DEAD_COPY_MODALS}"
        )
        dead_lines = self.DEAD_COPY_MODALS.read_text().count("\n")
        overlay_lines = self.OVERLAY_MODALS.read_text().count("\n")
        assert dead_lines < overlay_lines, (
            "if the dead copy ever catches up to (or exceeds) the overlay's "
            "line count, re-verify whether it is safe to sync them again -- "
            "this assertion just documents the drift discovered 2026-08-10"
        )


class TestDockerfileBuildStep:
    """Deliverable 1b (build): Dockerfile.a0 must apply the overlay at image-build time."""

    DOCKERFILE = PROJECT_ROOT / "docker" / "Dockerfile.a0"

    def test_dockerfile_exists(self):
        assert self.DOCKERFILE.is_file(), "docker/Dockerfile.a0 missing"

    def test_dockerfile_has_overlay_build_step(self):
        """Verify Dockerfile.a0 contains the apply-branding.sh invocation as a
        RUN step (not only referenced from CI)."""
        content = self.DOCKERFILE.read_text()
        assert "COPY scripts/apply-branding.sh" in content, (
            "Dockerfile.a0 must COPY apply-branding.sh into the build stage"
        )
        assert "COPY a0-webui/" in content, (
            "Dockerfile.a0 must COPY a0-webui/ into the build stage"
        )
        assert "RUN bash /tmp/branding/scripts/apply-branding.sh" in content, (
            "Dockerfile.a0 must RUN apply-branding.sh as a build step"
        )
