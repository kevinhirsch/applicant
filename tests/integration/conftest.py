"""Integration-lane parent-row seeding helpers (FK ordering for a real Postgres).

The real-Postgres *isolation* machinery (per-worker database, per-test reset, small
connection pool) lives in the ROOT ``tests/conftest.py`` so it covers every
``@pytest.mark.integration`` test wherever it lives.  This module adds the
parents-before-children seeding factories used by the integration tests in this
directory: against a real database, a child row (attribute, generated material,
application, …) needs its parent ``campaigns`` / ``job_postings`` row to exist first,
which the in-memory store never required.
"""

from __future__ import annotations

import pytest


def make_campaign(client, name: str = "Test campaign") -> str:
    """Create a real campaign through the API and return its id.

    The campaigns router mints its own id, so seed via the public endpoint and use
    the returned id as the parent for any child rows — this is the parents-before-
    children ordering a real database requires.  Assumes the LLM gate is already
    open (``/api/setup/llm``), which the create-campaign path requires.
    """
    r = client.post("/api/campaigns", json={"name": name})
    assert r.status_code == 201, f"campaign create failed: {r.status_code} {r.text}"
    return r.json()["id"]


@pytest.fixture
def seeded_campaign(client):
    """A factory that creates real campaign parent rows for the test's ``client``.

    Usage: ``cid = seeded_campaign()`` (or ``seeded_campaign("Name")``).  Use this
    instead of a fabricated ``new_id()``/literal id whenever a test writes a child
    row (attribute, generated material, criteria, onboarding, credential, …) that
    references a campaign — the parent must exist first on a real database.
    """

    def _factory(name: str = "Test campaign") -> str:
        return make_campaign(client, name)

    return _factory


@pytest.fixture
def seeded_application(client):
    """A factory that seeds a campaign + posting + application parent chain.

    Returns ``(campaign_id, application_id)``.  Inserts directly via the container
    storage (there is no public create-application endpoint) so outcome / screenshot
    / decision / generated-material children have the parent rows their FKs require.
    The posting is created too, since ``applications.posting_id`` is an FK to
    ``job_postings``.
    """
    from applicant.core.entities.application import Application
    from applicant.core.entities.job_posting import JobPosting
    from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id

    def _factory(
        *, status=None, root_url: str | None = None, name: str = "Test campaign"
    ) -> tuple[str, str]:
        cid = make_campaign(client, name)
        storage = client.app.state.container.storage
        posting_id = new_id()
        storage.postings.add(
            JobPosting(
                id=JobPostingId(posting_id),
                campaign_id=CampaignId(cid),
                title="Test role",
                company="Test co",
                source_url=root_url or "https://example.test/job",
            )
        )
        aid = new_id()
        kwargs: dict = {
            "id": ApplicationId(aid),
            "campaign_id": CampaignId(cid),
            "posting_id": JobPostingId(posting_id),
        }
        if status is not None:
            kwargs["status"] = status
        if root_url is not None:
            kwargs["root_url"] = root_url
        storage.applications.add(Application(**kwargs))
        storage.commit()
        return cid, aid

    return _factory
