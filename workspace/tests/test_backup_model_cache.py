"""applicant-backup should skip re-downloadable model caches by default.

data/huggingface/ and data/fastembed_cache/ are pure caches (often many GB)
the app re-fetches on demand; including them only bloats the tarball.
"""
import tarfile
import types
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "applicant-backup"


def _load_backup_module():
    loader = SourceFileLoader("fhbackup", str(_SCRIPT))
    mod = module_from_spec(spec_from_loader("fhbackup", loader))
    loader.exec_module(mod)
    return mod


def _snapshot_names(tmp_path, **flags):
    mod = _load_backup_module()
    data = tmp_path / "data"
    backups = tmp_path / "backups"
    for rel in ("app.db", "memory.json",
                "huggingface/models--foo/blob1.bin",
                "fastembed_cache/model.onnx",
                "personal_docs/keepme.txt"):
        f = data / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * 10)
    mod._DATA_DIR = data
    mod._BACKUP_DIR = backups
    mod.emit = lambda *a, **k: None  # silence output

    out = backups / "snap.tar.gz"
    args = types.SimpleNamespace(
        out=str(out), include_research=False, include_attachments=False,
        include_model_cache=False, pretty=False, json=True)
    for k, v in flags.items():
        setattr(args, k, v)
    mod.cmd_snapshot(args)
    with tarfile.open(out, "r:gz") as t:
        return sorted(t.getnames())


def test_model_caches_skipped_by_default(tmp_path):
    names = _snapshot_names(tmp_path)
    assert not any("huggingface" in n for n in names)
    assert not any("fastembed_cache" in n for n in names)
    # user data is still backed up
    assert any(n.endswith("app.db") for n in names)
    assert any("personal_docs" in n for n in names)


def test_include_model_cache_keeps_them(tmp_path):
    names = _snapshot_names(tmp_path, include_model_cache=True)
    assert any("huggingface" in n for n in names)
    assert any("fastembed_cache" in n for n in names)
