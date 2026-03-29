# Companion TUI — Session Context (2026-03-29)

## Status: Brainstorming in progress — awaiting clarifying questions

This file captures research and context from an interrupted brainstorming session. To resume:
> Open Claude Code in this repo, reference this file, and say:
> "Resume brainstorming the companion TUI feature from docs/superpowers/specs/2026-03-29-companion-tui-session-context.md"

---

## User Intent

Add Textual TUI panes that allow interacting with a MeshCore **companion** (a LoRa device connected via BLE, Serial, or TCP), replicating `meshcore-cli` functionality inside the existing TUI. Specific goals:

1. **Companion selector** — discover and connect to a companion device
2. **Channel chat** — tabbed interface for chatting in channels (public, hashtag, private)
3. **Repeater management** — send commands to remote repeaters via the companion

---

## Research Findings

### Current Codebase (`letsmesh-tui`)

- **Architecture**: Textual TUI app (`PacketMonitorApp`) that polls `api.letsmesh.net` REST API for packets and displays them in a `DataTable` with side panels (detail, map).
- **Key modules**: `monitor.py` (818 lines, main TUI), `decoder.py`, `channels.py`, `db.py`, `map_view.py`, `providers/`
- **Textual patterns used**: `@work(thread=True)` for background polling, CSS layout switching, `ModalScreen`, `DataTable`, keybindings via `BINDINGS`
- **No current direct-device integration** — only passive observation via REST API

### meshcore Python Ecosystem

| Package | Role |
|---------|------|
| `meshcore` (PyPI) | Core async Python library for device interaction |
| `meshcore-cli` (PyPI) | CLI tool wrapping `meshcore`, not a usable library |
| `meshcore-decoder` | Packet decoding utility |

### `meshcore` Python Library

- **Async-based** (`asyncio`), event-driven — fits Textual's async model well
- **Connection types**: BLE, Serial, TCP
- **Key patterns**:
  ```python
  # Command style
  result = await meshcore.commands.send_msg(contact, "Hello!")
  # Event subscription style
  meshcore.subscribe(EventType.MESSAGE_RECEIVED, callback)
  ```
- **Protocol**: Sequential commands, 5s timeout, 133-char message limit, frame format: `marker(1B) + size(2B LE) + payload`

### Existing Textual TUI Projects (reference implementations)

**meshtui** (`ekollof/meshtui`, v0.2.9+ on PyPI — actively maintained):
- Two-panel layout: sidebar (contacts/channels) + tabbed main (Chat, Device Settings, Node Mgmt, Logs)
- SQLite persistence per device (keyed by public key)
- ACK tracking + retry logic (3 attempts)
- Async event subscriptions
- Modules: `connection.py`, `transport.py`, `database.py`, `app.py`

**tui-meshcore** (`guax/tui-meshcore`):
- Onboarding wizard
- Public + private channel PSK support
- SQLite storage
- Hardware presets + 15 regional presets
- Config at `~/.config/tui-meshcore/`

### MeshCore Protocol Key Facts

- Commands: `APP_START` (0x01), send channel msg (0x03), get queued msgs (0x0A), etc.
- Push notifications: 0x80–0x8A range
- Channel types: public (fixed key), hashtag (`SHA256("#name")[:16]`), private (random secret)
- Repeater commands: `login`, `cmd`, `req_status`, `trace` — sent via companion

---

## Key Design Questions (not yet asked)

The brainstorming session was interrupted before clarifying questions. These need to be resolved:

1. **New app vs. integrated pane?** — Should companion interaction live in a new `meshcore-companion monitor` subcommand/app, or as additional panes/screens within the existing `PacketMonitorApp`?

2. **Connection UI** — How should companion discovery work? Manual entry (host:port / serial path) or auto-scan?

3. **Persistence** — Should chat history be persisted (SQLite)? Or in-memory only (ephemeral)?

4. **Dependency appetite** — Is adding `meshcore` as a mandatory dependency acceptable, or should it be optional (like the map dependencies)?

5. **Scope of repeater management** — Full repeater CLI parity, or just the most common commands (status, login, reboot)?

6. **Relationship to existing packet monitor** — Should a companion-connected session *also* feed packets into the existing monitor view? (The companion sees the same mesh as the letsmesh API observer, but directly.)

---

## Next Steps (when resuming)

1. Ask the clarifying questions above (one at a time)
2. Propose 2–3 architectural approaches with trade-offs
3. Present and iterate on the design
4. Write the approved design doc and commit
5. Run `writing-plans` skill to create implementation plan

---

## Session Notes

- Brainstorming skill was invoked and is guiding the process
- Plan mode is active; no code has been written
- Visual companion (browser mockups) was offered but not yet accepted/declined
