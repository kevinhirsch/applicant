Feature: Admin gate refuses remote callers in unconfigured mode
  # Issue #228 — workspace/routes/applicant_admin_routes.py / applicant_ops_routes.py _require_admin
  # In unconfigured/single-user mode _require_admin returns "" for ANY request — it has no
  # loopback check, unlike require_user which only returns "" for 127.0.0.1/::1/localhost. A
  # remote unauthenticated caller therefore passes the admin gate during setup → @pending for
  # the remote-refused fix; the loopback-allowed scenario is GREEN (today's correct behaviour).

  @pending
  Scenario: An unconfigured remote caller is refused by the admin gate
    Given the workspace admin gate in unconfigured mode
    When an unauthenticated request arrives from a remote address
    Then the admin gate refuses the remote caller

  Scenario: An unconfigured loopback caller is still allowed
    Given the workspace admin gate in unconfigured mode
    When an unauthenticated request arrives from loopback
    Then the admin gate allows the loopback caller
