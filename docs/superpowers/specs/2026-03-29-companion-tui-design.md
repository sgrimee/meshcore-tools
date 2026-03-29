# Companion TUI — Design Spec (2026-03-29)

## Overview

Extend `meshcore-tools` with a unified Textual TUI (`MeshCoreApp`) that is the default entry point. The app has three tabs: Monitor (existing packet monitor), Chat (companion messaging), and Repeaters (companion repeater management). Companion functionality requires the optional `[companion]` extra (`meshcore` PyPI package); without it, only the Monitor tab appears.

---

## Goals

1. **Unified TUI** — `meshcore-tools` with no subcommand launches the full app; tabs provide quick switching between monitor and companion views.
2. **Companion chat** — send/receive channel messages (public, hashtag, private) via a connected companion device.
3. **Repeater management** — full parity with `meshcore-cli` repeater commands (status, login, cmd, trace, reboot).
4. **Clean separation** — companion data does not merge into the monitor packet table; each tab is independent.

---

## Architecture

### Module Layout

```
src/meshcore_tools/
  cli.py          — entry point; default (no subcommand) launches MeshCoreApp
  app.py          — NEW: MeshCoreApp, owns TabbedContent and companion state
  monitor.py      — refactored: exports MonitorTab widget (existing logic extracted)
  chat.py         — NEW: ChatTab widget
  repeaters.py    — NEW: RepeatersTab widget
  companion.py    — NEW: CompanionManager (meshcore async bridge, optional import)
  connection.py   — NEW: ConnectScreen modal + config read/write
  decoder.py      — unchanged
  channels.py     — unchanged
  db.py           — unchanged
  providers/      — unchanged
```

### Widget Hierarchy

```
MeshCoreApp  (app.py)
├── Header      — app title + connection status indicator
├── TabbedContent
│   ├── MonitorTab    (monitor.py — existing polling logic, extracted as widget)
│   ├── ChatTab       (chat.py — only mounted if meshcore is installed)
│   └── RepeatersTab  (repeaters.py — only mounted if meshcore is installed)
└── Footer      — keybindings hint bar
```

`CompanionManager` (companion.py) is not a widget. It lives as an attribute on `MeshCoreApp`, wraps the `meshcore` async client, and communicates with the app via `app.post_message()`.

---

## CLI Entry Point

- `meshcore-tools` (no subcommand) → launches `MeshCoreApp` (new default)
- `meshcore-tools monitor` → alias for above (backward compatibility)
- `meshcore-tools nodes` → unchanged
- `pyproject.toml` adds optional dependency group: `meshcore-tools[companion]` pulls in `meshcore` (minimum version to be confirmed against PyPI at implementation time)
- If `meshcore` is not installed, Chat and Repeaters tabs are not mounted. The footer shows: `companion features require: pip install meshcore-tools[companion]`

---

## CompanionManager — Async Bridge

`CompanionManager` bridges `meshcore`'s asyncio API to Textual's event loop:

- Runs in the **same asyncio event loop** as Textual (no thread needed — Textual is async-native).
- On `connect()`: establishes the `meshcore` client (TCP, serial, or BLE), calls `APP_START`, subscribes to push events (`MESSAGE_RECEIVED`, node updates, etc.).
- **Incoming events** → forwarded to the app via `app.post_message()` using custom Textual message classes.
- **Outgoing commands** (send message, repeater command) → awaited as `@work(thread=False)` async workers on the calling widget so the UI stays responsive.
- **Connection failures / timeouts** → `CompanionManager` posts a `CompanionConnectionError` message to the app; the Header updates its status indicator.
- **On disconnect**: cleans up subscriptions, posts `Disconnected` message to app; Chat and Repeaters tabs clear their in-memory state.

### Connection Config

Stored at `~/.config/meshcore-tools/connection.json`:

```json
{
  "type": "tcp",
  "host": "192.168.1.5",
  "port": 5000
}
```

Supported types: `tcp` (host + port), `serial` (device path), `ble` (device name). On startup, config is read and connection attempted automatically if present. The `ConnectScreen` modal handles first-time setup and on-demand changes, with a scan button for BLE/serial discovery.

---

## Monitor Tab

Existing `PacketMonitorApp` logic extracted into `MonitorTab` widget. No functional changes — same packet table, detail panel, map panel, and API polling behavior. The tab receives no data from the companion; it always uses the letsmesh REST API.

---

## Chat Tab

### Layout

```
┌─────────────────────────────────────────────┐
│  [ #public ]  [ #mesh ]  [ alice (private) ] │  ← channel strip
├─────────────────────────────────────────────┤
│                                              │
│  14:23  gw-charly:  hello mesh               │  ← message log
│  14:24  alice:      hey!                     │     (scrollable, auto-scroll)
│  14:25  you:        hi  ✓                    │
│                                              │
├─────────────────────────────────────────────┤
│  > type a message...            [ 42/133 ]  │  ← input bar
└─────────────────────────────────────────────┘
```

### Behavior

- Channels populated from companion on connect (contacts + configured channels).
- Channel selector is a horizontal tab strip; switching channels changes the message log.
- 133-character limit enforced in the input widget; character counter updates live.
- Send on Enter. Sent messages appear immediately with `⏳`; updated to `✓` on ACK or `✗` on timeout (no retry).
- Private channel PSK must be pre-configured in `connection.json` — not managed in the UI.
- All messages are in-memory only. Cleared on disconnect.

---

## Repeaters Tab

### Layout

```
┌─────────────┬───────────────────────────────┐
│ Repeaters   │  Commands                     │
│             │                               │
│  gw-charly  │  [Status]  [Login]  [Trace]   │
│  node-far   │  [Cmd]     [Reboot]           │
│             │                               │
│             ├───────────────────────────────┤
│             │  Output log (scrollable)      │
│             │  14:30 status: uptime=2d...   │
│             │  14:31 trace: 3 hops          │
└─────────────┴───────────────────────────────┘
```

### Commands

| Button | Action |
|--------|--------|
| Status | `req_status` — display firmware version, uptime, config |
| Login  | Prompt for password, authenticate |
| Cmd    | Free-text input, send arbitrary repeater command |
| Trace  | `trace` — display hop-by-hop path result |
| Reboot | Confirm dialog, then send reboot command |

- Repeater list populated from companion contacts on connect (filtered to repeater type).
- Commands requiring login show a warning if not yet authenticated.
- All output is in-memory, cleared on disconnect.

---

## Keybindings

| Key | Action |
|-----|--------|
| F1  | Switch to Monitor tab |
| F2  | Switch to Chat tab (only registered when companion is available) |
| F3  | Switch to Repeaters tab (only registered when companion is available) |
| C   | Open ConnectScreen modal |
| Q   | Quit |

---

## Optional Dependency Handling

`companion.py` is only imported inside a `try/except ImportError` block. The import check happens once at app startup:

```python
try:
    from meshcore_tools.companion import CompanionManager
    COMPANION_AVAILABLE = True
except ImportError:
    COMPANION_AVAILABLE = False
```

`MeshCoreApp.compose()` conditionally mounts Chat and Repeaters tabs based on `COMPANION_AVAILABLE`.

---

## Out of Scope

- Chat history persistence (SQLite) — deferred to a future iteration
- Private channel PSK management in the UI — pre-configured in `connection.json`
- Companion packets feeding the Monitor tab — Monitor always uses letsmesh API
- Split-screen simultaneous views — architecture supports it, not implemented now
