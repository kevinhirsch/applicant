"""Integrate step: ChatService._maybe_toolbox offers the RUX-6 action tools.

RUX-6 added ``edit_criteria`` / ``rescore`` / ``draft_application`` / ``discard_job`` to
``ChatToolbox``, gated on the criteria + digest services being passed through. The
Integrate step wires ``ChatService._maybe_toolbox`` to pass ``criteria_service`` and
``digest_service`` (which the service already holds) so the live campaign agent is
actually OFFERED those tools instead of them staying dark. This pins that wiring.
"""
from __future__ import annotations

from applicant.application.services.chat_service import ChatService


class _FakeLLM:
    """A tool-capable LLM stub (only the capability probes are exercised here)."""

    def is_configured(self):
        return True

    def supports_tools(self):
        return True

    def complete_with_tools(self, *a, **k):  # presence is all _maybe_toolbox checks
        raise AssertionError("not called in this test")


class _FakeCriteria:
    pass


class _FakeDigest:
    pass


def _service(*, criteria=None, digest=None) -> ChatService:
    return ChatService(
        attribute_service=object(),
        criteria_service=criteria,
        digest_service=digest,
        llm=_FakeLLM(),
        chat_tools="auto",
    )


def test_maybe_toolbox_offers_criteria_and_digest_tools():
    svc = _service(criteria=_FakeCriteria(), digest=_FakeDigest())
    toolbox = svc._maybe_toolbox("camp-1")
    assert toolbox is not None
    names = {s["function"]["name"] for s in toolbox.tool_schemas()}
    assert {"edit_criteria", "rescore", "draft_application", "discard_job"} <= names


def test_maybe_toolbox_dark_without_criteria_and_digest():
    # No criteria/digest passed => those action tools are not offered (and with no
    # other tool wired, no toolbox is built at all — byte-identical to pre-wiring).
    svc = _service(criteria=None, digest=None)
    toolbox = svc._maybe_toolbox("camp-1")
    assert toolbox is None
