"""Pure domain entities (master spec §6). Frozen dataclasses, no I/O.

One module per entity. These hold state and (where applicable) defer rule
enforcement to ``applicant.core.rules`` / ``applicant.core.state_machine``.
"""

from applicant.core.entities.action_event import ActionEvent
from applicant.core.entities.agent_intent import AgentIntent
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import Attribute, AttributeStore
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.decision import Decision, DecisionType
from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.entities.generated_document import (
    DocumentType,
    GeneratedDocument,
)
from applicant.core.entities.job_posting import JobPosting
from applicant.core.entities.learning_model import LearningModel
from applicant.core.entities.onboarding_profile import OnboardingProfile
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.resume_variant import ResumeFitScoring, ResumeVariant
from applicant.core.entities.revision_session import RevisionSession
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.entities.viability_scoring import ViabilityScoring

__all__ = [
    "ActionEvent",
    "AgentIntent",
    "Application",
    "Attribute",
    "AttributeStore",
    "Campaign",
    "Decision",
    "DecisionType",
    "DetectionEvent",
    "DocumentType",
    "GeneratedDocument",
    "JobPosting",
    "LearningModel",
    "OnboardingProfile",
    "OutcomeEvent",
    "OutcomeSource",
    "PendingAction",
    "ResumeFitScoring",
    "ResumeVariant",
    "RevisionSession",
    "SearchCriteria",
    "ViabilityScoring",
]
