Feature: A rollback reverts the code and images, not only the database
  # Issue #279 — scripts/update.sh (--rollback path)
  # --rollback restores the database dump but leaves the git checkout and Docker images at
  # the NEW version, producing a broken stack of old data + new code when the new migrations
  # already ran. A real rollback must also revert the source checkout and the images to the
  # pre-update commit/tags it snapshotted before applying changes.
  # The update flow now records the pre-update git commit + image IDs (applicant/*:previous),
  # and --rollback reverts the checkout (git reset --hard) and re-points the images alongside
  # the DB restore — failing loudly if the snapshot is missing → hard regression gate.

  Scenario: The rollback also reverts the source checkout and images
    Given the updater script
    When its rollback path is inspected
    Then it reverts the git checkout and the container images alongside the database
