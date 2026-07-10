"""Live-takeover CDP transport seam (realtime-websocket.md, Phase 4).

The ``takeover`` realtime channel is a HUMAN driving the live browser: CDP
**screencast frames** stream DOWN and **mouse/keyboard input** streams UP. Both
ride the ONE existing owner-gated takeover surface — the same sandbox +
remote-view sub-port the HTTP ``/api/remote`` router already exposes
(``authorize_takeover`` / ``revoke_takeover`` / ``has_takeover``). This module
adds NO new authority: it is pure transport between the socket and that existing
surface, and it can never click a final submit (no submit/approve path exists
here at all — the human hand-finishes through the existing explicit HTTP gates).

Layering: this is the CDP transport boundary, split real-vs-fake exactly like
:class:`~applicant.adapters.sandbox.proxmox_client.ProxmoxApiClient` /
:class:`FakeProxmoxClient`. The default lane drives the in-memory
:class:`FakeTakeoverCdpDriver` (records input, emits scripted frames) so the whole
channel wiring + safety seam is unit-tested with NO Chrome / CDP / network; the
REAL :class:`PlaywrightCdpTakeoverDriver` connects Playwright ``connect_over_cdp``
to the session's EXISTING ``cdp_endpoint`` (never a new CDP client) and is the
clearly-marked ``# integration`` boundary, skipped without a remote Chrome.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from applicant.observability.logging import get_logger

log = get_logger(__name__)

#: A downstream screencast-frame sink: ``(session_id, message_type, data) -> None``.
#: The control layer passes one that fans the frame into the ``takeover`` channel
#: (via the realtime registry). Screencast frames are base64-in-``data`` for v1
#: (see the module/design note): one envelope path, at a bandwidth/latency cost.
TakeoverFrameSink = Callable[[str, str, dict[str, Any]], None]


@runtime_checkable
class TakeoverCdpDriver(Protocol):
    """The thin CDP transport a live takeover drives (screencast down, input up)."""

    def send_input(self, cdp_endpoint: str, event: dict[str, Any]) -> None:
        """Dispatch ONE raw mouse/keyboard event to the remote Chrome over CDP.

        ``event`` is the browser's own normalized input payload (kind + coords /
        key). The driver translates it to the matching ``Input.dispatch*`` CDP
        call. It is raw human input — it carries no application authority.
        """
        ...

    def start_screencast(
        self, cdp_endpoint: str, session_id: str, on_frame: TakeoverFrameSink
    ) -> None:
        """Begin streaming CDP screencast frames, calling ``on_frame`` per frame."""
        ...

    def stop_screencast(self, session_id: str) -> None:
        """Stop the screencast for ``session_id`` (idempotent)."""
        ...


class FakeTakeoverCdpDriver:
    """In-memory :class:`TakeoverCdpDriver` for the default lane (NO Chrome / CDP).

    Records every dispatched input and every screencast start/stop so the channel
    wiring + safety seam are unit-testable, and can emit scripted frames through the
    registered sink to exercise the downstream fan-out. Deterministic, side-effect
    free.
    """

    def __init__(self, *, scripted_frames: list[dict[str, Any]] | None = None) -> None:
        #: list of (cdp_endpoint, event) for every dispatched input.
        self.inputs: list[tuple[str, dict[str, Any]]] = []
        #: session_id -> the live frame sink (present while streaming).
        self.streaming: dict[str, TakeoverFrameSink] = {}
        #: frames to emit on ``start_screencast`` (test scripting).
        self._scripted = list(scripted_frames or [])

    def send_input(self, cdp_endpoint: str, event: dict[str, Any]) -> None:
        self.inputs.append((cdp_endpoint, dict(event)))

    def start_screencast(
        self, cdp_endpoint: str, session_id: str, on_frame: TakeoverFrameSink
    ) -> None:
        self.streaming[session_id] = on_frame
        # Emit any scripted frames immediately so a hermetic test can assert the
        # downstream fan-out without a real CDP screencast pump.
        for frame in self._scripted:
            on_frame(session_id, "frame", dict(frame))

    def emit(self, session_id: str, data: dict[str, Any]) -> bool:
        """Push one frame through the live sink (test helper). False if not streaming."""
        sink = self.streaming.get(session_id)
        if sink is None:
            return False
        sink(session_id, "frame", dict(data))
        return True

    def stop_screencast(self, session_id: str) -> None:
        self.streaming.pop(session_id, None)


class TakeoverControl:
    """Owner-gated live-takeover control — pure transport to the EXISTING surface.

    Wraps the sandbox (session lookup) + its remote-view sub-port (the EXISTING
    ``authorize_takeover``/``revoke_takeover``/``has_takeover`` the HTTP
    ``/api/remote`` router uses) + a :class:`TakeoverCdpDriver`. The realtime
    dispatcher calls:

    * :meth:`authorize` — hand control to the user (SAME as ``POST
      /api/remote/sessions/{id}/takeover``) and START streaming screencast frames
      down the ``takeover`` channel;
    * :meth:`revoke` — return control to the engine + stop the screencast (SAME as
      the remote-view ``revoke_takeover``);
    * :meth:`send_input` — forward ONE raw human mouse/keyboard event to the live
      browser, but ONLY while the user actually holds control (``has_takeover``).

    NO new authority: every method maps to something the owner can already do over
    the existing surface, and there is NO submit/approve path here — the human's
    own final submit still goes through the explicit HTTP finish gates.
    """

    def __init__(
        self,
        sandbox: Any,
        cdp_driver: TakeoverCdpDriver,
        *,
        frame_sink: TakeoverFrameSink | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._cdp = cdp_driver
        #: Injected downstream sink (fans a frame into the ``takeover`` channel). A
        #: ``None`` sink (unit context) makes screencast a clean no-op.
        self._frame_sink = frame_sink

    def _session(self, session_id: str) -> Any:
        get = getattr(self._sandbox, "get", None)
        return get(session_id) if callable(get) else None

    def _remote_view(self) -> Any:
        rv = getattr(self._sandbox, "remote_view", None)
        return rv() if callable(rv) else None

    def has_control(self, session_id: str) -> bool:
        rv = self._remote_view()
        has = getattr(rv, "has_takeover", None) if rv is not None else None
        return bool(has(session_id)) if callable(has) else False

    def authorize(self, session_id: str) -> tuple[bool, str]:
        """Hand control to the user + start the screencast. ``(ok, reason)``."""
        session = self._session(session_id)
        if session is None:
            return False, f"unknown takeover session: {session_id}"
        rv = self._remote_view()
        authorize = getattr(rv, "authorize_takeover", None) if rv is not None else None
        if callable(authorize):
            authorize(session_id)  # EXISTING owner-gated takeover (FR-SANDBOX-3)
        self._start_screencast(session_id, session)
        return True, ""

    def revoke(self, session_id: str) -> tuple[bool, str]:
        """Return control to the engine + stop the screencast. ``(ok, reason)``."""
        session = self._session(session_id)
        if session is None:
            return False, f"unknown takeover session: {session_id}"
        rv = self._remote_view()
        revoke = getattr(rv, "revoke_takeover", None) if rv is not None else None
        if callable(revoke):
            revoke(session_id)  # EXISTING owner-gated revoke (FR-SANDBOX-3)
        try:
            self._cdp.stop_screencast(session_id)
        except Exception:  # pragma: no cover - stopping a stream must never raise
            pass
        return True, ""

    def send_input(self, session_id: str, event: dict[str, Any]) -> tuple[bool, str]:
        """Forward ONE raw human input event to the live browser. ``(ok, reason)``.

        Refused unless the session exists AND the user currently holds control
        (``has_takeover``): a bare ``input`` frame can never drive the browser
        while the ENGINE holds it, so this is strictly the human hand-finishing.
        """
        session = self._session(session_id)
        if session is None:
            return False, f"unknown takeover session: {session_id}"
        if not self.has_control(session_id):
            return False, "take control of the session before sending input"
        cdp_endpoint = getattr(session, "cdp_endpoint", None) or ""
        try:
            self._cdp.send_input(cdp_endpoint, event)
        except Exception:  # pragma: no cover - a transport hiccup is a clean denial
            return False, "could not send input to the live session"
        return True, ""

    def _start_screencast(self, session_id: str, session: Any) -> None:
        sink = self._frame_sink
        if sink is None:
            return  # unit context / no registry bound: streaming is a clean no-op
        cdp_endpoint = getattr(session, "cdp_endpoint", None) or ""
        try:
            self._cdp.start_screencast(cdp_endpoint, session_id, sink)
        except Exception:  # pragma: no cover - a screencast hiccup must not break takeover
            log.warning("takeover_screencast_start_failed", session_id=session_id)


class PlaywrightCdpTakeoverDriver:  # pragma: no cover - integration
    """REAL CDP takeover driver over Playwright ``connect_over_cdp`` — # integration.

    Connects to the session's EXISTING ``cdp_endpoint`` (the one the automation
    already uses — NOT a new CDP client), opens a CDP session on the active page,
    and:

    * ``send_input`` -> ``Input.dispatchMouseEvent`` / ``Input.dispatchKeyEvent``;
    * ``start_screencast`` -> ``Page.startScreencast`` + a ``Page.screencastFrame``
      handler that base64-forwards each frame through the sink (acking each frame).

    Playwright is imported lazily so the default lane never needs the dependency or
    a reachable Chrome; an integration test (skipped without a remote Chrome) drives
    it. Left as a thin skeleton: the hermetic seam is :class:`FakeTakeoverCdpDriver`.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}

    def send_input(self, cdp_endpoint: str, event: dict[str, Any]) -> None:
        raise NotImplementedError(
            "PlaywrightCdpTakeoverDriver is the integration boundary; the default "
            "lane uses FakeTakeoverCdpDriver."
        )

    def start_screencast(
        self, cdp_endpoint: str, session_id: str, on_frame: TakeoverFrameSink
    ) -> None:
        raise NotImplementedError(
            "PlaywrightCdpTakeoverDriver is the integration boundary; the default "
            "lane uses FakeTakeoverCdpDriver."
        )

    def stop_screencast(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
