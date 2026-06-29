Feature: The deploy script does not pass the DB password on the command line
  # Issue #280 — scripts/proxmox-deploy.sh (around line 188)
  # The provisioner invokes install.sh with POSTGRES_PASSWORD="${DB_PASS}" inline on the command
  # line, so the password is visible in /proc/<pid>/cmdline, /proc/<pid>/environ and ps aux to
  # any local user. Writing the secret to .env before invoking install.sh (rather than inline)
  # is not done yet → @pending probe on the deploy script.

  @pending
  Scenario: The DB password is not exposed on the install command line
    Given the Proxmox deploy script
    When the database-install invocation is inspected
    Then the database password is not passed inline on the install command line
