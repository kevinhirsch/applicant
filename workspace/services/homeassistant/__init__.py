"""Home Assistant integration (Phase 4, Applicant parity).

Pure allowlist helpers live here; the DB-backed config store and the guarded
REST client live in ``service``. All control is opt-in: gated by the
``can_control_home`` privilege and constrained to an explicit entity allowlist,
with state-changing calls classified HIGH risk by ``src.policy``.
"""

from services.homeassistant.allowlist import entity_domain, is_allowed

__all__ = ["entity_domain", "is_allowed"]
