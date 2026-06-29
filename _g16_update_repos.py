# Helper script to apply G16 updates to repositories.py
import pathlib

p = pathlib.Path("src/applicant/adapters/storage/repositories.py")
t = p.read_text()

# Add new entity imports
t = t.replace(
    "from applicant.core.entities.attribute import Attribute",
    "from applicant.core.entities.attribute import Attribute\n"
    "from applicant.core.entities.follow_up import FollowUp, FollowUpStatus, FollowUpTemplate\n"
    "from applicant.core.entities.ghosting_signal import GhostingSignal\n"
    "from applicant.core.entities.portfolio_attachment import PortfolioAttachment, AttachmentType\n"
    "from applicant.core.entities.rejection_signal import RejectionSignal, RejectionSource\n"
    "from applicant.core.entities.submission_snapshot import SubmissionSnapshot"
)

t = t.replace(
    "from applicant.core.ids import (",
    "from applicant.core.ids import (\n"
    "    FollowUpId,\n"
    "    PortfolioAttachmentId,\n"
    "    RejectionSignalId,\n"
    "    SubmissionSnapshotId,"
)

# Add repo classes before OnboardingProfileRepo
repos_code = '''
def _snapshot_to_entity(row):
    return SubmissionSnapshot(id=row.id, application_id=row.application_id, answers=dict(row.answers or {}), materials=list(row.materials or []), ats_metadata=dict(row.ats_metadata or {}))

def _rejection_to_entity(row):
    return RejectionSignal(id=row.id, application_id=row.application_id, source=RejectionSource(row.source), signal_text=row.signal_text, confidence=row.confidence, detail=dict(row.detail or {}))

def _ghosting_to_entity(row):
    return GhostingSignal(campaign_id=row.campaign_id, application_id=row.application_id, sla_days=row.sla_days, submission_age_days=row.submission_age_days, detail=dict(row.detail or {}))

def _follow_up_to_entity(row):
    return FollowUp(id=row.id, campaign_id=row.campaign_id, application_id=row.application_id, template=FollowUpTemplate(row.template), status=FollowUpStatus(row.status), subject=row.subject, body=row.body, scheduled_at=row.scheduled_at, sent_at=row.sent_at)

def _attachment_to_entity(row):
    return PortfolioAttachment(id=row.id, campaign_id=row.campaign_id, application_id=row.application_id if row.application_id else None, attachment_type=AttachmentType(row.attachment_type), file_name=row.file_name, storage_path=row.storage_path, display_name=row.display_name, description=row.description, metadata=dict(row.metadata or {}))


class SubmissionSnapshotRepo:
    def __init__(self, session): self._s = session
    def add(self, s): self._s.merge(m.SubmissionSnapshotModel(id=s.id, application_id=s.application_id, answers=s.answers, materials=s.materials, ats_metadata=s.ats_metadata))
    def get(self, sid): row = self._s.get(m.SubmissionSnapshotModel, sid); return _snapshot_to_entity(row) if row else None
    def get_for_application(self, aid): row = self._s.scalars(select(m.SubmissionSnapshotModel).where(m.SubmissionSnapshotModel.application_id == aid).order_by(m.SubmissionSnapshotModel.captured_at.desc())).first(); return _snapshot_to_entity(row) if row else None
    def list_for_campaign(self, cid): rows = self._s.scalars(select(m.SubmissionSnapshotModel).join(m.ApplicationModel, m.SubmissionSnapshotModel.application_id == m.ApplicationModel.id).where(m.ApplicationModel.campaign_id == cid)).all(); return [_snapshot_to_entity(r) for r in rows]
    def delete_for_application(self, aid): return bool(self._s.query(m.SubmissionSnapshotModel).filter(m.SubmissionSnapshotModel.application_id == aid).delete(synchronize_session=False))

class RejectionSignalRepo:
    def __init__(self, session): self._s = session
    def add(self, sig): self._s.merge(m.RejectionSignalModel(id=sig.id, application_id=sig.application_id, source=sig.source.value, signal_text=sig.signal_text, confidence=sig.confidence, detail=sig.detail))
    def list_for_application(self, aid): rows = self._s.scalars(select(m.RejectionSignalModel).where(m.RejectionSignalModel.application_id == aid).order_by(m.RejectionSignalModel.detected_at)).all(); return [_rejection_to_entity(r) for r in rows]
    def list_for_campaign(self, cid): rows = self._s.scalars(select(m.RejectionSignalModel).join(m.ApplicationModel, m.RejectionSignalModel.application_id == m.ApplicationModel.id).where(m.ApplicationModel.campaign_id == cid).order_by(m.RejectionSignalModel.detected_at)).all(); return [_rejection_to_entity(r) for r in rows]

class GhostingSignalRepo:
    def __init__(self, session): self._s = session
    def add(self, sig): from applicant.core.ids import new_id; self._s.merge(m.GhostingSignalModel(id=new_id(), campaign_id=sig.campaign_id, application_id=sig.application_id, sla_days=sig.sla_days, submission_age_days=sig.submission_age_days, detail=sig.detail))
    def list_for_application(self, aid): rows = self._s.scalars(select(m.GhostingSignalModel).where(m.GhostingSignalModel.application_id == aid).order_by(m.GhostingSignalModel.detected_at)).all(); return [_ghosting_to_entity(r) for r in rows]
    def list_for_campaign(self, cid): rows = self._s.scalars(select(m.GhostingSignalModel).where(m.GhostingSignalModel.campaign_id == cid).order_by(m.GhostingSignalModel.detected_at)).all(); return [_ghosting_to_entity(r) for r in rows]

class FollowUpRepo:
    def __init__(self, session): self._s = session
    def add(self, f): self._s.merge(m.FollowUpModel(id=f.id, campaign_id=f.campaign_id, application_id=f.application_id, template=f.template.value, status=f.status.value, subject=f.subject, body=f.body, scheduled_at=f.scheduled_at, sent_at=f.sent_at))
    def get(self, fid): row = self._s.get(m.FollowUpModel, fid); return _follow_up_to_entity(row) if row else None
    def list_for_application(self, aid): rows = self._s.scalars(select(m.FollowUpModel).where(m.FollowUpModel.application_id == aid).order_by(m.FollowUpModel.created_at)).all(); return [_follow_up_to_entity(r) for r in rows]
    def list_for_campaign(self, cid): rows = self._s.scalars(select(m.FollowUpModel).where(m.FollowUpModel.campaign_id == cid).order_by(m.FollowUpModel.created_at)).all(); return [_follow_up_to_entity(r) for r in rows]
    def list_due(self, now): rows = self._s.scalars(select(m.FollowUpModel).where(m.FollowUpModel.scheduled_at <= now).where(m.FollowUpModel.status == "SCHEDULED").order_by(m.FollowUpModel.scheduled_at)).all(); return [_follow_up_to_entity(r) for r in rows]

class PortfolioAttachmentRepo:
    def __init__(self, session): self._s = session
    def add(self, a): self._s.merge(m.PortfolioAttachmentModel(id=a.id, campaign_id=a.campaign_id, application_id=a.application_id, attachment_type=a.attachment_type.value, file_name=a.file_name, storage_path=a.storage_path, display_name=a.display_name, description=a.description, metadata=a.metadata))
    def get(self, aid): row = self._s.get(m.PortfolioAttachmentModel, aid); return _attachment_to_entity(row) if row else None
    def list_for_application(self, aid): rows = self._s.scalars(select(m.PortfolioAttachmentModel).where(m.PortfolioAttachmentModel.application_id == aid).order_by(m.PortfolioAttachmentModel.created_at)).all(); return [_attachment_to_entity(r) for r in rows]
    def list_for_campaign(self, cid): rows = self._s.scalars(select(m.PortfolioAttachmentModel).where(m.PortfolioAttachmentModel.campaign_id == cid).order_by(m.PortfolioAttachmentModel.created_at)).all(); return [_attachment_to_entity(r) for r in rows]
    def delete(self, aid): row = self._s.get(m.PortfolioAttachmentModel, aid); self._s.delete(row); return bool(row)
    def delete_for_application(self, aid): return int(self._s.query(m.PortfolioAttachmentModel).filter(m.PortfolioAttachmentModel.application_id == aid).delete(synchronize_session=False) or 0)
'''

t = t.replace("class OnboardingProfileRepo:", repos_code + "\nclass OnboardingProfileRepo:")

# Wire into SqlAlchemyStorage.__init__
t = t.replace(
    "        self.onboarding_profiles = OnboardingProfileRepo(session)",
    "        self.onboarding_profiles = OnboardingProfileRepo(session)\n"
    "        self.submission_snapshots = SubmissionSnapshotRepo(session)\n"
    "        self.rejection_signals = RejectionSignalRepo(session)\n"
    "        self.ghosting_signals = GhostingSignalRepo(session)\n"
    "        self.follow_ups = FollowUpRepo(session)\n"
    "        self.portfolio_attachments = PortfolioAttachmentRepo(session)"
)

# Add G16 tables to purge_campaign
purge_old = '            counts["detection_events"] = _del('
purge_new = '''            counts["detection_events"] = _del(
                m.DetectionEventModel,
                m.DetectionEventModel.application_id.in_(app_ids),
            )
            counts["submission_snapshots"] = _del(
                m.SubmissionSnapshotModel,
                m.SubmissionSnapshotModel.application_id.in_(app_ids),
            )
            counts["rejection_signals"] = _del(
                m.RejectionSignalModel,
                m.RejectionSignalModel.application_id.in_(app_ids),
            )
            counts["ghosting_signals"] = _del(
                m.GhostingSignalModel,
                m.GhostingSignalModel.application_id.in_(app_ids),
            )
            counts["follow_ups"] = _del(
                m.FollowUpModel,
                m.FollowUpModel.application_id.in_(app_ids),
            )
            counts["portfolio_attachments"] = _del(
                m.PortfolioAttachmentModel,
                m.PortfolioAttachmentModel.application_id.in_(app_ids),
            )'''
t = t.replace(purge_old, purge_new)

p.write_text(t)
print("repositories.py done")
