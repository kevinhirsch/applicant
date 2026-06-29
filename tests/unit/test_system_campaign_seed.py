"""`ensure_system_campaign` must seed the reserved __system__ campaign on a real DB.

Instance secrets (the LLM key) are sealed in the credential store, whose
campaign_id is a NOT-NULL FK to campaigns. On a real database the env-config path
in build_container writes that credential during construction — before lifespan's
seed runs — so the __system__ row must be seeded first or the insert raises
ForeignKeyViolation (the in-memory lane has no FK, which is exactly why CI missed
the original crash). These hermetic tests pin the helper's contract with a fake
storage that mimics the real session/repo surface.
"""

from __future__ import annotations

from applicant.app.container import ensure_system_campaign
from applicant.core.ids import SYSTEM_CAMPAIGN_ID


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
    def __init__(self, *, with_session: bool) -> None:
        self._session = object() if with_session else None
        self.campaigns = _FakeCampaigns()
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_seeds_system_campaign_on_real_db_then_is_idempotent():
    storage = _FakeStorage(with_session=True)
    assert ensure_system_campaign(storage) is True  # created
    assert storage.campaigns.get(SYSTEM_CAMPAIGN_ID) is not None
    assert storage.commits == 1
    # Second call is a no-op (row already present) — does not double-seed.
    assert ensure_system_campaign(storage) is False
    assert storage.commits == 1


def test_noop_on_in_memory_storage_without_session():
    storage = _FakeStorage(with_session=False)
    assert ensure_system_campaign(storage) is False
    assert storage.campaigns.get(SYSTEM_CAMPAIGN_ID) is None
    assert storage.commits == 0
