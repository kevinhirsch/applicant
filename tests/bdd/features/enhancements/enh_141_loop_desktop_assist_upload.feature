# Issue #141 — FR-CUA / FR-RESUME-4 — application/services/prefill_service.py
# The autonomous pre-fill loop should self-use desktop assist to clear an off-page
# native file-upload dialog the browser DOM can't reach. This already SHIPS: when an
# attach control raises NativeFilePickerRequired the loop completes the picker via the
# ComputerUsePort (focus_app -> type path -> confirm), strictly bounded to the file
# attach and going through the FR-CUA core guards. The residual gap (other off-page
# windows: "open with" / print-to-PDF dialogs) is still human hand-off, so that stays
# @pending.

Feature: The autonomous loop clears native file-upload dialogs with desktop assist

  Scenario: The loop completes a native file picker using the bounded desktop vocabulary
    Given a pre-fill loop with an operable desktop-assist backend
    When a résumé attach step opens a native file-open dialog the browser cannot satisfy
    Then the loop focuses the dialog, types the file path, and confirms — nothing more

  Scenario: Desktop assist never crosses the pre-fill stop-boundary
    Given an operable desktop-assist backend
    When a desktop action is asked to perform a final submit
    Then the action is refused by the core stop-boundary

  Scenario: A credential value is never typed onto the desktop
    Given an operable desktop-assist backend
    When the desktop is asked to type a value flagged as a secret
    Then typing the secret is refused

  Scenario: The loop degrades to human hand-off when desktop assist is not operable
    Given a pre-fill loop with only the no-op desktop backend
    When a résumé attach step opens a native file-open dialog
    Then the loop does not attempt any desktop action and leaves the step for a human

  @pending
  Scenario: The loop clears a non-file off-page dialog with desktop assist
    Given a pre-fill loop with an operable desktop-assist backend
    When the page opens an "open with" / print-to-PDF dialog the browser cannot reach
    Then the loop delegates that off-page step to desktop assist as well
