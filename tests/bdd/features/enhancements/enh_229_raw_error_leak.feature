Feature: Engine 5xx detail is masked before reaching the browser
  # Issue #229 — workspace applicant_*_routes.py engine-error translation
  # The email route masks engine 5xx to a generic message with no raw detail (GREEN). Other
  # proxies (e.g. the documents route) still forward the engine's raw detail verbatim in the
  # response body, leaking tracebacks → @pending until they follow the email route's pattern.

  Scenario: The email proxy masks an engine server error
    Given an engine server error carrying a raw traceback
    When the email proxy translates it for the browser
    Then a generic message is returned and the raw traceback is not exposed

  @pending
  Scenario: The documents proxy masks an engine server error
    Given an engine server error carrying a raw traceback
    When the documents proxy translates it for the browser
    Then the documents response does not expose the raw traceback
