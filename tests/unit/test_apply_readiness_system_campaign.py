"""Regression: the apply-readiness reporter must ignore the reserved __system__ campaign.

On a real deploy the __system__ campaign is seeded first (it holds instance secrets),
so storage.campaigns.list() returns it at index 0. The setup-status "what's still
missing" reporter fell back to campaigns[0] when no campaign was ready yet — reporting
__system__'s emptiness (every essential missing) instead of the operator's real
campaign, e.g. claiming a résumé was still needed right after one was uploaded. The
in-memory test lane never seeds __system__ (ensure_system_campaign no-ops without a
real session), which is why this slipped past CI; here we use a real SQLite DB.
"""

from __future__ import annotations

import tempfile

from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine
from applicant.app.config import Settings
from applicant.app.container import build_container
from applicant.core.entities.campaign import Campaign
from applicant.core.ids import SYSTEM_CAMPAIGN_ID, CampaignId
from applicant.ports.driving.onboarding import IntakeSection


def test_apply_readiness_reporter_ignores_system_campaign():
    db = tempfile.mktemp(suffix=".db")
    url = f"sqlite:///{db}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    c = build_container(Settings(DATABASE_URL=url))

    # Seed __system__ FIRST so it is campaigns[0] — reproduces the real deploy ordering.
    c.storage.campaigns.add(
        Campaign(id=CampaignId(SYSTEM_CAMPAIGN_ID), name="System (internal)", active=False)
    )
    c.storage.commit()
    # A real operator campaign that HAS a résumé (so its only remaining gaps are criteria).
    user = c.campaign_service.create_campaign("My job search")
    c.onboarding_service.save_section(str(user.id), IntakeSection.BASE_RESUME, {"parsed": True})
    c.storage.commit()

    assert c.onboarding_service.has_base_resume(str(user.id)) is True
    readiness = c.setup_service.apply_readiness()
    assert readiness is not None
    # The reporter must reflect the operator's campaign (which has a résumé), NOT the
    # empty __system__ campaign. Before the fix this listed "a résumé" as missing.
    assert "a résumé" not in readiness.missing, readiness.missing
