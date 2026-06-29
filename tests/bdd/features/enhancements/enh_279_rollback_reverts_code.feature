Feature: A rollback reverts the code and images, not only the database
  # Issue #279 — scripts/update.sh (--rollback path)
  # --rollback restores the database dump but leaves the git checkout and Docker images at
  # the NEW version, producing a broken stack of old data + new code when the new migrations
  # already ran. A real rollback must also revert the source checkout and the images to the
  # pre-update commit/tags it snapshotted before applying changes.

  @pending
  Scenario: The rollback also reverts the source checkout and images
    Given the updater script
    When its rollback path is inspected
    Then it reverts the git checkout and the container images alongside the database
