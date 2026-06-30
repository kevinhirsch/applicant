# Issue #191 — No rejection detection (no IMAP/Gmail/ATS status polling) — FR-LEARN-2
# The system can detect email-verification gates and send outbound notices, but has no
# inbound mailbox scanning or ATS status polling to detect rejections. PENDING — the
# rejection-detection seam does not exist.

Feature: Rejection notices are detected so negative outcomes feed learning

  Scenario: A rejection email is classified as a rejection outcome
    Given an inbound rejection notice for a submitted application
    When the rejection detector scans the mailbox
    Then the application is marked rejected and the negative outcome is recorded

  Scenario: An ATS status page showing no-longer-under-consideration is detected
    Given an application whose ATS status page reads no longer under consideration
    When the status poller checks the application status page
    Then the application is marked rejected
