# Helper script to apply G16 updates to in_memory.py
import pathlib

p = pathlib.Path("src/applicant/adapters/storage/in_memory.py")
t = p.read_text()

# Add new entity imports
t = t.replace(
    "from applicant.core.entities.attribute import Attribute",
    "from applicant.core.entities.attribute import Attribute\n"
    "from applicant.core.entities.follow_up import FollowUp, FollowUpStatus\n"
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

# Add in-memory repo classes before InMemoryStorage
repos_code = """

class _SubmissionSnapshotRepo:
    def __init__(self, applications): self._d = {}; self._applications = applications
    def add(self, s): self._d[str(s.id)] = s
    def get(self, sid): return self._d.get(str(sid))
    def get_for_application(self, aid): return next((s for s in self._d.values() if s.application_id == aid), None)
    def list_for_campaign(self, cid): return [s for s in self._d.values() if (a := self._applications.get(s.application_id)) and a.campaign_id == cid]
    def delete_for_application(self, aid): return bool(sum(1 for k in list(self._d.keys()) if self._d[k].application_id == aid and self._d.pop(k, None) or 0))
    def delete_for_applications(self, aids): return sum(1 for k in list(self._d.keys()) if str(self._d[k].application_id) in aids and self._d.pop(k, None) or 0)

class _RejectionSignalRepo:
    def __init__(self, applications): self._l = []; self._applications = applications
    def add(self, s): self._l.append(s)
    def list_for_application(self, aid): return sorted([s for s in self._l if s.application_id == aid], key=lambda s: s.detected_at)
    def list_for_campaign(self, cid): return sorted([s for s in self._l if (a := self._applications.get(s.application_id)) and a.campaign_id == cid], key=lambda s: s.detected_at)
    def delete_for_applications(self, aids): n = len(self._l); self._l = [s for s in self._l if str(s.application_id) not in aids]; return n - len(self._l)

class _GhostingSignalRepo:
    def __init__(self, applications): self._l = []; self._applications = applications
    def add(self, s): self._l.append(s)
    def list_for_application(self, aid): return sorted([s for s in self._l if s.application_id == aid], key=lambda s: s.detected_at)
    def list_for_campaign(self, cid): return sorted([s for s in self._l if s.campaign_id == cid], key=lambda s: s.detected_at)
    def delete_for_applications(self, aids): n = len(self._l); self._l = [s for s in self._l if str(s.application_id) not in aids]; return n - len(self._l)

class _FollowUpRepo:
    def __init__(self, applications): self._d = {}; self._applications = applications
    def add(self, f): self._d[str(f.id)] = f
    def get(self, fid): return self._d.get(str(fid))
    def list_for_application(self, aid): return sorted([f for f in self._d.values() if f.application_id == aid], key=lambda f: f.created_at)
    def list_for_campaign(self, cid): return sorted([f for f in self._d.values() if (a := self._applications.get(f.application_id)) and a.campaign_id == cid], key=lambda f: f.created_at)
    def list_due(self, now): return sorted([f for f in self._d.values() if f.scheduled_at and f.scheduled_at <= now and f.status == FollowUpStatus.SCHEDULED], key=lambda f: f.scheduled_at)
    def delete_for_applications(self, aids): return sum(1 for k in list(self._d.keys()) if str(self._d[k].application_id) in aids and self._d.pop(k, None) or 0)

class _PortfolioAttachmentRepo:
    def __init__(self, applications): self._d = {}; self._applications = applications
    def add(self, a): self._d[str(a.id)] = a
    def get(self, aid): return self._d.get(str(aid))
    def list_for_application(self, aid): return sorted([a for a in self._d.values() if a.application_id == aid], key=lambda a: a.created_at)
    def list_for_campaign(self, cid): return sorted([a for a in self._d.values() if a.application_id and (app := self._applications.get(a.application_id)) and app.campaign_id == cid], key=lambda a: a.created_at)
    def delete(self, aid): return self._d.pop(str(aid), None) is not None
    def delete_for_application(self, aid): return sum(1 for k in list(self._d.keys()) if self._d[k].application_id == aid and self._d.pop(k, None) or 0)
    def delete_for_applications(self, aids): return sum(1 for k in list(self._d.keys()) if str(self._d[k].application_id) in aids and self._d.pop(k, None) or 0)
"""

t = t.replace("class InMemoryStorage:", repos_code + "\nclass InMemoryStorage:")

# Wire new repos into InMemoryStorage.__init__
t = t.replace(
    "        self.onboarding_profiles = _OnboardingProfileRepo()",
    "        self.onboarding_profiles = _OnboardingProfileRepo()\n"
    "        self.submission_snapshots = _SubmissionSnapshotRepo(self.applications)\n"
    "        self.rejection_signals = _RejectionSignalRepo(self.applications)\n"
    "        self.ghosting_signals = _GhostingSignalRepo(self.applications)\n"
    "        self.follow_ups = _FollowUpRepo(self.applications)\n"
    "        self.portfolio_attachments = _PortfolioAttachmentRepo(self.applications)"
)

# Add G16 tables to purge_campaign
purge_old = '            "detection_events": self.detection_events.delete_for_applications(app_ids),'
purge_new = '''            "detection_events": self.detection_events.delete_for_applications(app_ids),
            "submission_snapshots": self.submission_snapshots.delete_for_applications(app_ids),
            "rejection_signals": self.rejection_signals.delete_for_applications(app_ids),
            "ghosting_signals": self.ghosting_signals.delete_for_applications(app_ids),
            "follow_ups": self.follow_ups.delete_for_applications(app_ids),
            "portfolio_attachments": self.portfolio_attachments.delete_for_applications(app_ids),'''
t = t.replace(purge_old, purge_new)

p.write_text(t)
print("in_memory.py done")
