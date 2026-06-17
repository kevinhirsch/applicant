"""Configurable Ubuntu webtop takeover desktop (FR-SANDBOX-2/3, FR-PREFILL-5).

The takeover environment is a containerized, web-streamed FULL Ubuntu desktop whose
DE is configurable (Cinnamon default / Xfce / GNOME on X11). These unit tests pin the
SELECTION + URL/token + lifecycle logic in the default hermetic lane (no Docker/VM):

* TAKEOVER_DESKTOP defaults to cinnamon; invalid values are rejected.
* DE -> image resolution for all three (gnome -> the local custom image).
* REMOTE_VIEW_BACKEND switches the wired sub-port webtop <-> neko.
* The webtop remote-view mints a tokenized one-click URL, carries the handoff app
  URL (session-continuity), and tears down (token invalidated).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from applicant.adapters.sandbox.local_sandbox import LocalSandbox
from applicant.adapters.sandbox.remote_view import (
    NekoRemoteView,
    WebtopRemoteView,
)
from applicant.app.config import (
    Settings,
    resolve_takeover_image,
)
from applicant.app.container import _build_remote_view
from applicant.core.ids import ApplicationId, new_id
from applicant.ports.driven.sandbox import RemoteViewPort


# --- config: default + validation -------------------------------------------
def test_takeover_desktop_defaults_to_cinnamon():
    s = Settings(_env_file=None)
    assert s.takeover_desktop == "cinnamon"
    assert s.remote_view_backend == "webtop"


@pytest.mark.parametrize(
    "de", ["cinnamon", "xfce", "gnome", "pantheon", "GNOME", " Pantheon "]
)
def test_takeover_desktop_accepts_valid_des(de):
    s = Settings(_env_file=None, TAKEOVER_DESKTOP=de)
    assert s.takeover_desktop in {"cinnamon", "xfce", "gnome", "pantheon"}


def test_invalid_takeover_desktop_rejected_with_clear_error():
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, TAKEOVER_DESKTOP="kde-plasma")
    assert "TAKEOVER_DESKTOP" in str(exc.value)


def test_invalid_remote_view_backend_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, REMOTE_VIEW_BACKEND="rdp")


# --- DE -> image resolution table -------------------------------------------
def test_de_to_image_resolution_all_three():
    # FR-STEALTH-1: every DE ships Google Chrome, so Cinnamon/Xfce resolve to the
    # LOCAL derived Chrome-enabled webtop images (stock LinuxServer webtops have no
    # Chrome), and GNOME (no prebuilt webtop) resolves to the custom GNOME image.
    assert resolve_takeover_image("cinnamon") == "applicant/webtop-chrome:cinnamon"
    assert resolve_takeover_image("xfce") == "applicant/webtop-chrome:xfce"
    # GNOME does NOT ship as a prebuilt webtop -> local custom image (also Chrome).
    assert resolve_takeover_image("gnome") == "applicant/webtop-gnome:latest"
    # Pantheon likewise -> local custom Pantheon-on-Ubuntu image (also Chrome).
    assert resolve_takeover_image("pantheon") == "applicant/webtop-pantheon:latest"


def test_image_override_wins():
    assert (
        resolve_takeover_image("cinnamon", "my/custom:tag") == "my/custom:tag"
    )
    s = Settings(_env_file=None, TAKEOVER_DESKTOP="gnome", TAKEOVER_DESKTOP_IMAGE="x/y:z")
    assert s.takeover_desktop_image_resolved == "x/y:z"


def test_settings_resolves_configured_de_image():
    s = Settings(_env_file=None, TAKEOVER_DESKTOP="xfce")
    assert s.takeover_desktop_image_resolved == "applicant/webtop-chrome:xfce"


# --- REMOTE_VIEW_BACKEND switches the wired sub-port (webtop <-> neko) -------
def test_backend_webtop_selects_webtop_remote_view():
    s = Settings(_env_file=None, REMOTE_VIEW_BACKEND="webtop", TAKEOVER_DESKTOP="gnome")
    rv = _build_remote_view(s)
    assert isinstance(rv, WebtopRemoteView)
    assert isinstance(rv, RemoteViewPort)
    assert rv.provider == "webtop"
    assert rv.desktop == "gnome"
    assert rv.image == "applicant/webtop-gnome:latest"


def test_backend_neko_selects_neko_remote_view():
    s = Settings(_env_file=None, REMOTE_VIEW_BACKEND="neko")
    rv = _build_remote_view(s)
    assert isinstance(rv, NekoRemoteView)
    assert rv.provider == "neko"


# --- webtop remote-view: tokenized one-click URL + teardown -----------------
def test_webtop_view_url_is_tokenized_one_click():
    view = WebtopRemoteView()
    url = view.view_url("sess-1")
    assert "sess-1" in url and "token=" in url
    # token is valid until invalidated.
    tok = url.split("token=")[1].split("&")[0]
    assert view.token_valid("sess-1", tok)


def test_webtop_handoff_carries_application_url():
    # FR-PREFILL-5 / session-continuity: the desktop opens the SAME application URL.
    view = WebtopRemoteView()
    view.bind_application_url("sess-1", "https://jobs.example.com/apply/42?x=1")
    url = view.view_url("sess-1")
    assert "app=" in url
    # URL-encoded so it survives as a query value.
    assert "https%3A%2F%2Fjobs.example.com" in url


def test_webtop_teardown_invalidates_token_and_app_url():
    sandbox = LocalSandbox(remote_view=WebtopRemoteView())
    view = sandbox.remote_view()
    session = sandbox.provision(ApplicationId(new_id()))
    tok = session.remote_view_url.split("token=")[1].split("&")[0]
    assert view.token_valid(session.session_id, tok)
    sandbox.teardown(session.session_id)
    # FR-SANDBOX-2: a torn-down session's one-click link stops working.
    assert not view.token_valid(session.session_id, tok)


def test_sandbox_remote_view_swappable_to_webtop():
    sandbox = LocalSandbox(remote_view=WebtopRemoteView())
    assert sandbox.remote_view().provider == "webtop"
    session = sandbox.provision(ApplicationId(new_id()))
    assert session.remote_view_url and "token=" in session.remote_view_url
