Feature: Owner impersonation requires admin privilege at the auth layer
  # Issue #267 — workspace/app.py (around lines 237-239 and 262-266)
  # When the internal token matches, X-Applicant-Owner sets the current user to any user that
  # merely EXISTS, with no admin privilege check at the auth layer. A route that only checks
  # ownership can thus be impersonated. A defense-in-depth admin gate on impersonation does not
  # exist yet → @pending probe on the intended impersonation-guard seam.

  Scenario: Impersonating another owner requires an admin context
    Given the workspace impersonation auth seam
    When the internal channel attempts to impersonate an existing non-admin owner
    Then impersonation is gated on admin privilege rather than mere user existence
