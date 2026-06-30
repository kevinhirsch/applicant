Feature: CaptchaSolverPort — opt-in, safe-by-default CAPTCHA handling
  # Issue #350 (Skyvern-parity epic #351) — ties to plan-as-data #305
  # Two beasts, opposite tactics: score/behavioral systems (reCAPTCHA v3,
  # Turnstile) are AVOIDED by looking human (camoufox fingerprint + cadence —
  # shipped); challenge systems (reCAPTCHA v2, hCaptcha) are solved by token
  # injection via a solver service. Human hand-off stays the default + backstop.
  # The behavioral-avoidance leg is GREEN (it leans on shipped stealth); the
  # solver port + adapters are @pending until built.

  Scenario: Behavioral avoidance presents a coherent browser fingerprint
    Given the shipped stealth layer
    When a fingerprint is generated for the Chrome channel
    Then the fingerprint is internally coherent so score-based systems are less likely to challenge

  Scenario: Behavioral avoidance paces input like a human
    Given the shipped stealth layer with a seeded clock
    When a value is typed through the human-cadence planner
    Then each keystroke carries a positive human-like dwell and the logical clock advances

  Scenario: The solver port classifies a CAPTCHA as score-based or challenge-based
    Given a CAPTCHA detected on a page
    When the solver port inspects it
    Then it is classified as score-based (avoid) or challenge-based (solve)

  Scenario: A challenge CAPTCHA is solved by token injection via the solver service
    Given a challenge-based CAPTCHA with a site key
    When the solver-service adapter resolves it
    Then a response token is injected into the hidden field and the form can proceed

  Scenario: The solver API secret is never written to a log
    Given a configured solver-service adapter holding an API key
    When the adapter runs and logs its activity
    Then the API key never appears in any log line

  Scenario: With the solver off, a CAPTCHA falls back to human hand-off
    Given the CAPTCHA strategy is set to the default human hand-off
    When a CAPTCHA is encountered
    Then the run pauses and hands off to the operator rather than auto-solving

  Scenario: Solving never bypasses the final-submit stop-boundary
    Given a solved CAPTCHA mid-application
    When the plan continues past the CAPTCHA step
    Then the final submit is still withheld for human review
