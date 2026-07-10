"""Unit tests for Skyvern-parity gaps #3 (native calendar/date-picker) and #5
(self-healing selector recovery on the DEFAULT deterministic fill path). Issue #351.

All hermetic — no real browser. The date-picker + self-heal logic is driven against
in-memory fakes, including through ``PlaywrightPageSource.type_value`` (constructed via
``__new__`` so no browser binary is needed).

Safety-critical assertion: a self-heal recovery that would resolve to a submit /
account-create / final-submit control is REFUSED — the pre-fill stop-boundary
(``core/rules/prefill_boundary.py``) is never crossed by a retarget.
"""

from __future__ import annotations

import calendar as _calendar

import pytest

from applicant.adapters.browser.page_source import PlaywrightPageSource
from applicant.adapters.browser.skyvern_enhancements import (
    _MONTH_NAMES,
    AdaptiveWaitConfig,
    choose_date,
    heal_fill_selector,
    is_boundary_control,
    is_datepicker_element,
    parse_target_date,
)
from applicant.core.errors import PrefillBoundaryViolation

# Fast recovery config so a broken-selector test never blocks on the default ladder.
_FAST = AdaptiveWaitConfig(
    initial_timeout_s=0.02,
    max_timeout_s=0.05,
    poll_interval_s=0.01,
    max_adaptations=1,
    adapt_multiplier=2.0,
)


# ── Fake calendar widget (gap #3) ──────────────────────────────────────────


class _CalCell:
    def __init__(self, day: int, page: FakeCalendarPage, *, outside: bool = False):
        self.day = day
        self.page = page
        self.outside = outside
        self.clicked = False

    def inner_text(self) -> str:
        return str(self.day)

    def is_visible(self) -> bool:
        return True

    def get_attribute(self, name: str):
        if name == "aria-disabled":
            return "true" if self.outside else "false"
        if name == "class":
            return "day outside-month" if self.outside else "day"
        return None

    def click(self) -> None:
        self.clicked = True
        self.page.clicked_cells.append(self)


class _CalHeader:
    def __init__(self, page: FakeCalendarPage):
        self.page = page

    def inner_text(self) -> str:
        y, m = self.page.current
        return f"{_MONTH_NAMES[m]} {y}"

    def get_attribute(self, name: str):
        return None


class _CalNav:
    def __init__(self, page: FakeCalendarPage, delta: int):
        self.page = page
        self.delta = delta

    def click(self) -> None:
        y, m = self.page.current
        m += self.delta
        while m < 1:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        self.page.current = (y, m)


class _CalTrigger:
    def __init__(self, page: FakeCalendarPage):
        self.page = page

    def evaluate(self, _script: str) -> str:
        return "INPUT"  # for _is_select — a date field is not a <select>

    def get_attribute(self, name: str):
        return {
            "class": "datepicker-input",
            "data-automation-id": "startDate",
            "aria-haspopup": "dialog",
        }.get(name)

    def is_visible(self) -> bool:
        return True

    def click(self) -> None:
        self.page.opened = True


class FakeCalendarPage:
    """A hermetic model of a JS calendar date field (no typeable input)."""

    TRIGGER = "[data-automation-id='startDate']"

    def __init__(self, start=(2026, 6)):
        self.current = start
        self.opened = False
        self.clicked_cells: list[_CalCell] = []
        self._trigger = _CalTrigger(self)

    def query_selector(self, sel: str):
        if sel == self.TRIGGER:
            return self._trigger
        if not self.opened:
            return None
        if sel == ".datepicker-switch":
            return _CalHeader(self)
        if sel == ".next":
            return _CalNav(self, +1)
        if sel == ".prev":
            return _CalNav(self, -1)
        return None

    def query_selector_all(self, sel: str):
        if not self.opened or sel != "[role='gridcell']":
            return []
        y, m = self.current
        ndays = _calendar.monthrange(y, m)[1]
        # A trailing-month "7" placed FIRST: if outside-month cells were not skipped,
        # this wrong cell would be clicked instead of the target month's "7".
        cells: list[_CalCell] = [_CalCell(7, self, outside=True)]
        cells += [_CalCell(d, self) for d in range(1, ndays + 1)]
        return cells


class TestParseTargetDate:
    def test_iso(self):
        assert parse_target_date("2026-07-07") == (2026, 7, 7)

    def test_us_slash(self):
        assert parse_target_date("07/09/2026") == (2026, 7, 9)

    def test_month_name(self):
        assert parse_target_date("July 4, 2026") == (2026, 7, 4)

    def test_unparseable(self):
        assert parse_target_date("next tuesday") is None
        assert parse_target_date("2026-13-40") is None


class TestChooseDate:
    def test_navigates_forward_and_picks_day(self):
        page = FakeCalendarPage(start=(2026, 6))
        assert choose_date(page, page.TRIGGER, "2026-07-07") is True
        assert len(page.clicked_cells) == 1
        clicked = page.clicked_cells[0]
        assert clicked.day == 7
        # The IN-month "7" was clicked, not the trailing-month duplicate.
        assert clicked.outside is False

    def test_navigates_backward(self):
        page = FakeCalendarPage(start=(2026, 9))
        assert choose_date(page, page.TRIGGER, "2026-07-15") is True
        assert page.current == (2026, 7)
        assert page.clicked_cells[0].day == 15

    def test_unparseable_value_returns_false(self):
        page = FakeCalendarPage()
        assert choose_date(page, page.TRIGGER, "whenever") is False
        assert page.clicked_cells == []

    def test_unreachable_month_fails_softly_without_clicking(self):
        # Greptile #817: with no next/prev control the calendar can never leave its
        # start month, so it cannot reach the target. It MUST fail softly (return
        # False, click nothing) rather than click the matching day in the WRONG month
        # and silently record an incorrect date.
        class _NoNav(FakeCalendarPage):
            def query_selector(self, sel: str):
                if sel in (".next", ".prev"):
                    return None  # navigation impossible
                return super().query_selector(sel)

        page = _NoNav(start=(2026, 6))
        assert choose_date(page, page.TRIGGER, "2026-09-15") is False
        assert page.clicked_cells == []
        assert page.current == (2026, 6)  # never moved

    def test_type_value_fills_calendar_date_field(self):
        """A date field with a JS calendar (no typeable input) now fills via type_value."""
        src = PlaywrightPageSource.__new__(PlaywrightPageSource)
        page = FakeCalendarPage(start=(2026, 5))
        src._page = page
        # type_value routes: not <select>, IS datepicker → clicks the day cell.
        src.type_value(page.TRIGGER, "2026-07-07")
        assert len(page.clicked_cells) == 1
        assert page.clicked_cells[0].day == 7
        assert page.clicked_cells[0].outside is False


class TestIsDatepickerElement:
    class _El:
        def __init__(self, attrs):
            self._a = attrs

        def get_attribute(self, n):
            return self._a.get(n)

    def test_calendar_class(self):
        assert is_datepicker_element(self._El({"class": "react-datepicker__input"})) is True

    def test_haspopup_dialog_date_field(self):
        assert is_datepicker_element(
            self._El({"aria-haspopup": "dialog", "data-automation-id": "startDate"})
        ) is True

    def test_readonly_date_input(self):
        el = self._El({"aria-label": "Date of birth", "readonly": ""})
        assert is_datepicker_element(el) is True

    def test_plain_text_input_not_datepicker(self):
        assert is_datepicker_element(self._El({"name": "first_name", "type": "text"})) is False

    def test_native_typeable_date_not_hijacked(self):
        # A native <input type=date> (typeable) has no calendar/readonly signal → skip.
        assert is_datepicker_element(self._El({"type": "date", "name": "start"})) is False

    def test_none(self):
        assert is_datepicker_element(None) is False


# ── Self-heal / boundary guard (gap #5) ────────────────────────────────────


class _FakeEl:
    def __init__(self, attrs=None, text="", visible=True):
        self.attrs = attrs or {}
        self._text = text
        self._visible = visible

    def get_attribute(self, name):
        return self.attrs.get(name)

    def inner_text(self):
        return self._text

    def is_visible(self):
        return self._visible

    def evaluate(self, _script):
        return self.attrs.get("__tag__", "INPUT")


class FakeHealPage:
    def __init__(self, elements: dict):
        self.elements = elements
        self.filled: dict[str, str] = {}
        self.typed: dict[str, str] = {}

    def query_selector(self, sel):
        return self.elements.get(sel)

    def fill(self, sel, val):
        self.filled[sel] = val

    def type(self, sel, val, delay=0):
        self.typed[sel] = val


class TestIsBoundaryControl:
    def test_submit_input_type(self):
        assert is_boundary_control(_FakeEl({"type": "submit"})) is True

    def test_create_account_text(self):
        assert is_boundary_control(_FakeEl({"type": "button"}, text="Create Account")) is True

    def test_sign_up_button_by_role(self):
        # A real "Sign Up" control is button-like (role=button / a <button>) — refused.
        assert is_boundary_control(_FakeEl({"aria-label": "Sign Up", "role": "button"})) is True

    def test_plain_fill_target_not_boundary(self):
        assert is_boundary_control(_FakeEl({"type": "text", "name": "first_name"})) is False

    def test_calendar_day_button_not_boundary(self):
        # A day cell <button>7</button> must NOT be judged a submit control.
        assert is_boundary_control(_FakeEl({"type": "button"}, text="7")) is False

    def test_fillable_field_with_marker_substring_not_boundary(self):
        # Greptile #817: a FILLABLE field whose name/label merely CONTAINS a boundary
        # marker substring ("submit"/"register") is NOT a submit control — refusing it
        # would record a false fill failure. Only button-like controls are judged by text.
        assert is_boundary_control(_FakeEl({"type": "text", "name": "submitted_by"})) is False
        assert is_boundary_control(_FakeEl({"aria-label": "Registered name"})) is False
        assert is_boundary_control(_FakeEl({"type": "email", "name": "register_email"})) is False

    def test_submit_button_still_refused_by_text(self):
        # A genuine submit BUTTON (button-like + marker) is still refused.
        assert is_boundary_control(_FakeEl({"type": "button"}, text="Submit Application")) is True

    def test_none(self):
        assert is_boundary_control(None) is False


class TestHealFillSelector:
    def test_intact_selector_returned_unchanged(self):
        page = FakeHealPage({"[name='first_name']": _FakeEl({"type": "text"})})
        res = heal_fill_selector(page, "[name='first_name']", "First Name", wait_config=_FAST)
        assert res.selector == "[name='first_name']"
        assert res.healed is False
        assert res.refused is False

    def test_broken_selector_healed_to_alternative(self):
        # Original is gone; the aria-label alternative resolves to the intended input.
        page = FakeHealPage(
            {"[aria-label=\"First Name\"]": _FakeEl({"type": "text"}, text="")}
        )
        res = heal_fill_selector(
            page, "[name='old_first_name']", "First Name", wait_config=_FAST
        )
        assert res.refused is False
        assert res.healed is True
        assert res.selector == '[aria-label="First Name"]'

    def test_recovery_onto_submit_control_is_refused(self):
        # The recovered alternative resolves to a submit control → REFUSED, boundary intact.
        page = FakeHealPage({'[aria-label="Submit"]': _FakeEl({"type": "submit"})})
        res = heal_fill_selector(page, "[name='old_start']", "Submit", wait_config=_FAST)
        assert res.refused is True
        assert res.selector is None

    def test_original_pointing_at_boundary_is_refused(self):
        # A re-rendered page pointing the original selector at a submit control → refused.
        page = FakeHealPage({"[name='x']": _FakeEl({"type": "submit"})})
        res = heal_fill_selector(page, "[name='x']", "X", wait_config=_FAST)
        assert res.refused is True

    def test_no_recovery_candidate_returns_none(self):
        page = FakeHealPage({})
        res = heal_fill_selector(page, "[name='gone']", "Gone", wait_config=_FAST)
        assert res.refused is False
        assert res.healed is False
        assert res.selector is None


class TestTypeValueSelfHeal:
    """The DEFAULT (use_planner=False) fill path self-heals through type_value."""

    def _src(self, page):
        src = PlaywrightPageSource.__new__(PlaywrightPageSource)
        src._page = page
        src._HEAL_WAIT_CONFIG = _FAST
        return src

    def test_stale_selector_recovered_to_intended_field(self):
        page = FakeHealPage(
            {'[aria-label="First Name"]': _FakeEl({"type": "text"}, text="")}
        )
        src = self._src(page)
        src.type_value("[name='old_first_name']", "Ada", label="First Name")
        # The healed alternative was filled with the intended value.
        assert page.typed['[aria-label="First Name"]'] == "Ada"

    def test_recovery_onto_submit_control_refused_and_nothing_filled(self):
        page = FakeHealPage({'[aria-label="Submit"]': _FakeEl({"type": "submit"})})
        src = self._src(page)
        with pytest.raises(PrefillBoundaryViolation):
            src.type_value("[name='old_start']", "value", label="Submit")
        # Boundary intact: no fill/type ever landed on the submit control.
        assert page.filled == {}
        assert page.typed == {}
