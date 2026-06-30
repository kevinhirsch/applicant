# Issue #339 — adapters/browser/page_source.py:_on_response (PlaywrightPageSource)
#   _on_response captures the main-frame status into self._status but records no
#   timestamp, so response statuses cannot be correlated with prefill-loop steps.
# Requirement: _on_response MUST capture a timestamp alongside the response status so the
#   captured statuses can be correlated with the pre-fill action sequence when debugging.
# Related existing issue: #207 (browser-health/diagnostic instrumentation gap).
# PENDING: the status capture is timestamped (no timestamp seam exists today).

Feature: Captured response statuses carry a timestamp for correlation

  Scenario: A captured response status records when it was observed
    Given a page driver observing a navigation response
    When the response handler captures the document status
    Then the captured status entry carries a timestamp
