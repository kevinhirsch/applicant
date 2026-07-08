"""P2-14 -- Easy Apply assisted-mode brief endpoint (``GET /api/easy-apply/
{campaign_id}/{posting_id}``).

Exercises ``applicant.app.routers.easy_apply.assist`` directly against fakes
(mirrors ``test_llm_router_status.py``'s hermetic style) -- no DB/network/LLM.
The endpoint is a real stop-boundary: it must 409 until consent was actually
recorded, and it must never fabricate a posting that doesn't exist / doesn't
belong to the given campaign / isn't actually tagged Easy Apply.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from applicant.app.routers.easy_apply import ASSIST_CHECKLIST, assist
from applicant.core.ids import CampaignId, JobPostingId, new_id


def _posting(*, campaign_id, easy_apply=True, **overrides):
    fields = {
        "id": JobPostingId(new_id()),
        "campaign_id": campaign_id,
        "title": "Staff Engineer",
        "company": "Acme",
        "source_url": "https://example.test/jobs/acme-staff-eng",
        "easy_apply": easy_apply,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class _FakeSetupService:
    def __init__(self, *, given=False, given_at=None):
        self._given = given
        self._given_at = given_at

    def easy_apply_consent_status(self):
        return {"given": self._given, "given_at": self._given_at}


class _FakePostings:
    def __init__(self, postings=None):
        self._postings = postings or {}

    def get(self, posting_id):
        return self._postings.get(str(posting_id))


def _storage(postings=None):
    return SimpleNamespace(postings=_FakePostings(postings))


@pytest.mark.unit
class TestEasyApplyAssistRoute:
    def test_no_consent_is_409(self):
        cid = CampaignId(new_id())
        posting = _posting(campaign_id=cid)
        svc = _FakeSetupService(given=False)
        storage = _storage({str(posting.id): posting})
        with pytest.raises(HTTPException) as exc:
            assist(str(cid), str(posting.id), svc=svc, storage=storage)
        assert exc.value.status_code == 409

    def test_unknown_posting_is_404_even_with_consent(self):
        cid = CampaignId(new_id())
        svc = _FakeSetupService(given=True, given_at="2026-07-08T00:00:00+00:00")
        storage = _storage({})
        with pytest.raises(HTTPException) as exc:
            assist(str(cid), str(new_id()), svc=svc, storage=storage)
        assert exc.value.status_code == 404

    def test_posting_from_a_different_campaign_is_404(self):
        real_cid = CampaignId(new_id())
        other_cid = CampaignId(new_id())
        posting = _posting(campaign_id=real_cid)
        svc = _FakeSetupService(given=True, given_at="2026-07-08T00:00:00+00:00")
        storage = _storage({str(posting.id): posting})
        with pytest.raises(HTTPException) as exc:
            assist(str(other_cid), str(posting.id), svc=svc, storage=storage)
        assert exc.value.status_code == 404

    def test_posting_not_tagged_easy_apply_is_404(self):
        cid = CampaignId(new_id())
        posting = _posting(campaign_id=cid, easy_apply=False)
        svc = _FakeSetupService(given=True, given_at="2026-07-08T00:00:00+00:00")
        storage = _storage({str(posting.id): posting})
        with pytest.raises(HTTPException) as exc:
            assist(str(cid), str(posting.id), svc=svc, storage=storage)
        assert exc.value.status_code == 404

    def test_consented_real_easy_apply_posting_returns_the_brief(self):
        cid = CampaignId(new_id())
        posting = _posting(campaign_id=cid)
        svc = _FakeSetupService(given=True, given_at="2026-07-08T00:00:00+00:00")
        storage = _storage({str(posting.id): posting})
        result = assist(str(cid), str(posting.id), svc=svc, storage=storage)
        assert result["title"] == "Staff Engineer"
        assert result["company"] == "Acme"
        assert result["deep_link"] == posting.source_url
        assert result["checklist"] == list(ASSIST_CHECKLIST)
        assert result["consent_given_at"] == "2026-07-08T00:00:00+00:00"

    def test_checklist_never_offers_to_auto_answer_eeo_or_work_auth(self):
        """The checklist must send the user to answer these themselves --
        never imply the assistant will answer on their behalf (matches the
        core sensitive-fields guard's own posture)."""
        joined = " ".join(ASSIST_CHECKLIST).lower()
        assert "eeo" in joined or "work-authorization" in joined
        assert "never answers for you" in joined or "yourself" in joined
