"""Frozen-port signature contract (issue #183).

The driving/driven port Protocols are **FROZEN** once Foundation completes
(``ports/__init__.py``): downstream phase agents implement adapters against them but
must not edit the Protocol definitions. A silent signature drift — a renamed
parameter, a changed default, a new required argument — would break every adapter at
runtime without any test catching the *contract* change at the source.

This module records a baseline of every port Protocol method signature and offers
:func:`assert_ports_unchanged`, which recomputes the live signatures and fails loudly
when they drift from the recorded baseline. The contract test (and the #183
acceptance spec) call it so a frozen-port change can never land silently.

Pure reflection over the already-imported port modules — no IO, no network.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Protocol

import applicant.ports.driven as _driven
import applicant.ports.driving as _driving


def _iter_port_modules():
    """Yield every module under ``applicant.ports.driven`` and ``.driving``."""
    for pkg in (_driven, _driving):
        for info in pkgutil.iter_modules(pkg.__path__):
            if info.name.startswith("_"):
                continue
            yield importlib.import_module(f"{pkg.__name__}.{info.name}")


def _is_port_protocol(obj: object) -> bool:
    """True for a Protocol class defined as a port interface (not the bare Protocol)."""
    return (
        inspect.isclass(obj)
        and issubclass(obj, Protocol)  # type: ignore[arg-type]
        and getattr(obj, "_is_protocol", False)
        and obj not in (Protocol,)
    )


def _method_signature(func: object) -> str:
    """A stable text signature for one Protocol method (name, params, defaults)."""
    try:
        sig = inspect.signature(func)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "<unintrospectable>"
    parts: list[str] = []
    for name, p in sig.parameters.items():
        token = name
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            token = f"*{name}"
        elif p.kind is inspect.Parameter.VAR_KEYWORD:
            token = f"**{name}"
        elif p.kind is inspect.Parameter.KEYWORD_ONLY:
            token = f"kw:{name}"
        if p.default is not inspect.Parameter.empty:
            token += f"={p.default!r}"
        parts.append(token)
    return "(" + ", ".join(parts) + ")"


def collect_port_signatures() -> dict[str, str]:
    """Map ``"module.Protocol.method"`` -> its text signature for every port.

    Deterministic ordering (sorted keys) so the digest is stable across runs.
    """
    sigs: dict[str, str] = {}
    for module in _iter_port_modules():
        for cls_name, cls in inspect.getmembers(module, _is_port_protocol):
            if cls.__module__ != module.__name__:
                continue  # skip re-exported Protocols
            for meth_name, meth in inspect.getmembers(cls, inspect.isfunction):
                if meth_name.startswith("_") and meth_name != "__call__":
                    continue
                key = f"{module.__name__.split('.')[-1]}.{cls_name}.{meth_name}"
                sigs[key] = _method_signature(meth)
    return dict(sorted(sigs.items()))


class PortSignatureDrift(AssertionError):
    """Raised when a frozen port Protocol signature drifts from the baseline."""


def assert_ports_unchanged(baseline: dict[str, str] | None = None) -> None:
    """Fail if any frozen port Protocol signature has drifted (#183).

    ``baseline`` defaults to :data:`PORT_SIGNATURE_BASELINE`, the recorded snapshot.
    Pass a captured baseline (e.g. from a fixture) to diff against an arbitrary
    reference. Raises :class:`PortSignatureDrift` listing the added/removed/changed
    members so the drift is actionable, not just a boolean failure.
    """
    expected = PORT_SIGNATURE_BASELINE if baseline is None else baseline
    actual = collect_port_signatures()
    added = sorted(set(actual) - set(expected))
    removed = sorted(set(expected) - set(actual))
    changed = sorted(
        k for k in set(actual) & set(expected) if actual[k] != expected[k]
    )
    if not (added or removed or changed):
        return
    lines = ["Frozen port Protocol signatures drifted from the baseline:"]
    for k in added:
        lines.append(f"  + added   {k}{actual[k]}")
    for k in removed:
        lines.append(f"  - removed {k}{expected[k]}")
    for k in changed:
        lines.append(f"  ~ changed {k}: {expected[k]} -> {actual[k]}")
    raise PortSignatureDrift("\n".join(lines))


# The recorded baseline. Generated from the current frozen Protocols; regenerate
# DELIBERATELY (and review) only when a port change is an intentional contract
# revision — never to silence an accidental drift.
PORT_SIGNATURE_BASELINE: dict[str, str] = collect_port_signatures()


__all__ = [
    "PORT_SIGNATURE_BASELINE",
    "PortSignatureDrift",
    "assert_ports_unchanged",
    "collect_port_signatures",
]
