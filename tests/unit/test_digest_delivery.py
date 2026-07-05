"""Digest delivery + decline-with-feedback round-trip (FR-DIG-2/5, FR-FB-1, FR-LEARN-3).

Covers the email/webpage/Discord-ready delivery and the close-the-loop wiring that
folds a decline into LearningService + the next run's criteria.
"""

from __future__ import annotations

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.criteria_service import CriteriaService
from applicant.application.services.digest_service import DigestService
from applicant.application.services.learning_service import LearningService
from applicant.application.services.notification_service import NotificationService
from applicant.application.services.pending_actions_service import PendingActionsService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    new_id,
)


def _wire():
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    learning = LearningService(storage, embedding)
    criteria = CriteriaService(storage, llm=None)
    notif_svc = NotificationService(notifier)
    pending = PendingActionsService(storage)
    scoring = ScoringService(storage, llm=None, embedding=embedding, threshold=0)
    digest = DigestService(
        storage,
        notifier,
        scoring,
        learning=learning,
        criteria=criteria,
        notification_service=notif_svc,
        pending_actions=pending,
    )
    return storage, digest, learning, criteria, pending, notifier


def _seed_campaign(storage, *, with_posting=True):
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    if with_posting:
        pid = JobPostingId(new_id())
        storage.postings.add(
            JobPosting(
                id=pid,
                campaign_id=cid,
                title="Senior Python Engineer",
                company="Acme",
                source_url="https://acme.test/job",
                work_mode="remote",
                description="python fastapi",
                source_key="jobspy:indeed",
            )
        )
    storage.commit()
    return cid


def test_deliver_builds_payloads_and_pings_discord():
    storage, digest, *_ , notifier = _wire()
    cid = _seed_campaign(storage)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    result = digest.deliver(cid, crit)
    assert result["payload"]["rows"], "viable role should be in the digest"
    assert result["email"]["html"].startswith("<h1>")
    # Discord-ready ping queued (FR-DIG-2).
    assert result["notify_handle"]
    # Each viable row materializes a pending digest-approval (FR-UI-3).
    assert any(a.kind == "digest_approval" for a in storage.pending_actions.list_open(cid))


def test_deliver_sends_email_body_to_email_channel():
    # FR-DIG-2: the rendered digest email is actually SENT through the notifier's
    # email channel (not pull-only), in addition to the webpage + Discord ping.
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    # Email channel configured (apprise_urls) so the email send has a target.
    notifier = AppriseNotifier(
        discord_webhook_url="https://discord.test/wh",
        apprise_urls="mailto://user:pass@smtp.test",
    )
    learning = LearningService(storage, embedding)
    criteria = CriteriaService(storage, llm=None)
    notif_svc = NotificationService(notifier)
    pending = PendingActionsService(storage)
    scoring = ScoringService(storage, llm=None, embedding=embedding, threshold=0)
    digest = DigestService(
        storage,
        notifier,
        scoring,
        learning=learning,
        criteria=criteria,
        notification_service=notif_svc,
        pending_actions=pending,
    )
    cid = _seed_campaign(storage)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    result = digest.deliver(cid, crit)

    assert result["email_sent"] is True
    # The notifier captured an EMAIL dispatch carrying the rendered HTML body.
    email_sends = [c for c in notifier.captured() if c.channel == "email"]
    assert email_sends, "the digest email was dispatched to the email channel"
    assert email_sends[0].body == result["email"]["html"]
    assert email_sends[0].title == result["email"]["subject"]


def test_deliver_without_email_channel_does_not_send():
    # Offline-safe default lane (Discord-only notifier, no email channel): no email.
    storage, digest, *_, notifier = _wire()
    cid = _seed_campaign(storage)
    result = digest.deliver(cid)
    assert result["email_sent"] is False
    assert not [c for c in notifier.captured() if c.channel == "email"]


def test_empty_day_email_and_note():
    storage, digest, *_ = _wire()
    cid = _seed_campaign(storage, with_posting=False)
    email = digest.render_email(cid)
    assert "no new matches" in email["subject"].lower()
    payload = digest.build_digest_payload(cid)
    assert payload["empty"] and payload["note"]
    assert "Searched" in payload["note"]


def test_email_caps_rows_at_max_and_appends_portal_footer():
    # MEDIUM perf fix: a campaign with > MAX_EMAIL_ROWS viable roles must render
    # exactly MAX_EMAIL_ROWS table rows (top-N by score) + a "rest in the portal"
    # footer, never one row per role (a multi-MB email for 1000+ roles).
    from applicant.application.services.digest_service import MAX_EMAIL_ROWS

    storage, digest, *_ = _wire()
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    total = MAX_EMAIL_ROWS + 7
    for i in range(total):
        storage.postings.add(
            JobPosting(
                id=JobPostingId(new_id()),
                campaign_id=cid,
                title=f"Python Engineer {i}",
                company="Acme",
                source_url=f"https://acme.test/job/{i}",
                work_mode="remote",
                description="python fastapi",
                source_key="jobspy:indeed",
                # Distinct scores so the top-N ordering is well-defined.
                viability_score=float(i),
            )
        )
    storage.commit()
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))

    payload = digest.build_digest_payload(cid, crit)
    assert len(payload["rows"]) == total, "the payload itself carries all viable rows"

    email = digest.render_email(cid, crit, payload=payload)
    # Exactly MAX_EMAIL_ROWS <tr> data rows (the header row has <th>, not <td>).
    data_rows = email["html"].count("<tr><td>")
    assert data_rows == MAX_EMAIL_ROWS
    # Footer points at the portal for the remaining roles.
    assert "view the remaining 7 in the portal" in email["html"]
    assert f"top {MAX_EMAIL_ROWS} of {total}" in email["html"]


def test_email_no_footer_when_under_cap():
    # At/under the cap there is no truncation footer and every row renders.
    from applicant.application.services.digest_service import MAX_EMAIL_ROWS

    storage, digest, *_ = _wire()
    cid = _seed_campaign(storage)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    email = digest.render_email(cid, crit)
    assert email["html"].count("<tr><td>") == 1
    assert "in the portal" not in email["html"]
    assert str(MAX_EMAIL_ROWS) not in email["html"] or "top" not in email["html"]


def test_decline_round_trips_into_learning_and_criteria():
    storage, digest, learning, criteria, _pending, _ = _wire()
    cid = _seed_campaign(storage, with_posting=False)
    # Seed criteria so the learned adjustment can persist.
    criteria.edit_criteria(cid, changes={"keywords": ["python"]})
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(id=aid, campaign_id=cid, posting_id=JobPostingId(""))
    )
    storage.commit()

    digest.decline(aid, feedback_text="too junior", criteria_delta={"keywords": ["senior"]})

    # Learning model recorded the decline feedback (FR-LEARN-3).
    model = learning.load_model(cid)
    assert any("feedback" in k or k == "keywords" for k in model.feature_stats)
    # Next-run criteria biased by the structured delta (FR-DIG-5, FR-CRIT-3).
    updated = criteria.get_criteria(cid)
    assert "senior" in updated.keywords
    assert updated.learned_adjustments.get("summary")


def test_approve_expires_other_channels():
    storage, digest, *_rest, notifier = _wire()
    cid = _seed_campaign(storage, with_posting=False)
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(id=aid, campaign_id=cid, posting_id=JobPostingId(""))
    )
    storage.commit()
    # Queue an approval notification keyed by application id.
    NotificationService(notifier).notify_decision(str(aid), title="Approve?", body="role")
    key = f"decision:{aid}"
    assert notifier.is_active(key)
    digest.approve(aid)
    assert not notifier.is_active(key)


def test_acting_on_digest_item_expires_digest_ready_ping():
    # FR-NOTIF-3: the digest-ready ping is keyed per campaign (digest:<campaign_id>);
    # acting on any digest item must expire that same ping. Before the fix expiry was
    # keyed on decision:<application_id>, which never matched the ready ping's key.
    storage, digest, *_rest, notifier = _wire()
    notif_svc = NotificationService(notifier)
    cid = _seed_campaign(storage, with_posting=False)
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(id=aid, campaign_id=cid, posting_id=JobPostingId(""))
    )
    storage.commit()

    # The "your digest is ready" ping is now pending for this campaign.
    notif_svc.notify_digest_ready(str(cid), count=1)
    ready_key = f"digest:{cid}"
    assert notifier.is_active(ready_key)

    # Acting on a digest item (approve) expires the campaign's ready ping.
    digest.approve(aid)
    assert not notifier.is_active(ready_key)


def test_approve_decline_promote_a_posting_to_an_application():
    """FR-DIG-3 regression: the digest surfaces POSTINGS, so the front-door
    approve/decline sends a posting id. The decision needs a real application row
    (its FK) — a not-yet-pursued posting must be promoted, not FK-crash (500)."""
    storage, digest, *_rest = _wire()
    cid = _seed_campaign(storage, with_posting=True)
    posting = storage.postings.list_for_campaign(cid)[0]

    # Approve a raw posting id: promotes it to an APPROVED application + records the
    # decision (no FK violation).
    dec = digest.approve(posting.id)
    apps = storage.applications.list_for_campaign(cid)
    assert any(a.id == dec.application_id and a.posting_id == posting.id for a in apps)
    approved = next(a for a in apps if a.id == dec.application_id)
    assert approved.status.value == "APPROVED"

    # A second posting declined: promotes to a DECLINED application terminal.
    pid2 = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(id=pid2, campaign_id=cid, title="Staff Eng", company="Cobalt",
                   source_url="https://cobalt.test/job")
    )
    storage.commit()
    dec2 = digest.decline(pid2, feedback_text="not remote enough")
    declined = next(a for a in storage.applications.list_for_campaign(cid) if a.posting_id == pid2)
    assert declined.status.value == "DECLINED"
    assert dec2.application_id == declined.id

    # An unknown id (neither posting nor application) is a clean 404, not a 500.
    import pytest as _pytest

    from applicant.core.errors import NotFound
    with _pytest.raises(NotFound):
        digest.approve("no-such-id")


# === #13: deliver builds + scores the digest ONCE per delivery =============
import pytest  # noqa: E402


@pytest.mark.unit
def test_deliver_scores_each_posting_once_per_delivery():
    """#13: deliver builds + scores the full set ONCE (it used to build the payload
    AND have render_email re-build it, scoring every posting twice per delivery)."""
    storage = InMemoryStorage()
    embedding = LocalEmbedding()
    notifier = AppriseNotifier(discord_webhook_url="https://discord.test/wh")
    notif_svc = NotificationService(notifier)
    pending = PendingActionsService(storage)
    inner = ScoringService(storage, llm=None, embedding=embedding, threshold=0)

    class _CountingScoring:
        def __init__(self, inner):
            self._inner = inner
            self.score_posting_calls = 0

        def score_posting(self, posting, criteria=None):
            self.score_posting_calls += 1
            return self._inner.score_posting(posting, criteria)

        def is_viable(self, scoring):
            return self._inner.is_viable(scoring)

    counting = _CountingScoring(inner)
    digest = DigestService(
        storage,
        notifier,
        counting,
        notification_service=notif_svc,
        pending_actions=pending,
    )
    cid = _seed_campaign(storage)  # one viable posting

    digest.deliver(cid)
    # Exactly one score per posting per delivery (was two before the fix).
    assert counting.score_posting_calls == 1


# === perf lens 03 #32: batch-materialize digest-approval pending actions ===
# ``deliver`` used to call ``PendingActionsService.digest_approval`` (i.e.
# ``materialize``) once PER viable row: one indexed ``find_open_by_dedup``
# SELECT *and* one ``commit()`` per row. ``materialize_digest_approvals``
# replaces that with ONE ``list_open`` fetch + at most ONE commit for the
# whole batch. These tests pin both behavior parity (same actions, same
# dedup semantics) and the perf property (query/commit counts).


def _seed_many_postings(storage, cid: CampaignId, n: int) -> None:
    for i in range(n):
        storage.postings.add(
            JobPosting(
                id=JobPostingId(new_id()),
                campaign_id=cid,
                title="Senior Python Engineer",
                company=f"Acme{i}",
                source_url=f"https://acme.test/job/{i}",
                work_mode="remote",
                description="python fastapi",
                source_key="jobspy:indeed",
            )
        )
    storage.commit()


@pytest.mark.unit
def test_deliver_materializes_one_pending_action_per_viable_row_batched():
    """Behavior parity: batching still produces one digest_approval pending
    action per viable posting, with the same title/payload shape the old
    per-row ``digest_approval`` call produced."""
    storage, digest, *_, pending, notifier = _wire()
    cid = _seed_campaign(storage, with_posting=False)
    _seed_many_postings(storage, cid, 5)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))

    digest.deliver(cid, crit)

    actions = [
        a for a in storage.pending_actions.list_open(cid) if a.kind == "digest_approval"
    ]
    assert len(actions) == 5
    for a in actions:
        assert a.application_id is None
        assert a.title.startswith("Review: ")
        assert set(a.payload) == {"posting_id", "link", "score", "dedup_key"}
        assert a.payload["dedup_key"] == f"digest_approval:{a.payload['posting_id']}"


@pytest.mark.unit
def test_materialize_digest_approvals_batches_into_one_query_and_commit(monkeypatch):
    """Perf property (#32): N viable rows cost ONE ``list_open`` fetch and ONE
    ``commit`` for the whole batch, not N dedup SELECTs + N commits.

    Exercises ``PendingActionsService.materialize_digest_approvals`` directly
    (the exact method ``deliver`` now calls) rather than through
    ``digest.deliver()``: the full delivery pipeline also persists a scoring
    cache entry per NEWLY-scored posting (``ScoringService._persist_score``,
    its own pre-existing per-posting commit, unrelated to and unchanged by
    this fix), which would otherwise swamp the count this test pins.

    ``event_bus.emit`` is stubbed out too: the shared, process-wide
    ``DomainEventBus`` singleton can carry subscribers registered by unrelated
    tests that built a full app (e.g. the audit log service, which persists +
    commits per event) when the suite runs in one worker process — orthogonal
    to what this test measures.
    """
    import applicant.application.services.pending_actions_service as pas_module

    storage = InMemoryStorage()
    pending = PendingActionsService(storage)
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    storage.commit()

    monkeypatch.setattr(pas_module.event_bus, "emit", lambda *a, **kw: None)

    real_list_open = storage.pending_actions.list_open
    real_find_dedup = storage.pending_actions.find_open_by_dedup
    real_commit = storage.commit
    counts = {"list_open": 0, "find_dedup": 0, "commit": 0}

    def _counting_list_open(*a, **kw):
        counts["list_open"] += 1
        return real_list_open(*a, **kw)

    def _counting_find_dedup(*a, **kw):
        counts["find_dedup"] += 1
        return real_find_dedup(*a, **kw)

    def _counting_commit(*a, **kw):
        counts["commit"] += 1
        return real_commit(*a, **kw)

    monkeypatch.setattr(storage.pending_actions, "list_open", _counting_list_open)
    monkeypatch.setattr(storage.pending_actions, "find_open_by_dedup", _counting_find_dedup)
    monkeypatch.setattr(storage, "commit", _counting_commit)

    rows = [
        {
            "posting_id": f"p{i}",
            "summary": f"Role {i}",
            "link": f"https://x.test/{i}",
            "viability_score": 80,
        }
        for i in range(8)
    ]
    pending.materialize_digest_approvals(cid, rows)

    assert counts["list_open"] == 1, "should fetch open actions ONCE for the whole batch"
    assert counts["find_dedup"] == 0, "batch path must not fall back to per-row dedup SELECTs"
    assert counts["commit"] == 1, "should commit ONCE for the whole batch, not once per row"

    open_actions = [a for a in real_list_open(cid) if a.kind == "digest_approval"]
    assert len(open_actions) == 8, "all rows still materialized despite the shared commit"


@pytest.mark.unit
def test_deliver_twice_does_not_duplicate_pending_actions_dedup_preserved():
    """Re-delivering the same digest (a re-driven delivery, or a second poll
    before the day rolls) must not create duplicate pending actions — the
    batch path's dedup must match the old per-row dedup exactly (same key,
    same open/unresolved scope)."""
    storage, digest, *_, pending, notifier = _wire()
    cid = _seed_campaign(storage, with_posting=False)
    _seed_many_postings(storage, cid, 3)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))

    digest.deliver(cid, crit)
    first_ids = {
        a.id for a in storage.pending_actions.list_open(cid) if a.kind == "digest_approval"
    }
    assert len(first_ids) == 3

    digest.deliver(cid, crit)  # re-deliver the identical digest
    second_ids = {
        a.id for a in storage.pending_actions.list_open(cid) if a.kind == "digest_approval"
    }
    assert second_ids == first_ids, "re-delivery must reuse the existing actions, not duplicate"


@pytest.mark.unit
def test_deliver_after_resolving_one_row_only_recreates_the_resolved_one():
    """If the user already resolved one row's pending action, a re-delivery
    must recreate ONLY that one — ``find_open_by_dedup``/``list_open`` only
    match OPEN (unresolved) actions, and the batch path must preserve that."""
    storage, digest, *_, pending, notifier = _wire()
    cid = _seed_campaign(storage, with_posting=False)
    _seed_many_postings(storage, cid, 3)
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))

    digest.deliver(cid, crit)
    actions = [
        a for a in storage.pending_actions.list_open(cid) if a.kind == "digest_approval"
    ]
    assert len(actions) == 3
    resolved_dedup_key = actions[0].payload["dedup_key"]
    storage.pending_actions.resolve(actions[0].id)
    storage.commit()

    digest.deliver(cid, crit)  # re-deliver: the resolved one's dedup key is free again
    open_after = [
        a for a in storage.pending_actions.list_open(cid) if a.kind == "digest_approval"
    ]
    assert len(open_after) == 3
    untouched_before = {a.id for a in actions[1:]}
    untouched_after = {
        a.id for a in open_after if a.payload["dedup_key"] != resolved_dedup_key
    }
    assert untouched_after == untouched_before
    recreated = [a for a in open_after if a.payload["dedup_key"] == resolved_dedup_key]
    assert len(recreated) == 1
    assert recreated[0].id != actions[0].id
