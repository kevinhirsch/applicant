"""EPIC MODEL-CONFIG — the pure per-use-case model/endpoint catalog (domain).

This is domain metadata: the enumerable set of LLM *use cases* the operator can bind
to a model/endpoint, plus the binding-mode vocabulary. It lives in ``core`` (pure, no
outward imports) so BOTH the ``application`` layer (``SetupService`` binding
validation/resolution) and the ``app`` layer (``config``/routers rendering the Settings
surface) can import it without crossing a hexagonal boundary.

MODEL-CONFIG principle (docs/APPLICANT-BACKLOG.md §EPIC MODEL-CONFIG): there is NO
hardcoded model/endpoint decision — every use case here is bindable to local OR any
OpenAI-compatible endpoint via the EXISTING ``ModelEndpointService`` + tier ladder.
This catalog is metadata only; it never itself calls a model. Fresh-install safety:
a use case with no stored binding walks the shared tier ladder, so the app works with
zero config. ``preset_model`` is the *documented recommendation* surfaced in the UI
(the ``app`` layer overlays env-overridable presets on top); it never forces a
specific endpoint to exist.
"""

from __future__ import annotations

from dataclasses import dataclass

# Grouping keys for the Settings UI (purely cosmetic ordering/sectioning).
LLM_USE_CASE_GROUP_SCORING = "scoring"
LLM_USE_CASE_GROUP_DRAFTING = "drafting"
LLM_USE_CASE_GROUP_RESEARCH = "research"
LLM_USE_CASE_GROUP_CHAT = "chat"
LLM_USE_CASE_GROUP_EMBEDDINGS = "embeddings"
LLM_USE_CASE_GROUP_AGENTS = "agents"
LLM_USE_CASE_GROUP_SYSTEM = "system"

# A binding's ``mode``: walk the configured tier ladder as-is, or pin a saved model
# endpoint (by id) + a chosen model as the PRIMARY tier (the ladder is still appended
# below it as fallback — the ladder is never forked/replaced).
LLM_BINDING_MODE_DEFAULT = "default"
LLM_BINDING_MODE_ENDPOINT = "endpoint"
LLM_BINDING_MODES = (LLM_BINDING_MODE_DEFAULT, LLM_BINDING_MODE_ENDPOINT)


@dataclass(frozen=True)
class LLMUseCase:
    """One enumerable LLM call site the operator can bind to a model/endpoint.

    ``key`` is the stable id persisted in a binding record; ``preset_target`` is a
    coarse ``local``/``cloud`` hint for the UI; ``preset_model`` is the documented
    recommended model name (surfaced, never forced). ``task_type`` matches the smart
    router's ``TaskType`` axis (kept as a plain string here so this module stays
    dependency-free) so a bound use case still routes coherently.
    """

    key: str
    label: str
    group: str
    task_type: str
    preset_target: str  # "local" | "cloud"
    preset_model: str
    description: str = ""


#: The canonical, ordered use-case catalog. Extend this (append-only) as new LLM call
#: sites appear — the Settings surface and the binding resolver both read it, so a new
#: use case is configurable the moment it is listed here.
LLM_USE_CASES: tuple[LLMUseCase, ...] = (
    LLMUseCase(
        key="scoring",
        label="Job scoring",
        group=LLM_USE_CASE_GROUP_SCORING,
        task_type="reasoning",
        preset_target="local",
        preset_model="",  # "" = whatever the local ladder tier serves (local qwen)
        description="Viability scoring of discovered postings.",
    ),
    LLMUseCase(
        key="drafting_cover_letter",
        label="Cover-letter drafting",
        group=LLM_USE_CASE_GROUP_DRAFTING,
        task_type="creative",
        preset_target="cloud",
        preset_model="deepseek-v4-flash",
        description="Generating tailored cover letters.",
    ),
    LLMUseCase(
        key="drafting_screening",
        label="Screening-answer drafting",
        group=LLM_USE_CASE_GROUP_DRAFTING,
        task_type="creative",
        preset_target="cloud",
        preset_model="deepseek-v4-flash",
        description="Drafting application screening-question answers.",
    ),
    LLMUseCase(
        key="drafting_resume",
        label="Résumé-variant drafting",
        group=LLM_USE_CASE_GROUP_DRAFTING,
        task_type="creative",
        preset_target="cloud",
        preset_model="deepseek-v4-flash",
        description="Tailoring a résumé variant to a posting.",
    ),
    LLMUseCase(
        key="research",
        label="Research / enrichment",
        group=LLM_USE_CASE_GROUP_RESEARCH,
        task_type="summarization",
        preset_target="local",
        preset_model="",
        description="Company/role research and enrichment.",
    ),
    LLMUseCase(
        key="chat",
        label="Campaign chat",
        group=LLM_USE_CASE_GROUP_CHAT,
        task_type="chat",
        preset_target="local",
        preset_model="",
        description="The interactive campaign assistant.",
    ),
    LLMUseCase(
        key="embeddings",
        label="Embeddings",
        group=LLM_USE_CASE_GROUP_EMBEDDINGS,
        task_type="embedding",
        preset_target="local",
        preset_model="",
        description="Vector embeddings for memory/matching.",
    ),
    LLMUseCase(
        key="summarization",
        label="Summarization",
        group=LLM_USE_CASE_GROUP_SYSTEM,
        task_type="summarization",
        preset_target="local",
        preset_model="",
        description="Context compression and digests.",
    ),
    LLMUseCase(
        key="reflection_coach",
        label="Reflection Coach",
        group=LLM_USE_CASE_GROUP_AGENTS,
        task_type="reasoning",
        preset_target="local",
        preset_model="",
        description="The strategic self-improvement agent (EPIC AGENTS).",
    ),
    LLMUseCase(
        key="automation_engineer",
        label="Automation Engineer",
        group=LLM_USE_CASE_GROUP_AGENTS,
        task_type="code",
        preset_target="local",
        preset_model="",
        description="The self-healing/automation agent (EPIC AGENTS).",
    ),
)

#: Fast lookup by key (validation + resolution).
LLM_USE_CASES_BY_KEY: dict[str, LLMUseCase] = {uc.key: uc for uc in LLM_USE_CASES}


def llm_use_case_keys() -> tuple[str, ...]:
    """The set of valid use-case keys (used to validate a binding request)."""
    return tuple(uc.key for uc in LLM_USE_CASES)
