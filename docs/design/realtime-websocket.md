# Realtime WebSocket bridge — design

**Status:** design / phased build. **Owner decisions (scoping Q&A):** dedicated duplex channel per
session (shared single-tenant engine — NOT per-session engine sharding); **full bridge**
(browser ⇄ workspace ⇄ engine); **one user, many tabs/devices**; use cases: **(1) live takeover
desktop, (2) co-steer running agents, (3) push everything / kill polling**.

## Why

Today the FE↔BE model is **half-duplex**: the browser POSTs to *start* work and the server
streams back over **SSE** (`StreamingResponse`, `data: …\n\n`), consumed via `EventSource` or
`fetch().body.getReader()`. There is **no client→server realtime channel**, the applicant Portal /
bell **poll** (`applicantPortal.js` `pollVisible` + a cross-tab `applicant:pending-changed`
localStorage event), and the engine is a **single shared single-tenant** 24/7 loop that every
session merely observes through owner-gated HTTP proxies. The only true WebSocket in the tree is
engine→remote-Chrome **CDP** (`adapters/sandbox/proxmox_client.py`).

This adds a **bidirectional, per-session-multiplexed WebSocket** so the one operator's tabs/devices
can co-drive live: push (no polling), steer a running agent, and hand-finish a submit on the live
takeover desktop — all in-app.

## Architecture

```
 browser  ⇄WS⇄  workspace/app.py            ⇄WS⇄  engine (app/routers/realtime.py)
    │             session registry:                 per-session actor over the ONE shared
    │             session_id → {ws, subscribers}     single-tenant engine (CDP takeover,
    │             + replay buffer per channel        agent_runs bus, notification bus)
    └── ONE multiplexed WS. Frame envelope:
        { "chan": "notif|agent|takeover|chat|presence", "type": "...", "seq": N, "data": {...} }
```

### Frame envelope (both hops speak the same envelope)
- `chan` — logical channel (see below). One physical socket multiplexes all channels.
- `type` — per-channel message type (e.g. `notif`/`pending`, `agent`/`event`, `agent`/`steer`,
  `takeover`/`frame`, `takeover`/`input`, `presence`/`join`).
- `seq` — monotonic per-`(session, chan)` sequence for replay/ordering + gap detection.
- `data` — channel payload (JSON; binary takeover frames sent as separate binary WS frames tagged
  by a preceding envelope, or base64 in `data` for v1 simplicity — decide in Phase 4).

### Session registry + replay buffer (generalize `agent_runs.py`)
`agent_runs.py` already implements the exact pattern we need, for ONE channel: a background drain
task fans events into a **per-session replay buffer** (`buffer: list`, `subscribers: set` of
`asyncio.Queue`); closing a client drops only the subscriber; reconnect **replays buffer then goes
live**; a grace-timer evicts terminal state. **Lift-and-shift that** into a general
`RealtimeSession` that holds a buffer + subscriber-set **per channel**, keyed by `session_id`.
Many tabs of the one user attach to the **same** `RealtimeSession` → all see identical live state
(co-driving) and a reconnecting tab replays-then-lives. This is the "1:1 per session, N connections"
model — **1 session : N sockets**, not 1 socket : 1 anything.

### Channels
| chan | dir | payload | phase |
|---|---|---|---|
| `presence` | both | tab join/leave, who's-connected count | 1 |
| `notif` | BE→FE | notifications + pending-actions (replaces Portal/bell polling) | 2 |
| `agent` | both | agent-run events (down) + `steer`/`pause`/`approve` (up) | 3 |
| `takeover` | both | CDP screen frames (down) + mouse/keyboard input (up) | 4 |
| `chat` | both | optional: migrate chat SSE onto the WS | later/opt |

## Auth + safety (NON-NEGOTIABLE)
- **Auth on upgrade:** the WS `Upgrade` request is authenticated by the existing `applicant_session`
  cookie via the same gate as HTTP; owner-scoped identically (`require_engine_owner` semantics). An
  unauthenticated / non-owner upgrade is rejected before any channel opens.
- **The WS MUST NOT become a bypass of the review-before-submit stop-boundary.** Every **upstream**
  command (`agent/steer`, `agent/approve`, `takeover/input`) is validated **server-side** against the
  same core rules the HTTP path uses — the socket is just transport. In particular: `agent/approve`
  cannot self-authorize a final submit any more than the HTTP path can; the engine's
  review-before-submit + pre-fill stop-boundary still hold. Protected-question classes stay
  non-AI-answered. **Never gate a safety check on a caller-supplied flag** (SOUL.md #: safety
  server-side).
- **No new authority:** the WS exposes only what the owner can already do over HTTP; it does not add
  a consequential action that wasn't already review-gated.

## Fallback (degrade, never break)
- If the WS can't connect / drops and won't re-establish, the FE **falls back** to today's SSE
  (chat/agent) + polling (Portal/bell). The push channel is an *optimization over* polling, not a
  hard dependency — an honesty invariant (no silent dead UI). A visible "reconnecting…" state, then
  transparent fallback.
- Reconnect uses the replay buffer + last `seq` to resume without gaps or dupes.

## Deploy / proxy
- The public surface is `applicant-ui` fronting `workspace/`; the engine is internal. The reverse
  proxy (Caddy/Traefik/nginx, `docs/reverse-proxy-https.md`) must pass the `Upgrade`/`Connection`
  headers for the WS route. Caddy/Traefik do by default; document the nginx `proxy_set_header
  Upgrade`/`Connection` lines. Compose `applicant-ui`→`api` internal hop likewise for the bridge WS.

## Phasing (each = one focused PR, gated + owner-reviewed)
1. **Transport backbone** — WS endpoints (workspace + engine), the bridge handshake, the frame
   envelope, `RealtimeSession` registry + per-channel replay buffer (lifted from `agent_runs.py`),
   cookie-auth on upgrade, a minimal `presence` channel to prove the round-trip, FE WS client
   (`workspace/static/js/applicantRealtime.js`) with reconnect + fallback scaffolding, tests. **No
   user-facing feature yet.**
2. **Push channel (`notif`)** — fan notifications + pending-actions over the WS; FE consumes it and
   **retires the Portal/bell polling** (keeping poll as the fallback). Highest daily value, lowest
   risk. Reuse the existing `applicant:pending-changed` contract so bell/rail/Portal all update.
3. **Agent co-steer (`agent`)** — upstream `pause`/`redirect`/`approve` over `agent_runs`, fanned to
   all the session's tabs, safety-gated server-side; FE controls on the run view.
4. **Live takeover desktop (`takeover`)** — CDP screen frames ⇄ FE canvas ⇄ input, over the full
   bridge; extends `applicantRemote.js`. Biggest + most infra-sensitive; last.

## Test contract (per phase, in addition to `/gate`)
- Backbone: auth-rejects-unauthenticated-upgrade; owner-scope; envelope round-trip; **reconnect
  replays buffer then lives**; drop-a-subscriber-doesn't-kill-the-session; fallback path exercised.
- Every upstream-command channel: a server-side test that a crafted command **cannot** bypass the
  stop-boundary / answer a protected question / act on a foreign id.
- White-label clean; hexagonal purity (`lint-imports`); reachability contract.
