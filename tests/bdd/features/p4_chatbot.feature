Feature: Assistant chatbot proposes confirmation-gated changes
  # master spec §10 / §3.20 — FR-CHAT-1, FR-FB-2, FR-FB-3

  Scenario: The chatbot identifies gaps in the attribute cloud
    Given a chatbot for an empty campaign
    When the user sends "hello"
    Then the chatbot reports the missing core attributes

  Scenario: The chatbot proposes an integral change but never auto-commits it
    Given a chatbot for an empty campaign
    When the user states an integral attribute value
    Then the chatbot proposes the change requiring confirmation
    And the change is not committed until the user confirms

  Scenario: The chatbot auto-applies a non-integral attribute
    Given a chatbot for an empty campaign
    When the user states a non-integral attribute value
    Then the chatbot applies the change immediately
