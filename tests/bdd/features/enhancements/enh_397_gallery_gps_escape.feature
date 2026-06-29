Feature: Image EXIF GPS coordinates are HTML-escaped in the gallery detail panel
  # Issue #397 — workspace/static/js/gallery.js:1424 (sink), GPS from attacker-supplied EXIF
  # Requirement: The front-door MUST wrap img.gps.lat / img.gps.lng in the escaping helper
  # at the gallery detail sink (defense-in-depth, matching the escaped sibling fields).

  Scenario: Sibling metadata fields in the detail panel are already escaped
    Given the gallery browser module
    When the camera, source and session detail fields are inspected
    Then each escapes its value with the escaping helper

  @pending
  Scenario: The GPS latitude and longitude are escaped at the detail sink
    Given the gallery browser module
    When the location detail interpolation is inspected
    Then the GPS latitude and longitude are escaped before interpolation
