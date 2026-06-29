# Issue #179 — FR-CUA — adapters/sandbox/computer_use/* + dormant.py + docker/webtop-chrome
# Desktop assist is fully wired (ports, guards, stop-boundary, proxy routes, dormant
# registry entry desktop_assist=live) but runtime capability-gated: it only becomes
# operable when COMPUTER_USE_BACKEND=cua AND the cua-driver binary is baked into the
# sandbox image (INSTALL_CUA_DRIVER=1). With the default noop backend the toggle renders
# locked. The capability gate (noop => not operable; missing driver => health fails; the
# registry advertises it as wired-but-capability-gated) is GREEN-testable. Actually using
# it needs the baked image, which stays @pending/integration.

Feature: Desktop assist is wired end-to-end but capability-gated on the sandbox image bake

  Scenario: The default backend selection is the no-op desktop backend
    Given no desktop backend is configured
    When the computer-use adapter is selected
    Then the no-op desktop backend is selected

  Scenario: The no-op backend reports itself as not a real desktop
    Given the no-op desktop backend
    When its health preflight is read
    Then it is healthy but reports the no-op backend, so the surface stays locked

  Scenario: The cua backend with a missing driver fails its preflight as a deploy signal
    Given the cua backend selected but the driver binary missing from the image
    When its health preflight is read
    Then the preflight fails and names the missing driver as a deploy signal

  Scenario: The dormant registry advertises desktop assist as wired but capability-gated
    Given the engine's dormant-surface registry
    When the desktop-assist surface is looked up
    Then it is marked live and its notes explain the capability gate

  @pending
  @integration
  Scenario: Desktop assist becomes operable once the driver is baked into the image
    Given the cua backend with the driver baked into the sandbox image
    When its health preflight is read
    Then the preflight passes and the desktop surface is operable
