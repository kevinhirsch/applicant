"""Pure Home Assistant allowlist matching (Phase 4). No app deps."""

import importlib.util as _u

_spec = _u.spec_from_file_location(
    "ha_allowlist",
    __file__.rsplit("/tests/", 1)[0] + "/services/homeassistant/allowlist.py",
)
al = _u.module_from_spec(_spec)
_spec.loader.exec_module(al)


def test_entity_domain():
    assert al.entity_domain("light.kitchen") == "light"
    assert al.entity_domain("alarm_control_panel.home") == "alarm_control_panel"
    assert al.entity_domain("noprefix") == ""
    assert al.entity_domain("") == ""


def test_empty_allowlist_denies_everything():
    assert al.is_allowed("light.kitchen", []) is False
    assert al.is_allowed("light.kitchen", None) is False


def test_exact_match():
    assert al.is_allowed("light.kitchen", ["light.kitchen"]) is True
    assert al.is_allowed("light.bedroom", ["light.kitchen"]) is False


def test_domain_wildcards():
    assert al.is_allowed("light.kitchen", ["light"]) is True
    assert al.is_allowed("light.kitchen", ["light.*"]) is True
    assert al.is_allowed("switch.fan", ["light"]) is False


def test_global_wildcard():
    assert al.is_allowed("anything.here", ["*"]) is True


def test_whitespace_and_blank_entries_ignored():
    assert al.is_allowed("light.kitchen", ["  light.kitchen  "]) is True
    assert al.is_allowed("light.kitchen", ["", "  "]) is False
