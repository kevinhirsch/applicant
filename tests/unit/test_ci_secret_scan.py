"""Hermetic coverage for the CI secret-scanning guard (P1-0, issue #651).

Exercises ``scripts/ci/secret_scan.py`` directly against a scratch git repo
(never against the real working tree from inside the test — that would make
the test's pass/fail depend on whatever happens to be committed) so this stays
a pure, hermetic unit test of the scanner's own logic: it flags real-looking
credentials, it does not flag illustrative/fixture/detector-regex text, and
its exclusion list is honored.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "secret_scan.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("secret_scan", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "ci"], cwd=tmp_path, check=True)
    return tmp_path


def _write_and_track(repo: Path, rel_path: str, content: str) -> None:
    full = repo / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    subprocess.run(["git", "add", rel_path], cwd=repo, check=True)


def _run_scan_against(repo: Path):
    module = _load_module()
    original_root = module.REPO_ROOT
    try:
        module.REPO_ROOT = repo
        return module.scan()
    finally:
        module.REPO_ROOT = original_root


def test_scanner_module_is_importable():
    # Guards against the CI step regressing to an uncaught SyntaxError/ImportError
    # (which would otherwise only surface as an opaque CI failure).
    _load_module()


def test_flags_a_real_looking_openai_style_key(tmp_path):
    repo = _init_repo(tmp_path)
    _write_and_track(repo, "config.py", 'OPENROUTER_KEY = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ01234"\n')
    findings = _run_scan_against(repo)
    assert any("config.py" in f for f in findings)


def test_flags_a_github_token_and_a_pem_private_key(tmp_path):
    repo = _init_repo(tmp_path)
    _write_and_track(repo, "deploy.env", "GH_TOKEN=ghp_" + "a" * 40 + "\n")
    _write_and_track(
        repo,
        "id_rsa",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIB...redacted...\n-----END RSA PRIVATE KEY-----\n",
    )
    findings = _run_scan_against(repo)
    assert any("deploy.env" in f for f in findings)
    assert any("id_rsa" in f for f in findings)


def test_does_not_flag_illustrative_prefixes_without_a_real_payload(tmp_path):
    repo = _init_repo(tmp_path)
    _write_and_track(
        repo,
        "docs/setup.md",
        "Usage: /setup openrouter sk-or-...\nUsage: /setup anthropic sk-ant-...\n",
    )
    findings = _run_scan_against(repo)
    assert findings == []


def test_does_not_flag_a_short_placeholder_value(tmp_path):
    repo = _init_repo(tmp_path)
    _write_and_track(repo, "fixture.py", '{"api_key": "sk-x"}\n')
    findings = _run_scan_against(repo)
    assert findings == []


def test_honors_the_allowed_files_exclusion_list(tmp_path):
    repo = _init_repo(tmp_path)
    # Same content that would otherwise trip the scan, but under a path this
    # repo's own scanner explicitly allow-lists as a fixture/detector file.
    _write_and_track(
        repo,
        "tests/unit/test_observability.py",
        'sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ01234\n',
    )
    findings = _run_scan_against(repo)
    assert findings == []


def test_skips_lockfiles(tmp_path):
    repo = _init_repo(tmp_path)
    _write_and_track(repo, "uv.lock", 'sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ01234\n')
    findings = _run_scan_against(repo)
    assert findings == []


def test_main_exits_nonzero_when_findings_present(tmp_path):
    repo = _init_repo(tmp_path)
    _write_and_track(repo, "leak.py", 'KEY = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ01234"\n')
    module = _load_module()
    original_root = module.REPO_ROOT
    try:
        module.REPO_ROOT = repo
        assert module.main() == 1
    finally:
        module.REPO_ROOT = original_root


def test_main_exits_zero_on_the_real_repo_working_tree():
    """The scanner run against the actual repo (as CI will run it) is clean."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=_SCRIPT.resolve().parents[2],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
