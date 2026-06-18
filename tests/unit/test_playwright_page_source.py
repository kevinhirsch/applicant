"""Hermetic tests for the REAL PlaywrightPageSource via a stubbed Playwright page.

No browser binary: a lightweight ``_StubPage`` / ``_StubLocator`` stands in for the
Playwright page so we can drive the integration-gated code paths and assert their
real behavior (multi-page advance, status/body in current(), real selectors,
content-aware predicates, slugified screenshot path, fingerprint script, cadence).
"""

from __future__ import annotations

from applicant.adapters.browser.page_source import (
    PlaywrightPageSource,
    _slugify,
)
from applicant.adapters.browser.stealth import NORMALIZED_FINGERPRINT


class _StubHandle:
    def __init__(self, attrs=None, text="", inner=""):
        self._attrs = attrs or {}
        self._inner = inner

    def get_attribute(self, name):
        return self._attrs.get(name)

    def evaluate(self, script):
        # Two evaluate uses: tagName lookup, and the _best_label resolver. The stub
        # can't run JS, so simulate: tagName -> "input"; label resolver -> aria-label.
        if "tagName" in script:
            return "input"
        return self._attrs.get("aria-label", "") or self._inner

    def inner_text(self):
        return self._inner


class _StubLocator:
    def __init__(self, count=1, enabled=True, on_click=None):
        self._count = count
        self._enabled = enabled
        self._on_click = on_click
        self.first = self
        self.pressed: list[tuple[str, float]] = []

    def count(self):
        return self._count

    def is_enabled(self):
        return self._enabled

    def click(self):
        if self._on_click:
            self._on_click()

    def press_sequentially(self, ch, delay=0.0):
        self.pressed.append((ch, delay))


class _StubKeyboard:
    def __init__(self):
        self.typed: list[str] = []
        self.pressed: list[str] = []
        # Options revealed only after typing (simulates react-select filtering).
        self.reveal_on_type: list = []

    def type(self, text, delay=0):
        self.typed.append(text)
        for opt in self.reveal_on_type:
            opt._visible = True

    def press(self, key):
        self.pressed.append(key)


class _StubOption:
    def __init__(self, text, visible=True):
        self._text = text
        self._visible = visible
        self.clicked = False

    def inner_text(self):
        return self._text

    def is_visible(self):
        return self._visible

    def get_attribute(self, name):
        return self._text if name == "data-automation-label" else None

    def click(self):
        self.clicked = True


class _StubElement:
    def __init__(self, visible=True, tag="div", options=None, attrs=None):
        self._visible = visible
        self._tag = tag
        self._options = [_StubOption(o) for o in (options or [])]
        self._attrs = attrs or {}
        self.clicked = False

    def is_visible(self):
        return self._visible

    def evaluate(self, _script):
        # Mimics page.evaluate("e => e.tagName") → uppercase tag name.
        return self._tag.upper()

    def get_attribute(self, name):
        return self._attrs.get(name)

    def click(self):
        self.clicked = True

    def query_selector_all(self, sel):
        return self._options if sel == "option" else []


class _StubPage:
    def __init__(self, *, url="https://acme.myworkdayjobs.com/job/1"):
        self.url = url
        self._content = "<html><body></body></html>"
        self._handles_by_sel: dict[str, list[_StubHandle]] = {}
        self._locators: dict[str, _StubLocator] = {}
        # Selector -> _StubElement for query_selector (visible-challenge detection).
        self._elements_by_sel: dict[str, _StubElement] = {}
        self._body_text = ""
        self.filled: list[str] = []
        self.typed: list[tuple[str, str, int]] = []
        self.screenshots: list[str] = []
        # select_option calls: (selector, kwargs) — and which option (label) won.
        self.selected: list[tuple[str, dict]] = []
        # Options returned for query_selector_all("[role='option']") (custom dropdown).
        self._role_options: list = []
        self.keyboard = _StubKeyboard()

    # query / read
    def query_selector_all(self, sel):
        if sel == "[role='option']":
            return self._role_options
        return self._handles_by_sel.get(sel, [])

    def query_selector(self, sel):
        return self._elements_by_sel.get(sel)

    def select_option(self, selector, **kwargs):
        # Mimic Playwright: succeed only when the requested label/value matches one of
        # the element's options; otherwise raise (so the tolerant fallback is exercised).
        el = self._elements_by_sel.get(selector)
        opts = [o.inner_text() for o in (el._options if el is not None else [])]
        want = kwargs.get("label") or kwargs.get("value")
        if want not in opts:
            raise ValueError(f"no option {want!r}")
        self.selected.append((selector, kwargs))

    def content(self):
        return self._content

    def inner_text(self, _sel):
        return self._body_text

    def locator(self, sel):
        return self._locators.get(sel, _StubLocator(count=0))

    # input
    def fill(self, sel, _val):
        self.filled.append(sel)

    def type(self, sel, value, delay=80):
        self.typed.append((sel, value, delay))

    def screenshot(self, path):
        self.screenshots.append(path)

    def wait_for_load_state(self, *a, **k):
        pass

    def on(self, *a, **k):
        pass


def _bare_source(page):
    """Construct a PlaywrightPageSource without running __init__ (no browser)."""
    src = object.__new__(PlaywrightPageSource)
    src._page = page
    src._fingerprint = dict(NORMALIZED_FINGERPRINT)
    src._status = None
    src._expected_host = None
    return src


# --- current() populates status/body/detection (FR-PREFILL-6) -------------
def test_current_populates_status_body_and_detection():
    # A genuine, user-visible interstitial PHRASE is a real challenge marker.
    page = _StubPage()
    page._content = "<html>please complete the captcha to continue</html>"
    src = _bare_source(page)
    src._status = 403
    src._expected_host = "acme.myworkdayjobs.com"
    state = src.current()
    assert state.status == 403
    assert "complete the captcha" in state.body
    assert "complete the captcha" in state.detection_signals
    assert state.expected_host == "acme.myworkdayjobs.com"


def test_embedded_invisible_recaptcha_script_is_not_a_signal():
    # REGRESSION (live PwC playtest): a page that merely EMBEDS an (invisible)
    # reCAPTCHA script must NOT be flagged — the login form is fillable. Without a
    # visible challenge element or interstitial phrase, detection_signals is empty.
    page = _StubPage()
    page._content = (
        "<html><head>"
        "<script src='https://www.google.com/recaptcha/api.js'></script>"
        "</head><body><form><input name='email'><input type='password'>"
        "</form></body></html>"
    )
    src = _bare_source(page)
    state = src.current()
    assert state.detection_signals == ()


def test_visible_challenge_widget_is_a_signal():
    # A RENDERED + visible reCAPTCHA challenge iframe IS a real challenge → flagged.
    page = _StubPage()
    page._content = "<html><body>sign in</body></html>"
    page._elements_by_sel["iframe[src*='recaptcha'][src*='bframe']"] = _StubElement(visible=True)
    src = _bare_source(page)
    state = src.current()
    assert "recaptcha" in state.detection_signals


def test_invisible_challenge_widget_element_is_not_a_signal():
    # The reCAPTCHA badge iframe exists but is NOT visible (invisible reCAPTCHA) →
    # not a blocker.
    page = _StubPage()
    page._elements_by_sel["iframe[src*='recaptcha'][src*='bframe']"] = _StubElement(visible=False)
    src = _bare_source(page)
    assert src.current().detection_signals == ()


# --- <select> dropdowns are CHOSEN, not typed (FR-PREFILL-2/3) -------------
def test_type_value_uses_select_option_for_dropdowns():
    # REGRESSION (local fixture playtest): a <select> field (EEO / work-auth /
    # country) must be filled via select_option — typing into it throws, so every
    # dropdown silently failed before. Here the resolved value matches an option.
    page = _StubPage()
    page._elements_by_sel["[name='gender']"] = _StubElement(
        tag="select", options=["Male", "Female", "prefer not to say"]
    )
    src = _bare_source(page)
    src.type_value("[name='gender']", "prefer not to say")
    assert page.selected == [("[name='gender']", {"label": "prefer not to say"})]
    assert page.filled == []  # never routed through the text-fill path


def test_select_option_tolerant_contains_match():
    # The resolved value overlaps an option's longer label → still selected.
    page = _StubPage()
    page._elements_by_sel["[name='race']"] = _StubElement(
        tag="select", options=["Asian", "Decline to self-identify (USA)"]
    )
    src = _bare_source(page)
    src.type_value("[name='race']", "decline to self-identify")
    assert page.selected == [("[name='race']", {"label": "Decline to self-identify (USA)"})]


def test_text_input_still_typed_not_selected():
    page = _StubPage()
    page._elements_by_sel["[name='email']"] = _StubElement(tag="input")
    src = _bare_source(page)
    src.type_value("[name='email']", "a@b.com")
    assert page.selected == []
    assert page.typed and page.typed[0][0] == "[name='email']"


# --- Workday custom <button> dropdowns (aria-haspopup=listbox) --------------
def test_detect_fields_includes_listbox_buttons():
    # REGRESSION (Workday mock playtest): Workday's Country/Phone-type/EEO fields are
    # <button aria-haspopup="listbox"> — NOT <select> — so the input/select/textarea
    # query missed them. They must be detected as 'listbox' fields.
    page = _StubPage()
    page._handles_by_sel["button[aria-haspopup='listbox'], [role='combobox']"] = [
        _StubHandle({"aria-haspopup": "listbox", "data-automation-id": "gender", "aria-label": "gender"})
    ]
    fields = _bare_source(page).detect_fields()
    assert any(f.field_type == "listbox" and f.label == "gender" for f in fields)


def test_type_value_chooses_listbox_option():
    # The dropdown is opened (trigger clicked) and the matching VISIBLE option is
    # clicked — never typed into.
    page = _StubPage()
    trigger = _StubElement(tag="button", attrs={"aria-haspopup": "listbox"})
    page._elements_by_sel['[data-automation-id="gender"]'] = trigger
    opt_other = _StubOption("Male")
    opt_match = _StubOption("Prefer not to say")
    page._role_options = [opt_other, opt_match]
    src = _bare_source(page)
    src.type_value('[data-automation-id="gender"]', "prefer not to say")
    assert trigger.clicked is True
    assert opt_match.clicked is True
    assert opt_other.clicked is False
    assert page.typed == []  # never routed through the text-type path


def test_type_value_typeable_combobox_filters_then_picks():
    # REGRESSION (live Greenhouse): a react-select combobox is an <input
    # role="combobox" aria-autocomplete="list">. When the wanted option is not shown
    # until the list is filtered, the engine TYPES to filter, then clicks the match.
    page = _StubPage()
    cb = _StubElement(tag="input", attrs={"role": "combobox", "aria-autocomplete": "list"})
    page._elements_by_sel["#country"] = cb
    hidden_match = _StubOption("United States", visible=False)  # appears only after typing
    page._role_options = [_StubOption("Canada", visible=False), hidden_match]
    page.keyboard.reveal_on_type = page._role_options
    src = _bare_source(page)
    src.type_value("#country", "United States")
    assert "United States" in page.keyboard.typed  # typed to filter the long list
    assert hidden_match.clicked is True


def test_listbox_decline_synonym_maps_to_form_wording():
    # REGRESSION (live Greenhouse EEO): the stored decline value ("prefer not to say")
    # must map to a form option worded differently for the SAME intent ("Decline To
    # Self Identify") — picked from the OPEN options without typing (typing would
    # wrongly filter the 3-option list to nothing).
    page = _StubPage()
    page._elements_by_sel["#gender"] = _StubElement(
        tag="input", attrs={"role": "combobox", "aria-autocomplete": "list"}
    )
    male = _StubOption("Male")
    decline = _StubOption("Decline To Self Identify")
    page._role_options = [male, _StubOption("Female"), decline]
    src = _bare_source(page)
    src.type_value("#gender", "prefer not to say")
    assert decline.clicked is True
    assert male.clicked is False
    assert page.typed == []  # matched the open options; never filtered them away


def test_option_match_exact_loose_and_decline():
    from applicant.adapters.browser.page_source import PlaywrightPageSource as P

    assert P._option_match("Mobile", "Mobile") == "exact"
    assert P._option_match("decline to self-identify", "Decline To Self Identify") in ("exact", "loose")
    assert P._option_match("prefer not to say", "I don't wish to answer") == "loose"
    assert P._option_match("prefer not to say", "I do not want to answer") == "loose"
    assert P._option_match("Male", "Female") is None  # not a false decline match
    # A dialing-code suffix must not block a country match.
    assert P._option_match("United States of America", "United States +1") == "loose"
    assert P._option_match("United States of America", "United Kingdom +44") is None


def test_filter_query_uses_first_meaningful_words():
    from applicant.adapters.browser.page_source import PlaywrightPageSource as P

    assert P._filter_query("United States of America") == "United States"
    assert P._filter_query("Mobile") == "Mobile"


def test_combobox_country_matches_despite_dialing_code():
    # REGRESSION (live Greenhouse phone country): type a short filter query, then match
    # "United States of America" to the option labelled "United States +1".
    page = _StubPage()
    page._elements_by_sel["#country"] = _StubElement(
        tag="input", attrs={"role": "combobox", "aria-autocomplete": "list"}
    )
    us = _StubOption("United States +1", visible=False)
    page._role_options = [_StubOption("United Kingdom +44", visible=False), us]
    page.keyboard.reveal_on_type = page._role_options
    src = _bare_source(page)
    src.type_value("#country", "United States of America")
    assert page.keyboard.typed == ["United States"]  # short filter query, not the full value
    assert us.clicked is True


def test_listbox_skips_hidden_options_from_other_dropdowns():
    # Options from a closed dropdown (not visible) must NOT be chosen — only the
    # visible option of the opened dropdown.
    page = _StubPage()
    page._elements_by_sel['[data-automation-id="veteran_status"]'] = _StubElement(
        tag="button", attrs={"aria-haspopup": "listbox"}
    )
    hidden = _StubOption("Decline to self-identify", visible=False)  # other, closed dropdown
    visible = _StubOption("I am not a protected veteran", visible=True)
    page._role_options = [hidden, visible]
    src = _bare_source(page)
    src.type_value('[data-automation-id="veteran_status"]', "i am not a protected veteran")
    assert visible.clicked is True
    assert hidden.clicked is False


# --- detect_fields returns REAL selectors ----------------------------------
def test_detect_fields_builds_real_selectors():
    page = _StubPage()
    page._handles_by_sel["input, select, textarea"] = [
        _StubHandle({"name": "firstName", "type": "text"}),
        _StubHandle({"id": "email", "type": "email"}),
        _StubHandle({"data-automation-id": "phone", "type": "tel"}),
    ]
    src = _bare_source(page)
    selectors = [f.selector for f in src.detect_fields()]
    assert selectors[0] == '[name="firstName"]'
    assert selectors[1] == "#email"
    assert selectors[2] == '[data-automation-id="phone"]'
    # All are usable Playwright selector strings, not raw attribute values.
    assert all(s.startswith(("[", "#")) for s in selectors)


def test_detect_fields_resolves_label_and_required():
    # Universal-ATS support: the engine reads the field's real label (here via the
    # aria-label the stub returns from its label-resolver evaluate) and captures the
    # DOM's required flag — so it can map fields and block only on required ones.
    page = _StubPage()
    page._handles_by_sel["input, select, textarea"] = [
        _StubHandle({"id": "q1", "type": "text", "aria-label": "Why do you want this job?",
                     "required": "true"}),
        _StubHandle({"id": "q2", "type": "text", "aria-label": "Portfolio URL"}),  # optional
    ]
    fields = {f.label: f for f in _bare_source(page).detect_fields()}
    assert fields["Why do you want this job?"].required is True
    assert fields["Portfolio URL"].required is False


# --- advance traverses N pages then ends -----------------------------------
def test_advance_traverses_multiple_pages_then_ends():
    page = _StubPage(url="https://acme.myworkdayjobs.com/p1")
    # Three pages: each click bumps the URL; after page 3 the Next control vanishes.
    state = {"n": 1}

    def click_next():
        state["n"] += 1
        page.url = f"https://acme.myworkdayjobs.com/p{state['n']}"
        if state["n"] >= 3:
            # last page: Next control disappears
            page._locators["button:has-text('Next')"] = _StubLocator(count=0)

    page._locators["button:has-text('Next')"] = _StubLocator(count=1, on_click=click_next)
    src = _bare_source(page)

    advanced = 0
    while src.advance() is not None:
        advanced += 1
        if advanced > 10:  # guard against an infinite loop
            break
    assert advanced == 2  # p1 -> p2 -> p3, then None


# --- predicates use content, not just URL ----------------------------------
def test_is_account_create_uses_content_not_just_url():
    page = _StubPage(url="https://acme.myworkdayjobs.com/login")
    # A pure LOGIN page (url has no 'account') must NOT be account-create...
    page._handles_by_sel["h1"] = [_StubHandle(inner="Sign In")]
    src = _bare_source(page)
    assert src.is_account_create_page() is False
    # ...and a register page IS account-create even with a /login-ish url.
    page._handles_by_sel["h1"] = [_StubHandle(inner="Create Account")]
    assert src.is_account_create_page() is True


def test_is_final_submit_distinguishes_review_personal_from_submit():
    page = _StubPage(url="https://acme.myworkdayjobs.com/review")
    # A "review your personal information" page is NOT the final submit.
    page._handles_by_sel["h1"] = [_StubHandle(inner="Review Your Personal Information")]
    src = _bare_source(page)
    assert src.is_final_submit_page() is False
    # A page with a real "Submit Application" button IS final submit.
    page._handles_by_sel["h1"] = [_StubHandle(inner="Ready to apply?")]
    page._handles_by_sel["button"] = [_StubHandle(inner="Submit Application")]
    assert src.is_final_submit_page() is True


# --- screenshot path is slugified ------------------------------------------
def test_screenshot_path_is_slugified():
    page = _StubPage(url="https://acme.test/jobs/123?step=2&x=y")
    src = _bare_source(page)
    ref = src.screenshot()
    assert page.screenshots  # screenshot was taken
    written = page.screenshots[0]
    # No invalid filename chars from the URL tail.
    assert "?" not in written and ":" not in written.split("/tmp/")[-1]
    assert ref.startswith("file://")


def test_slugify_strips_invalid_chars():
    assert "/" not in _slugify("a/b?c:d")
    assert _slugify("step=2&x=y").replace("-", "").isalnum()


# --- fingerprint platform/webgl applied (FR-STEALTH-1) ---------------------
def test_fingerprint_init_script_applies_platform_and_webgl():
    script = PlaywrightPageSource.fingerprint_init_script(NORMALIZED_FINGERPRINT)
    assert NORMALIZED_FINGERPRINT["platform"] in script  # Win32
    assert NORMALIZED_FINGERPRINT["webgl_vendor"] in script
    assert NORMALIZED_FINGERPRINT["webgl_renderer"] in script
    assert "navigator" in script and "37445" in script  # UNMASKED_VENDOR_WEBGL


# --- cadence is applied, not discarded (FR-STEALTH-2) ----------------------
def test_type_value_applies_cadence_plan():
    page = _StubPage()
    sel = '[name="firstName"]'
    loc = _StubLocator()
    page._locators[sel] = loc
    src = _bare_source(page)
    src.type_value(sel, "Ada", cadence_ms=[100.0, 50.0, 75.0])
    # Each char pressed with its own dwell (not a constant 80ms via .type()).
    assert [c for c, _ in loc.pressed] == ["A", "d", "a"]
    assert [d for _, d in loc.pressed] == [100.0, 50.0, 75.0]
    assert page.typed == []  # the constant-delay path was NOT used
