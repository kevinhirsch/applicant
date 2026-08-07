"""Unit tests for the single-conversation extension hook (FR-UX).

The hook lives in the product plugin tree (``a0-applicant/extensions/python/...``);
in production ``docker/Dockerfile.a0`` copies ``a0-applicant/`` to
``/a0/plugins/applicant/`` so the framework discovers it at runtime. Here we
load the file directly. It imports ``helpers.extension.Extension`` (a framework
module not present in the project's pytest venv), so a hermetic stub is
installed only when a real framework module isn't already importable.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_HOOK = (
    Path(__file__).resolve().parents[2]
    / "a0-applicant/extensions/python/_functions/agent/AgentContext/__init__/start"
    / "_10_force_single_context.py"
)


@pytest.fixture(scope="module", autouse=True)
def _hermetic_helpers_extension():
    """Provide a stub ``helpers.extension.Extension`` if the framework is absent."""
    if "helpers" in sys.modules or "helpers.extension" in sys.modules:
        yield
        return
    pkg = types.ModuleType("helpers")
    ext = types.ModuleType("helpers.extension")

    class Extension:
        pass

    ext.Extension = Extension
    pkg.extension = ext
    sys.modules["helpers"] = pkg
    sys.modules["helpers.extension"] = ext
    yield
    sys.modules.pop("helpers.extension", None)
    sys.modules.pop("helpers", None)


def _load_hook():
    spec = importlib.util.spec_from_file_location("force_single_context_hook", _HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_canonical_id_is_main():
    mod = _load_hook()
    assert mod.CANONICAL_CONTEXT_ID == "main"


def test_forces_new_user_mint_onto_main():
    mod = _load_hook()
    ext = mod.ForceSingleContext()
    data = {"kwargs": {"config": object()}}  # no id, no type -> defaults USER
    ext.execute(data=data)
    assert data["kwargs"]["id"] == "main"


def test_forces_empty_string_id_onto_main():
    mod = _load_hook()
    ext = mod.ForceSingleContext()
    data = {"kwargs": {"config": object(), "id": ""}}
    ext.execute(data=data)
    assert data["kwargs"]["id"] == "main"


def test_preserves_explicit_restore_id():
    """Persisted-chat restores always pass an explicit id; never clobber them."""
    mod = _load_hook()
    ext = mod.ForceSingleContext()
    data = {"kwargs": {"config": object(), "id": "some-existing-context"}}
    ext.execute(data=data)
    assert data["kwargs"]["id"] == "some-existing-context"


def test_does_not_touch_task_background_contexts():
    """Scheduler/background contexts must never collapse into the user thread."""
    mod = _load_hook()
    ext = mod.ForceSingleContext()

    class _Type:
        def __init__(self, value):
            self.value = value

    data = {"kwargs": {"config": object(), "type": _Type("task")}}
    ext.execute(data=data)
    assert "id" not in data["kwargs"]

    data = {"kwargs": {"config": object(), "type": _Type("background")}}
    ext.execute(data=data)
    assert "id" not in data["kwargs"]


def test_hook_handles_missing_kwargs_gracefully():
    mod = _load_hook()
    ext = mod.ForceSingleContext()
    ext.execute(data=None)
    ext.execute(data={"args": ()})  # no kwargs dict
    ext.execute()  # no data at all
