Feature: Internationalized field parsing in the engine
  # Issue #194 — core/rules/field_normalization.py, sensitive_fields.py, chat_service.py
  # Phone/salary/EEO/ATS parsing is US/English-centric and there is no translation
  # framework. The US-only behaviour is GREEN regression; a non-US phone normalized
  # without mangling, and any i18n framework, are the gaps (@pending).

  Scenario: A North-American number normalizes by dropping the +1 country code
    Given the phone-normalization core rule
    When a US number written with its +1 country code is normalized
    Then it reduces to the bare ten-digit national number

  @pending
  Scenario: An international number keeps its country code intact
    Given the phone-normalization core rule
    When a UK number written with its +44 country code is normalized
    Then the country code is preserved rather than mangled

  @pending
  Scenario: A translation framework backs user-facing parsing
    Given the engine parsing layer
    When a localization framework is looked up
    Then a translation backend is available so parsing is not English-only
