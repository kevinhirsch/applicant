# Issue #264 — applicantPortal.js, applicantActivity.js, applicantUpdate.js orphaned
# A dependency trace was requested before deletion. Confirmed by static analysis: the
# served shell loads applicant modules only via <script type="module"> for Debug,
# ModelLadder, Remote, Vault and Mind (Remote pulls in Vault). None of those import
# Portal, Activity or Update; the shell mentions those three only in HTML comments, and
# there is no dynamic import() of them. So under static analysis they are unreachable.
# GREEN: prove none of the three are loaded by a script tag or imported by a loaded
# module. @pending: the cleanup acceptance criterion — the orphaned modules are gone.

Feature: Only reachable applicant modules are shipped

  Scenario: The three suspect modules are not loaded by a script tag
    Given the served workspace shell
    When the module script tags are read
    Then none of them load the portal, activity or update module

  Scenario: No loaded module statically imports the three suspect modules
    Given the applicant browser modules
    When the loaded modules are scanned for imports of the three suspect modules
    Then none of them import the portal, activity or update module

  @pending
  Scenario: The orphaned applicant modules have been removed
    Given the applicant browser modules
    Then the orphaned portal, activity and update modules no longer exist
