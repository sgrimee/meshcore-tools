# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Show 'Not connected' banner on F2 Channels and F3 Contacts tabs
- Add node blacklist to filter spurious address-collision nodes
- Add F4 companion info tab with device info panel and command input
- Add settings.toml to persist default region
- Import channels from channels.txt to connected companion
- Show recent connections expanded by default in ConnectScreen
- Colour unread dot indicator in tab labels with warning amber
- Add unread message indicators for channels and DMs
- Persist companion channel data to channels.txt for packet decryption
- Save per-repeater passwords with fallback default in config
- Format JSON command responses as key: value lines

### Changed
- Skip code review for PRs authored by claude[bot]

### Fixed
- Skip code review for Claude Code-authored PRs
- Map F4 companion tab commands to binary API calls
- Resolve BLE device names for legacy history entries
- Show BLE device name instead of MAC address in recent companion list
- Show unread dot when message received for selected contact while tab is inactive
- Recognise channel_secret field and skip all-zero keys in _extract_channel_key_hex
- Add reload_channels method to MonitorTab and store _channels_path
- Rename ambiguous variable l to line in test_channels.py
- Allow bots to trigger claude code review workflow
- Parse Python dict reprs and improve response formatting
- Accept bool | None in _on_save callback to satisfy push_screen type overloads

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

[unreleased]: https://github.com/sgrimee/meshcore-tools/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/sgrimee/meshcore-tools/compare/v0.1.0...v0.2.0
