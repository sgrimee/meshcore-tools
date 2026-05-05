# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-05-05

### Added
- Three-mode path display (`n` key): names, src+dest with labels, or all-hex
- Coordinate support in input files (lat/lon fields)
- Relay range limit: hops beyond 150 km are rejected in map view
- Show packet path one hop per line in detail view
- Expand/collapse multiple observations with arrow keys in monitor table
- Expandable multi-observer sub-rows in monitor table
- MQTT packet source for monitor tab with observer-aware deduplication
- 'Not connected' banner on Channels and Contacts tabs
- Node blacklist to filter spurious address-collision nodes
- F4 companion info tab with device info panel and command input
- Settings file to persist default region across sessions
- Recent connections shown expanded by default in ConnectScreen
- Unread indicator in tab labels coloured amber
- Unread message indicators for channels and DMs
- Per-repeater password storage with fallback default
- Command responses formatted as key: value lines
- Channel keys stored in secrets.toml; auto-synced when connecting companion
- Channel data persisted to channels.txt and imported to connected companion
- Show geo-resolved name for source/dest in path detail view
- Parse wardriving coordinates from #wardriving channel messages
- Per-hop geo-scoring fallback for long path packets
- Show hex prefix on map labels; list unplaced nodes by hex prefix

### Changed
- Config files consolidated into config.toml and secrets.toml (migration required)

### Fixed
- Map footer names restored; Path destination key corrected
- Nodes at (0,0) rejected as Null Island
- Wrong-continent node placement prevented for short/partial key matches
- Map display cropped on first open due to premature size read
- BLE device names shown instead of MAC addresses in recent connections
- Unread dot shown for messages received while another contact is selected
- Channel key parsing for channel_secret field; all-zero keys skipped
- Companion response formatting improved (Python dict reprs parsed)
- 'Not connected' display unified across Companion tab panels
- Preserve composite name for ambiguous hops
- Use exact key lookup in node coordinates to prevent wrong-continent placement
- Lowercase hex prefixes in map node labels
- Remove nodes placed on wrong continent via hash collision

## [0.2.0] - 2026-04-03

### Added
- Add logging to just monitor
- Per-contact logs, login state tracking, and improved trace/ping/telemetry
- Auto-focus most recent device on connection panel open
- Add DM/ping/telemetry contact ops; fix status/ping response display
- Display channels as vertical list on left of channels tab
- Remember recent companions; auto-connect BLE by saved MAC
- Rename Chat→Channels tab; contextual contacts tab
- Use left/right keys to switch channels instead of tab
- Auto-fetch channels on connect; suppress stderr logs in TUI
- Add update-changelog skill for keepachangelog.com format
- Add resize handle between detail and map panels
- Mouse-draggable resize handles for log panel and detail/map panels
- Move F1/F2/F3 hints from footer into tab titles
- Add bottom log panel toggled with l, resizable with +/-
- Add Logs tab with live level filter and --log-file CLI option
- Clear tiles cache (justfile)
- Include paired/cached BLE devices from bluetoothctl in scan results
- Pre-select first BLE device after scan, show PIN only after device selected
- Add optional BLE PIN field for pairing
- Implement ConnectScreen section switching, serial discovery, BLE scan worker
- Rework ConnectScreen.compose with TCP/Serial/BLE sections
- Add list_serial_ports and format_ble_devices helpers
- Update CLI — default launch MeshCoreApp, monitor as alias
- Add MeshCoreApp with TabbedContent
- Add RepeatersTab widget
- Add ChatTab widget
- Extract MonitorTab(TabPane), update run_monitor() to launch MeshCoreApp
- Add CompanionManager and Textual message classes
- Add ConnectScreen Textual modal
- Add ConnectionConfig dataclass and config I/O
- Add companion optional dependency (meshcore>=2.3.3)

### Changed
- Regression tests for repeater ping/telemetry/status protocols
- Add build and clean targets to justfile
- Exclude dev-only files from sdist
- Manage version in __version__.py, add CHANGELOG
- Delete old specs
- Remove title label from log panel
- Remove Logs tab, keep only the bottom log panel
- Mention linux and mac support
- Update uv.lock for pyserial dependency
- Add ConnectScreen device discovery implementation plan
- Add ConnectScreen device discovery design spec
- Update CLAUDE.md with new module layout
- Add skills and agents
- Add companion TUI design spec

### Fixed
- Restore working ping/status/telemetry protocols for repeaters
- Reset to first button when contacts tab gains focus
- Only show active-cmd button highlight when contacts tab is active
- Ping filter, telemetry min_timeout, auto-select first list item
- Correct ping/telemetry/status/cmd protocols; add log colours
- Resolve DM sender name, fix ping event, inline DM/cmd input
- Remove flex-wrap from recent-buttons in ConnectScreen
- Load all contacts in repeaters tab; use left/right for command nav
- Resolve all ty type-check diagnostics
- Justfile tool name
- Inner resize handle direction follows mouse correctly
- Suppress class name text in ResizeHandle by rendering Blank
- Disconnect BLE on exit/crash; shorten (Shift-) to (S-) in footer
- Catch macOS Bluetooth permission SIGABRT instead of crashing
- Avoid scan conflicts by using BLEDevice object from manual scan
- Translate BLE scan errors properly, only show sudo hint for permission errors
- Restore MeshCore filter, show name prominently in scan results
- Show all BLE devices in scan, connect by MAC address
- Show BLE PIN in plain text
- Auto-recover from NotPermitted BLE stale connection
- Translate BLE errors to plain English, remove spurious markup_escape
- Guard Select.NULL in _submit, pin pyserial version
- Remove unused BleakDBusError/BleakError imports
- Add pyserial to base deps, fix test import order
- Use self.app.call_from_thread in MonitorTab._poll_worker
- Rename MonitorTab.region to _region to avoid Widget property conflict
- Post CompanionDisconnected on explicit disconnect, add TODO for channel population, escape sub_title markup
- Move TYPE_CHECKING import before try/except block (PEP 8)
- COMPANION_AVAILABLE reflects actual meshcore install status
- Escape markup in chat messages, handle invalid timestamps
- Trace passes dst=contact, add _EventType fallback
- ConnectScreen Select allow_blank=False and port validation
- Correct module docstring (ConnectScreen added in Task 3)

[unreleased]: https://github.com/sgrimee/meshcore-tools/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/sgrimee/meshcore-tools/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/sgrimee/meshcore-tools/compare/v0.1.0...v0.2.0
