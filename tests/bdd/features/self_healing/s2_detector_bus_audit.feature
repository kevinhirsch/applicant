# Slice S2 — Detector event bus + audit store. docs/stories/self-healing.md#s2-detector-event-bus--audit-store
# Grounds: src/applicant/core/events.py (DomainEventBus), src/applicant/application/services/
# audit_log_service.py (AuditLogService, _ACTION_MAP), src/applicant/app/lifespan.py (BootHealth,
# extended from boot-once to periodic).
#
# NOT YET WIRED — see epic_self_healing.feature header for the collection/@pending convention.

Feature: Detector events flow onto the audit trail

  @pending
  Scenario: A detector event is persisted as an audit entry
    Given a ScorerDegradedDetected event is emitted on the domain event bus
    When AuditLogService processes it
    Then an ActionEvent with action "detector_fired" appears in the audit trail
    And it is visible on the existing audit panel

  @pending
  Scenario: Runtime invariants are checked continuously, not just at boot
    Given a runtime invariant already checked once at boot, such as a model endpoint's reachability
    When the periodic watchdog tick runs
    Then its BootHealth-style status is refreshed
    And a status change from healthy to degraded, or back, emits a detector event

  @pending
  Scenario: A remediation outcome is audited and linked to its trigger
    Given a remediation action completes, successfully or not
    When its outcome is recorded
    Then a paired ActionEvent captures the outcome
    And it references the originating detector event
