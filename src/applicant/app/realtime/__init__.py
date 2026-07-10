"""Process-lived realtime session registry (transport infrastructure).

Generalizes the ``workspace/src/agent_runs.py`` replay-buffer/subscriber pattern
from ONE stream to a **per-channel** buffer + subscriber-set keyed by
``session_id``. Many sockets of the one owner attach to the SAME
:class:`RealtimeSession` (1 session : N sockets): each sees identical live state
and a reconnecting socket replays-then-lives from the per-channel buffer.

Process-lived (module-global registry) so it survives the scheduler's per-tick
``AgentLoop`` rebuilds — never hang realtime state off a per-tick object.
"""

from applicant.app.realtime.agent_control import (
    AgentControlDispatcher,
    make_agent_control_dispatcher,
)
from applicant.app.realtime.publish import (
    AgentPublisher,
    NotifPublisher,
    make_agent_publisher,
    make_notif_publisher,
)
from applicant.app.realtime.registry import (
    RealtimeRegistry,
    RealtimeSession,
    get_registry,
)

__all__ = [
    "RealtimeRegistry",
    "RealtimeSession",
    "get_registry",
    "make_notif_publisher",
    "NotifPublisher",
    "make_agent_publisher",
    "AgentPublisher",
    "make_agent_control_dispatcher",
    "AgentControlDispatcher",
]
