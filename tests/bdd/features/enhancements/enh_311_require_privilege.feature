Feature: Privilege gate defaults to deny for unknown keys
  # Issue #311 — workspace/src/auth_helpers.py require_privilege
  # Today a missing privilege key defaults to PERMITTED (privs.get(key, True)),
  # so a future typo or a new key silently grants a restricted sub-user access.
  # The known-key denial is GREEN regression coverage; the unknown-key default-deny
  # is @pending until require_privilege fails closed with an explicit allow-list.

  Scenario: A known privilege explicitly set to false is denied
    Given a sub-user whose known privilege is set to false
    When a route guarded by that privilege is called
    Then access is refused with a 403

  Scenario: An unknown privilege key defaults to deny
    Given a sub-user whose privilege map does not contain a requested key
    When a route guarded by that unknown key is called
    Then access is refused rather than silently granted
