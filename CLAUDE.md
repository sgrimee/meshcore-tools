# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See README.md for usage, commands, input file format, and data sources.

## Architecture

CLI entry point: `meshcore-tools` (defined in `[project.scripts]` in `pyproject.toml`).
Package: `src/meshcore_tools/` with a `src/` layout. Tests in `tests/`.
Dependency: `textual>=0.80` (TUI framework). Optional: `meshcore>=2.3.3` (companion features, install via `pip install meshcore-tools[companion]`).

**Module layout:**
- `src/meshcore_tools/cli.py` — entry point; no subcommand or `monitor` launches `MeshCoreApp`; `nodes` subcommands unchanged
- `src/meshcore_tools/app.py` — `MeshCoreApp` (unified TUI with Monitor/Chat/Repeater tabs); `COMPANION_AVAILABLE` flag
- `src/meshcore_tools/monitor.py` — `MonitorTab(TabPane)` + `PacketMonitorApp` (legacy) + `run_monitor()`
- `src/meshcore_tools/chat.py` — `ChatTab(TabPane)` (channel strip, message log, 133-char input); only mounted when companion available
- `src/meshcore_tools/repeaters.py` — `RepeatersTab(TabPane)` (repeater list + Status/Login/Cmd/Trace/Reboot); only mounted when companion available
- `src/meshcore_tools/companion.py` — `CompanionManager` (async meshcore bridge) + 6 Textual message classes; `_MESHCORE_AVAILABLE` flag
- `src/meshcore_tools/connection.py` — `ConnectionConfig` dataclass, `load/save_connection_config()`, `ConnectScreen` modal
- `src/meshcore_tools/db.py` — node database (`load_db`, `save_db`, `parse_input_file`, `update`)
- `src/meshcore_tools/nodes.py` — node query/display (`lookup`, `list_nodes`)
- `src/meshcore_tools/providers/` — `PacketProvider`, `NodeProvider`, `CoordProvider` protocols + implementations

**Data flow:** `input/*.txt` + live API → `nodes.json` (gitignored)

**Merge logic (`update()` in db.py):** Input file nodes with partial keys (< 64 hex chars) are matched against API nodes whose full key starts with that partial. On match, the partial entry is replaced with the full 64-char key, preserving `type` and `routing` from the input file.

**API access:** Two endpoints, both require `Origin: https://analyzer.letsmesh.net` — no auth:
- `https://api.letsmesh.net/api/nodes?region=LUX` — node list
- `https://api.letsmesh.net/api/packets?region=LUX&limit=50` — recent packets (no WebSocket; poll-based)

**`nodes.json` schema per node:**
```json
{
  "name": "gw-charly",
  "type": "CLI",
  "routing": "Flood",
  "source": "sam.txt",
  "key_complete": true,
  "last_seen": "2026-03-06T..."
}
```
`source` is either a filename from `input/` or `"api:REGION"`. `last_seen` is only present for API-sourced nodes.
