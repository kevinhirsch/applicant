Feature: Panels discard stale responses on a fast campaign/tab switch
  # Issue #387 — workspace/static/js/applicantDebug.js:134 / emailLibrary/applicantDigest.js:813 / applicantRemote.js:185
  # Requirement: Panels that re-render on a selector/tab change MUST stamp an incrementing request token (or AbortController) and discard/abort stale responses before writing the DOM.

  Scenario: The Run-controls in-flight disable shows the deliberate-sequencing pattern already lives here
    Given the Activity/Debug browser module
    When the Run-now and Pause click handlers are inspected
    Then each disables its button while the request is in flight and re-enables it afterwards

  Scenario: A late response for a deselected campaign cannot overwrite the current view
    Given the Applicant panel browser modules
    When the re-render paths are scanned for a stale-response guard
    Then a request token or AbortController gates the DOM write so a stale response is discarded
