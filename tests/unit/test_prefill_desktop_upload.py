"""Guarded desktop file-upload fallback during pre-fill (FR-CUA, FR-RESUME-4).

When a résumé/CV file input opens a NATIVE OS file-picker the browser DOM can't
satisfy, AND desktop assist (computer use) is genuinely operable, the pre-fill loop
completes the off-page dialog with the bounded ``ComputerUsePort`` (focus → type the
résumé PATH → confirm) and records the document exactly as the DOM path would. When
computer use is the noop/unhealthy backend it is NEVER invoked and behavior is exactly
today's (skip / human hand-off). The stop-boundary (FR-CUA-3) still refuses a non-upload
desktop action. Hermetic: a fake operable ComputerUsePort recording calls — no desktop.
"""

from __future__ import annotations

import pytest

from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.sandbox.computer_use.noop import NoopComputerUse
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.prefill_service import PrefillResult, PrefillService
from applicant.core.entities.application import Application
from applicant.core.errors import (
    ComputerUseBlocked,
    NativeFilePickerRequired,
    PrefillBoundaryViolation,
)
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.rules.computer_use import CaptureMode, DesktopAction
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.browser_automation import DetectedField, PageState
from applicant.ports.driven.computer_use import (
    CaptureResult,
    DesktopActionResult,
    HealthReport,
)

URL = "https://acme.myworkdayjobs.com/job/123"


def _app(cid):
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        root_url=URL,
    )


class _PickerBrowser:
    """Browser stub whose résumé upload opens a NATIVE OS picker the DOM can't satisfy."""

    def __init__(self, field: DetectedField, *, carry_path: bool = True) -> None:
        self._field = field
        self._carry_path = carry_path
        self.uploads: list[tuple[str, str]] = []

    def current_state(self, aid):  # noqa: ARG002
        return PageState(url="https://x/form", fields=())

    def detect_fields(self, aid):  # noqa: ARG002
        return [self._field]

    def upload_file(self, aid, selector, file_path):  # noqa: ARG002
        self.uploads.append((selector, file_path))
        raise NativeFilePickerRequired(
            file_path=file_path if self._carry_path else None
        )


class _PlainBrowser(_PickerBrowser):
    """Browser stub whose résumé upload succeeds via the DOM (no native picker)."""

    def upload_file(self, aid, selector, file_path):  # noqa: ARG002
        self.uploads.append((selector, file_path))


class _FixedProvider:
    def __init__(self, path):
        self._path = path

    def resume_file_for(self, application):  # noqa: ARG002
        return self._path


class _FakeOperableDesktop:
    """A fake operable ``ComputerUsePort`` recording calls (real backend, healthy)."""

    backend = "cua"  # NOT the noop test backend → reads as operable when healthy

    def __init__(self, *, ok: bool = True) -> None:
        self._ok = ok
        self.calls: list[tuple[str, tuple, dict]] = []

    def health(self) -> HealthReport:
        return HealthReport(ok=self._ok, backend=self.backend, detail="fake")

    def focus_app(self, app, **kw):
        self.calls.append(("focus_app", (app,), kw))
        return DesktopActionResult(DesktopAction.FOCUS_APP, detail=app)

    def type_text(self, text, **kw):
        self.calls.append(("type_text", (text,), kw))
        return DesktopActionResult(DesktopAction.TYPE_TEXT)

    def key(self, keys, **kw):
        self.calls.append(("key", (keys,), kw))
        return DesktopActionResult(DesktopAction.KEY, detail=keys)

    def capture(self, mode: CaptureMode = CaptureMode.SOM) -> CaptureResult:
        self.calls.append(("capture", (mode,), {}))
        return CaptureResult(mode=mode)


def _service(browser, provider, computer_use=None):
    return PrefillService(
        storage=InMemoryStorage(),
        browser=browser,
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
        llm=None,
        resume_provider=provider,
        computer_use=computer_use,
    )


def _resume_field():
    return DetectedField(selector="#resume", label="Resume/CV", field_type="file")


@pytest.mark.unit
class TestDesktopUploadFallback:
    def test_operable_desktop_completes_native_picker_and_records(self, tmp_path):
        resume = tmp_path / "base.pdf"
        resume.write_bytes(b"%PDF-1.7 fake")
        browser = _PickerBrowser(_resume_field())
        cu = _FakeOperableDesktop()
        svc = _service(browser, _FixedProvider(str(resume)), computer_use=cu)
        app = _app(CampaignId(new_id()))
        result = PrefillResult(application_id=app.id, state=app.status)

        assert svc._fill_current_page(app, [], result) is None

        # The desktop fallback drove focus → type-path → confirm, in order.
        names = [c[0] for c in cu.calls]
        assert names == ["focus_app", "type_text", "key"]
        # It typed the RESOLVED résumé PATH (not a secret) and confirmed with Enter.
        type_call = next(c for c in cu.calls if c[0] == "type_text")
        assert type_call[1][0] == str(resume)
        assert type_call[2].get("is_secret") is False
        key_call = next(c for c in cu.calls if c[0] == "key")
        assert key_call[1][0] == "enter"
        # The document was recorded exactly as the DOM path would (FR-RESUME-4).
        assert result.uploaded_documents == [
            {"selector": "#resume", "label": "Resume/CV", "path": str(resume), "url": "https://x/form"}
        ]

    def test_noop_desktop_is_not_invoked_and_degrades(self, tmp_path):
        # The default noop backend is NOT operable → the fallback must not run and the
        # upload degrades exactly as today (nothing recorded, no desktop call).
        resume = tmp_path / "base.pdf"
        resume.write_bytes(b"%PDF-1.7 fake")
        browser = _PickerBrowser(_resume_field())
        cu = NoopComputerUse()  # backend == "noop"
        svc = _service(browser, _FixedProvider(str(resume)), computer_use=cu)
        app = _app(CampaignId(new_id()))
        result = PrefillResult(application_id=app.id, state=app.status)

        assert svc._fill_current_page(app, [], result) is None
        assert cu.calls == []  # never invoked the bounded desktop vocabulary
        assert result.uploaded_documents == []  # degraded — nothing recorded

    def test_unhealthy_desktop_is_not_invoked_and_degrades(self, tmp_path):
        resume = tmp_path / "base.pdf"
        resume.write_bytes(b"%PDF-1.7 fake")
        browser = _PickerBrowser(_resume_field())
        cu = _FakeOperableDesktop(ok=False)  # cua backend but health preflight FAILS
        svc = _service(browser, _FixedProvider(str(resume)), computer_use=cu)
        app = _app(CampaignId(new_id()))
        result = PrefillResult(application_id=app.id, state=app.status)

        assert svc._fill_current_page(app, [], result) is None
        assert cu.calls == []
        assert result.uploaded_documents == []

    def test_no_computer_use_wired_degrades(self, tmp_path):
        resume = tmp_path / "base.pdf"
        resume.write_bytes(b"%PDF-1.7 fake")
        browser = _PickerBrowser(_resume_field())
        svc = _service(browser, _FixedProvider(str(resume)))  # no desktop port
        app = _app(CampaignId(new_id()))
        result = PrefillResult(application_id=app.id, state=app.status)

        assert svc._fill_current_page(app, [], result) is None
        assert result.uploaded_documents == []

    def test_dom_upload_success_never_touches_desktop(self, tmp_path):
        # When the DOM path satisfies the upload (no native picker), the operable
        # desktop port is never used — desktop assist is the fallback, not the default.
        resume = tmp_path / "base.pdf"
        resume.write_bytes(b"%PDF-1.7 fake")
        browser = _PlainBrowser(_resume_field())
        cu = _FakeOperableDesktop()
        svc = _service(browser, _FixedProvider(str(resume)), computer_use=cu)
        app = _app(CampaignId(new_id()))
        result = PrefillResult(application_id=app.id, state=app.status)

        assert svc._fill_current_page(app, [], result) is None
        assert cu.calls == []
        assert result.uploaded_documents and result.uploaded_documents[0]["path"] == str(resume)

    def test_picker_without_carried_path_falls_back_to_resolved_path(self, tmp_path):
        resume = tmp_path / "base.pdf"
        resume.write_bytes(b"%PDF-1.7 fake")
        browser = _PickerBrowser(_resume_field(), carry_path=False)
        cu = _FakeOperableDesktop()
        svc = _service(browser, _FixedProvider(str(resume)), computer_use=cu)
        app = _app(CampaignId(new_id()))
        result = PrefillResult(application_id=app.id, state=app.status)

        assert svc._fill_current_page(app, [], result) is None
        type_call = next(c for c in cu.calls if c[0] == "type_text")
        assert type_call[1][0] == str(resume)


@pytest.mark.unit
class TestDesktopUploadStaysBoundedAndSafe:
    def test_stop_boundary_still_refuses_a_non_upload_desktop_action(self):
        # The desktop fallback is bounded to the file-attach; the stop-boundary
        # (FR-CUA-3) still refuses a boundary action like a final-submit click,
        # enforced in the real adapter regardless of any caller.
        cu = NoopComputerUse()
        with pytest.raises(PrefillBoundaryViolation):
            cu.click("submit-token", intent="final_submit")

    def test_desktop_fallback_never_types_a_secret(self):
        # FR-CUA-6: even the bounded fallback's type call passes is_secret=False; a
        # secret value would be refused by the adapter regardless.
        cu = NoopComputerUse()
        with pytest.raises(ComputerUseBlocked):
            cu.type_text("hunter2", is_secret=True)
