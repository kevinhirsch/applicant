"""`ensure_default_campaign` must seed one active USER campaign on a fresh install.

The OOBE onboarding and every active-campaign resolver need a non-system campaign;
with none, the resolver falls back to the reserved __system__ campaign and onboarding
against it fails (fresh-install OOBE was broken, 2026-08). These hermetic tests pin the
helper's contract with a fake storage that mimics the real session/repo surface.
"""

from __future__ import annotations

from applicant.app.container import ensure_default_campaign
from applicant.core.ids import SYSTEM_CAMPAIGN_ID, CampaignId, new_id


class _FakeCampaigns:
    def __init__(self) -> None:
        self._rows: dict[str, object] = {}

    def get(self, cid):
        return self._rows.get(cid)

    def add(self, campaign):
        if campaign.id in self._rows:
            raise ValueError("duplicate campaign id")
        self._rows[campaign.id] = campaign

    def list(self):
        return list(self._rows.values())


class _FakeStorage:
    def __init__(self, *, with_session: bool, seed_system: bool = False) -> None:
        self._session = object() if with_session else None
        self.campaigns = _FakeCampaigns()
        self.commits = 0
        self.rollbacks = 0
        if seed_system:
            from applicant.core.entities.campaign import Campaign

            self.campaigns.add(
                Campaign(id=CampaignId(SYSTEM_CAMPAIGN_ID), name="System (internal)", active=False)
            )

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_seeds_default_campaign_when_only_system_then_idempotent():
    storage = _FakeStorage(with_session=True, seed_system=True)
    assert ensure_default_campaign(storage) is True
    users = [c for c in storage.campaigns.list() if str(c.id) != SYSTEM_CAMPAIGN_ID]
    assert len(users) == 1 and users[0].active is True
    assert storage.commits == 1
    # Second call is a no-op: a user campaign now exists.
    assert ensure_default_campaign(storage) is False
    assert len([c for c in storage.campaigns.list() if str(c.id) != SYSTEM_CAMPAIGN_ID]) == 1


def test_noop_when_a_user_campaign_already_exists():
    from applicant.core.entities.campaign import Campaign

    storage = _FakeStorage(with_session=True)
    storage.campaigns.add(Campaign(id=CampaignId(new_id()), name="Existing", active=True))
    assert ensure_default_campaign(storage) is False
    assert storage.commits == 0


def test_noop_on_in_memory_storage_without_session():
    storage = _FakeStorage(with_session=False)
    assert ensure_default_campaign(storage) is False
    assert storage.commits == 0
