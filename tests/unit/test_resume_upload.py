"""Résumé-upload plumbing tests (FR-RESUME-4).

Phase 2 "upload the base résumé as-is": the pre-fill loop must attach the user's
uploaded base résumé to an ATS résumé/CV ``<input type=file>`` — a deterministic,
boundary-safe pre-fill step — while leaving cover-letter / unrelated file inputs
untouched. Hermetic: no browser, no real ATS.
"""

from __future__ import annotations

import pytest

from applicant.adapters.browser.ats import FakePage
from applicant.adapters.browser.page_source import FakePageSource
from applicant.adapters.browser.patchright_browser import PatchrightBrowser
from applicant.adapters.detection.detection_monitor import DetectionMonitor
from applicant.adapters.resume_tailoring.base_resume_provider import BaseResumeProvider
from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.prefill_service import PrefillResult, PrefillService
from applicant.core.entities.application import Application
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    OnboardingProfileId,
    new_id,
)
from applicant.core.rules.prefill_boundary import StepKind, ensure_action_allowed
from applicant.core.state_machine import ApplicationState
from applicant.ports.driven.browser_automation import DetectedField, PageState

URL = "https://acme.myworkdayjobs.com/job/123"


def _app(cid):
    return Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        root_url=URL,
    )


class _FileFieldBrowser:
    """Minimal browser stub exposing one detected field + recording uploads."""

    def __init__(self, field: DetectedField) -> None:
        self._field = field
        self.uploads: list[tuple[str, str]] = []

    def current_state(self, aid):  # noqa: ARG002
        return PageState(url="https://x/form", fields=())

    def detect_fields(self, aid):  # noqa: ARG002
        return [self._field]

    def upload_file(self, aid, selector, file_path):  # noqa: ARG002
        self.uploads.append((selector, file_path))


def _service(browser, provider):
    return PrefillService(
        storage=InMemoryStorage(),
        browser=browser,
        detection=DetectionMonitor(),
        sandbox=LocalSandbox(),
        credentials=None,
        llm=None,
        resume_provider=provider,
    )


class _FixedProvider:
    def __init__(self, path):
        self._path = path

    def resume_file_for(self, application):  # noqa: ARG002
        return self._path


@pytest.mark.unit
class TestResumeUploadDuringPrefill:
    def test_resume_input_gets_base_resume_uploaded_and_recorded(self, tmp_path):
        resume = tmp_path / "base.pdf"
        resume.write_bytes(b"%PDF-1.7 fake")
        browser = _FileFieldBrowser(
            DetectedField(selector="#resume", label="Resume/CV", field_type="file")
        )
        svc = _service(browser, _FixedProvider(str(resume)))
        app = _app(CampaignId(new_id()))
        result = PrefillResult(application_id=app.id, state=app.status)

        assert svc._fill_current_page(app, [], result) is None
        # The base résumé was attached to the file input...
        assert browser.uploads == [("#resume", str(resume))]
        # ...and recorded for the surfacing/handoff log (FR-RESUME-4).
        assert result.uploaded_documents == [
            {"selector": "#resume", "label": "Resume/CV", "path": str(resume), "url": "https://x/form"}
        ]

    def test_cover_letter_file_input_is_skipped(self, tmp_path):
        resume = tmp_path / "base.pdf"
        resume.write_bytes(b"%PDF-1.7 fake")
        browser = _FileFieldBrowser(
            DetectedField(selector="#cover", label="Cover Letter", field_type="file")
        )
        svc = _service(browser, _FixedProvider(str(resume)))
        app = _app(CampaignId(new_id()))
        result = PrefillResult(application_id=app.id, state=app.status)

        assert svc._fill_current_page(app, [], result) is None
        assert browser.uploads == []
        assert result.uploaded_documents == []

    def test_no_provider_skips_upload_without_error(self, tmp_path):
        browser = _FileFieldBrowser(
            DetectedField(selector="#resume", label="Resume", field_type="file")
        )
        svc = _service(browser, None)  # no provider wired
        app = _app(CampaignId(new_id()))
        result = PrefillResult(application_id=app.id, state=app.status)

        assert svc._fill_current_page(app, [], result) is None
        assert browser.uploads == []
        assert result.uploaded_documents == []

    def test_provider_returns_none_skips_upload(self):
        browser = _FileFieldBrowser(
            DetectedField(selector="#resume", label="Resume", field_type="file")
        )
        svc = _service(browser, _FixedProvider(None))
        app = _app(CampaignId(new_id()))
        result = PrefillResult(application_id=app.id, state=app.status)

        assert svc._fill_current_page(app, [], result) is None
        assert browser.uploads == []

    def test_resume_input_detected_by_selector_id(self):
        # The label is empty but the selector ``#cv`` identifies it (token-aware match).
        assert PrefillService._is_resume_input(
            DetectedField(selector="#cv", label="", field_type="file")
        )
        # A bare "cv" must not match inside an unrelated word like "service".
        assert not PrefillService._is_resume_input(
            DetectedField(selector="#service_doc", label="Service document", field_type="file")
        )


@pytest.mark.unit
class TestUploadBrowserPrimitive:
    def test_patchright_upload_routes_through_fake_source(self):
        browser = PatchrightBrowser()
        aid = ApplicationId(new_id())
        browser.open(aid, URL)
        browser.upload_file(aid, "#resume", "/tmp/base.pdf")
        assert browser._source(aid).uploaded() == {"#resume": "/tmp/base.pdf"}

    def test_fake_page_source_records_upload(self):
        src = FakePageSource()
        src._pages = [FakePage(url="https://x/form")]
        src._index = 0
        src.set_input_files("#resume", "/tmp/r.pdf")
        assert src.uploaded() == {"#resume": "/tmp/r.pdf"}

    def test_upload_document_step_is_always_allowed(self):
        # The upload step never trips the pre-fill-stop boundary (no submit).
        ensure_action_allowed(StepKind.UPLOAD_DOCUMENT)


@pytest.mark.unit
class TestBaseResumeProvider:
    def _seed(self, storage, cid, document_path):
        storage.onboarding_profiles.add(
            OnboardingProfile(
                id=OnboardingProfileId(new_id()),
                campaign_id=cid,
                completion_flag=True,
                intake={"base_resume": {"document_path": document_path, "raw_text": "x"}},
            )
        )

    def test_returns_uploaded_base_resume_path(self, tmp_path):
        resume = tmp_path / "base.docx"
        resume.write_bytes(b"PK fake docx")
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        self._seed(storage, cid, str(resume))
        provider = BaseResumeProvider(storage)
        assert provider.resume_file_for(_app(cid)) == str(resume)

    def test_returns_none_when_file_missing_on_disk(self):
        storage = InMemoryStorage()
        cid = CampaignId(new_id())
        self._seed(storage, cid, "/no/such/file.pdf")
        provider = BaseResumeProvider(storage)
        assert provider.resume_file_for(_app(cid)) is None

    def test_returns_none_when_no_profile(self):
        provider = BaseResumeProvider(InMemoryStorage())
        assert provider.resume_file_for(_app(CampaignId(new_id()))) is None
