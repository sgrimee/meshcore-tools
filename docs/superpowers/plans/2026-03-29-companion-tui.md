# Companion TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend meshcore-tools with a unified Textual TUI (MeshCoreApp) featuring Monitor, Chat, and Repeater tabs with optional companion device integration via the `meshcore` PyPI package.

**Architecture:** `MeshCoreApp` owns a `TabbedContent` with up to three tabs. `CompanionManager` bridges the `meshcore` async client to Textual's event loop by posting custom `Message` subclasses to the app. Chat and Repeater tabs are only mounted when `meshcore` is installed.

**Tech Stack:** Python 3.13, Textual ≥0.80, meshcore ≥2.3.3 (optional `[companion]` extra)

---

## File Structure

**Created:**
- `src/meshcore_tools/app.py` — `MeshCoreApp`: `TabbedContent` + keybindings + companion lifecycle
- `src/meshcore_tools/companion.py` — `CompanionManager` + custom Textual message classes
- `src/meshcore_tools/chat.py` — `ChatTab(TabPane)` widget
- `src/meshcore_tools/repeaters.py` — `RepeatersTab(TabPane)` widget
- `src/meshcore_tools/connection.py` — `ConnectionConfig` dataclass + config I/O + `ConnectScreen` modal
- `tests/test_connection_config.py` — unit tests for config read/write
- `tests/test_companion_messages.py` — unit tests for companion message classes

**Modified:**
- `src/meshcore_tools/monitor.py` — extract `MonitorTab(TabPane)`, keep `run_monitor()` as wrapper
- `src/meshcore_tools/cli.py` — make subcommand optional; default + `monitor` launch `MeshCoreApp`
- `pyproject.toml` — add `companion` optional dependency group

---

### Task 1: pyproject.toml — add companion optional dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the companion optional dependency**

In `pyproject.toml`, change the `[project.optional-dependencies]` section from:
```toml
[project.optional-dependencies]
map = ["textual-image", "staticmap", "Pillow"]
```
to:
```toml
[project.optional-dependencies]
map = ["textual-image", "staticmap", "Pillow"]
companion = ["meshcore>=2.3.3"]
```

- [ ] **Step 2: Verify the TOML is valid**

```bash
python -c "import tomllib; tomllib.load(open('pyproject.toml','rb')); print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add companion optional dependency (meshcore>=2.3.3)"
```

---

### Task 2: connection.py — ConnectionConfig dataclass and config I/O

**Files:**
- Create: `src/meshcore_tools/connection.py`
- Create: `tests/test_connection_config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_connection_config.py`:

```python
"""Tests for ConnectionConfig load/save."""

import json
from pathlib import Path

from meshcore_tools.connection import ConnectionConfig, load_connection_config, save_connection_config


def test_load_returns_none_when_missing(tmp_path):
    assert load_connection_config(config_dir=tmp_path) is None


def test_save_and_load_tcp(tmp_path):
    cfg = ConnectionConfig(type="tcp", host="10.0.0.1", port=5000)
    save_connection_config(cfg, config_dir=tmp_path)
    loaded = load_connection_config(config_dir=tmp_path)
    assert loaded is not None
    assert loaded.type == "tcp"
    assert loaded.host == "10.0.0.1"
    assert loaded.port == 5000
    assert loaded.device is None
    assert loaded.ble_name is None


def test_save_and_load_serial(tmp_path):
    cfg = ConnectionConfig(type="serial", device="/dev/ttyUSB0")
    save_connection_config(cfg, config_dir=tmp_path)
    loaded = load_connection_config(config_dir=tmp_path)
    assert loaded is not None
    assert loaded.type == "serial"
    assert loaded.device == "/dev/ttyUSB0"


def test_save_and_load_ble(tmp_path):
    cfg = ConnectionConfig(type="ble", ble_name="MyNode")
    save_connection_config(cfg, config_dir=tmp_path)
    loaded = load_connection_config(config_dir=tmp_path)
    assert loaded is not None
    assert loaded.type == "ble"
    assert loaded.ble_name == "MyNode"


def test_config_file_is_json(tmp_path):
    cfg = ConnectionConfig(type="tcp", host="127.0.0.1", port=4000)
    save_connection_config(cfg, config_dir=tmp_path)
    raw = json.loads((tmp_path / "connection.json").read_text())
    assert raw["type"] == "tcp"
    assert raw["host"] == "127.0.0.1"
    assert raw["port"] == 4000


def test_load_ignores_unknown_keys(tmp_path):
    (tmp_path / "connection.json").write_text(
        '{"type":"tcp","host":"1.2.3.4","port":1234,"future_field":"x"}'
    )
    loaded = load_connection_config(config_dir=tmp_path)
    assert loaded is not None
    assert loaded.host == "1.2.3.4"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_connection_config.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'meshcore_tools.connection'`

- [ ] **Step 3: Create connection.py with ConnectionConfig and I/O only**

Create `src/meshcore_tools/connection.py`:

```python
"""Connection configuration and ConnectScreen modal."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "meshcore-tools"


@dataclass
class ConnectionConfig:
    """Stores connection parameters for a companion device."""

    type: str  # "tcp", "serial", or "ble"
    host: str | None = None
    port: int | None = None
    device: str | None = None
    ble_name: str | None = None


def load_connection_config(config_dir: Path = _DEFAULT_CONFIG_DIR) -> ConnectionConfig | None:
    """Return stored config or None if the file does not exist."""
    path = config_dir / "connection.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return ConnectionConfig(
        type=data.get("type", "tcp"),
        host=data.get("host"),
        port=data.get("port"),
        device=data.get("device"),
        ble_name=data.get("ble_name"),
    )


def save_connection_config(
    config: ConnectionConfig, config_dir: Path = _DEFAULT_CONFIG_DIR
) -> None:
    """Persist config as JSON, creating parent directories as needed."""
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "connection.json"
    data = {k: v for k, v in asdict(config).items() if v is not None}
    path.write_text(json.dumps(data, indent=2))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_connection_config.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/meshcore_tools/connection.py tests/test_connection_config.py
git commit -m "feat: add ConnectionConfig dataclass and config I/O"
```

---

### Task 3: connection.py — ConnectScreen Textual modal

**Files:**
- Modify: `src/meshcore_tools/connection.py`

- [ ] **Step 1: Append ConnectScreen to connection.py**

Add the following imports at the top of `src/meshcore_tools/connection.py` (after the existing imports):

```python
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static
from textual.containers import Container
```

Then append the `ConnectScreen` class at the end of the file:

```python

class ConnectScreen(ModalScreen[ConnectionConfig | None]):
    """Modal for configuring and initiating a companion connection."""

    DEFAULT_CSS = """
    ConnectScreen {
        align: center middle;
    }
    ConnectScreen > Container {
        width: 60;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    ConnectScreen Label {
        margin-top: 1;
    }
    ConnectScreen Input {
        margin-bottom: 1;
    }
    ConnectScreen #buttons {
        layout: horizontal;
        height: 3;
        margin-top: 1;
    }
    ConnectScreen Button {
        margin-right: 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current: ConnectionConfig | None = None) -> None:
        super().__init__()
        self._current = current or ConnectionConfig(type="tcp")

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Connect to companion device[/bold]", markup=True)
            yield Label("Connection type:")
            yield Select(
                [("TCP", "tcp"), ("Serial", "serial"), ("BLE", "ble")],
                value=self._current.type,
                id="conn_type",
            )
            yield Label("Host (TCP only):")
            yield Input(
                value=self._current.host or "",
                placeholder="192.168.1.5",
                id="host",
            )
            yield Label("Port (TCP only):")
            yield Input(
                value=str(self._current.port or 5000),
                placeholder="5000",
                id="port",
            )
            yield Label("Device path (Serial only):")
            yield Input(
                value=self._current.device or "",
                placeholder="/dev/ttyUSB0",
                id="device",
            )
            yield Label("BLE device name (BLE only):")
            yield Input(
                value=self._current.ble_name or "",
                placeholder="MyNode",
                id="ble_name",
            )
            with Container(id="buttons"):
                yield Button("Connect", variant="primary", id="btn_connect")
                yield Button("Cancel", id="btn_cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_connect":
            self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        conn_type = str(self.query_one("#conn_type", Select).value)
        try:
            port = int(self.query_one("#port", Input).value)
        except ValueError:
            port = 5000
        config = ConnectionConfig(
            type=conn_type,
            host=self.query_one("#host", Input).value.strip() or None,
            port=port if conn_type == "tcp" else None,
            device=self.query_one("#device", Input).value.strip() or None,
            ble_name=self.query_one("#ble_name", Input).value.strip() or None,
        )
        self.dismiss(config)
```

- [ ] **Step 2: Run existing connection config tests to verify no regression**

```bash
pytest tests/test_connection_config.py -v
```
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add src/meshcore_tools/connection.py
git commit -m "feat: add ConnectScreen Textual modal"
```

---

### Task 4: companion.py — Custom Textual message classes + CompanionManager

**Files:**
- Create: `src/meshcore_tools/companion.py`
- Create: `tests/test_companion_messages.py`

- [ ] **Step 1: Write failing tests for message classes**

Create `tests/test_companion_messages.py`:

```python
"""Tests for companion Textual message classes."""

from meshcore_tools.companion import (
    ChannelMessage,
    CompanionConnected,
    CompanionConnectionError,
    CompanionDisconnected,
    ContactMessage,
    ContactsUpdated,
)


def test_companion_connected_fields():
    msg = CompanionConnected(node_name="gw-home", node_key="aabbcc")
    assert msg.node_name == "gw-home"
    assert msg.node_key == "aabbcc"


def test_companion_disconnected_instantiates():
    msg = CompanionDisconnected()
    assert isinstance(msg, CompanionDisconnected)


def test_companion_connection_error_has_reason():
    msg = CompanionConnectionError(reason="timeout")
    assert msg.reason == "timeout"


def test_channel_message_fields():
    msg = ChannelMessage(
        channel_idx=0,
        channel_name="#public",
        sender="alice",
        text="hello",
        timestamp=12345,
    )
    assert msg.channel_idx == 0
    assert msg.channel_name == "#public"
    assert msg.sender == "alice"
    assert msg.text == "hello"
    assert msg.timestamp == 12345


def test_contact_message_fields():
    msg = ContactMessage(
        pubkey_prefix="aabb",
        sender="bob",
        text="hi there",
        timestamp=99999,
    )
    assert msg.pubkey_prefix == "aabb"
    assert msg.sender == "bob"
    assert msg.text == "hi there"
    assert msg.timestamp == 99999


def test_contacts_updated_stores_list():
    contacts = [{"name": "relay1", "public_key": "aabb"}]
    msg = ContactsUpdated(contacts=contacts)
    assert len(msg.contacts) == 1
    assert msg.contacts[0]["name"] == "relay1"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_companion_messages.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'meshcore_tools.companion'`

- [ ] **Step 3: Create companion.py**

Create `src/meshcore_tools/companion.py`:

```python
"""CompanionManager — bridges meshcore async client to Textual's event loop.

Import guard: this module imports meshcore at the top level.
Only import it inside `try/except ImportError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.message import Message

if TYPE_CHECKING:
    from textual.app import App
    from meshcore_tools.connection import ConnectionConfig

# meshcore is an optional dependency — imported lazily inside connect()
try:
    from meshcore import MeshCore, EventType as _EventType
    _MESHCORE_AVAILABLE = True
except ImportError:
    _MESHCORE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Custom Textual messages posted to the app from CompanionManager callbacks
# ---------------------------------------------------------------------------

class CompanionConnected(Message):
    """Posted when the companion device connects and sends self-info."""

    def __init__(self, node_name: str, node_key: str) -> None:
        super().__init__()
        self.node_name = node_name
        self.node_key = node_key


class CompanionDisconnected(Message):
    """Posted when the companion device disconnects cleanly."""


class CompanionConnectionError(Message):
    """Posted when a connection attempt fails."""

    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason


class ChannelMessage(Message):
    """Posted when a channel broadcast message is received."""

    def __init__(
        self,
        channel_idx: int,
        channel_name: str,
        sender: str,
        text: str,
        timestamp: int,
    ) -> None:
        super().__init__()
        self.channel_idx = channel_idx
        self.channel_name = channel_name
        self.sender = sender
        self.text = text
        self.timestamp = timestamp


class ContactMessage(Message):
    """Posted when a direct message from a contact is received."""

    def __init__(
        self, pubkey_prefix: str, sender: str, text: str, timestamp: int
    ) -> None:
        super().__init__()
        self.pubkey_prefix = pubkey_prefix
        self.sender = sender
        self.text = text
        self.timestamp = timestamp


class ContactsUpdated(Message):
    """Posted when the contacts list is fetched or refreshed."""

    def __init__(self, contacts: list[dict]) -> None:
        super().__init__()
        self.contacts = contacts


# ---------------------------------------------------------------------------
# CompanionManager — async bridge
# ---------------------------------------------------------------------------

class CompanionManager:
    """Manages the meshcore async client and posts Textual messages to the app.

    Runs in Textual's asyncio event loop (no threads needed).
    Usage:
        manager = CompanionManager(app)
        await manager.connect(config)       # auto-called on startup
        await manager.disconnect()
        # Outgoing commands: called via @work(thread=False) on the widget
        await manager.send_channel_message(channel_idx, text)
        await manager.send_repeater_status(contact)
        await manager.send_repeater_login(contact, password)
        await manager.send_repeater_cmd(contact, cmd)
        await manager.send_repeater_trace(contact)
        await manager.send_repeater_reboot(contact)
    """

    def __init__(self, app: App) -> None:
        self._app = app
        self._client: object | None = None  # MeshCore instance
        self._contacts: list[dict] = []
        self._connected = False

    async def connect(self, config: ConnectionConfig) -> None:
        """Establish meshcore connection and subscribe to push events."""
        if not _MESHCORE_AVAILABLE:
            self._app.post_message(
                CompanionConnectionError(reason="meshcore package not installed")
            )
            return

        try:
            if config.type == "tcp":
                self._client = await MeshCore.create_tcp(
                    config.host or "127.0.0.1",
                    config.port or 5000,
                )
            elif config.type == "serial":
                self._client = await MeshCore.create_serial(config.device or "")
            elif config.type == "ble":
                self._client = await MeshCore.create_ble(config.ble_name or "")
            else:
                self._app.post_message(
                    CompanionConnectionError(reason=f"unknown type: {config.type}")
                )
                return
        except Exception as exc:
            self._app.post_message(CompanionConnectionError(reason=str(exc)))
            return

        self._connected = True
        self._subscribe_events()
        await self._fetch_contacts()
        await self._client.start_auto_message_fetching()

        # Notify the app — self-info may arrive asynchronously; send a placeholder
        self._app.post_message(CompanionConnected(node_name="companion", node_key=""))

    def _subscribe_events(self) -> None:
        client = self._client

        async def _on_channel_msg(event) -> None:
            d = event.payload
            self._app.post_message(
                ChannelMessage(
                    channel_idx=int(d.get("channel_idx", 0)),
                    channel_name=f"#{d.get('channel_idx', 0)}",
                    sender=d.get("sender", "unknown"),
                    text=d.get("text", ""),
                    timestamp=int(d.get("timestamp", 0)),
                )
            )

        async def _on_contact_msg(event) -> None:
            d = event.payload
            self._app.post_message(
                ContactMessage(
                    pubkey_prefix=d.get("pubkey_prefix", ""),
                    sender=d.get("sender", d.get("pubkey_prefix", "?")),
                    text=d.get("text", ""),
                    timestamp=int(d.get("timestamp", 0)),
                )
            )

        async def _on_disconnected(event) -> None:
            self._connected = False
            self._app.post_message(CompanionDisconnected())

        client.subscribe(_EventType.CHANNEL_MSG_RECV, _on_channel_msg)
        client.subscribe(_EventType.CONTACT_MSG_RECV, _on_contact_msg)
        client.subscribe(_EventType.DISCONNECTED, _on_disconnected)

    async def _fetch_contacts(self) -> None:
        result = await self._client.commands.get_contacts()
        if hasattr(result, "type") and str(result.type) != str(_EventType.ERROR):
            payload = result.payload
            if isinstance(payload, dict):
                self._contacts = list(payload.values())
            elif isinstance(payload, list):
                self._contacts = payload
            else:
                self._contacts = []
            self._app.post_message(ContactsUpdated(contacts=list(self._contacts)))

    async def disconnect(self) -> None:
        """Disconnect from the companion device."""
        if self._client is None:
            return
        try:
            await self._client.stop_auto_message_fetching()
            await self._client.disconnect()
        except Exception:
            pass
        finally:
            self._client = None
            self._connected = False

    @property
    def contacts(self) -> list[dict]:
        return list(self._contacts)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # --- Outgoing commands (awaited by @work(thread=False) on the widget) ---

    async def send_channel_message(self, channel_idx: int, text: str) -> bool:
        """Send a channel message. Returns True on success."""
        if not self._client or not self._connected:
            return False
        try:
            result = await self._client.commands.send_chan_msg(chan=channel_idx, msg=text)
            return str(getattr(result, "type", "")) != str(_EventType.ERROR)
        except Exception:
            return False

    async def send_repeater_status(self, contact: dict) -> str:
        """Request status from a repeater. Returns response text."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_statusreq(dst=contact)
            return str(result.payload)
        except Exception as exc:
            return f"error: {exc}"

    async def send_repeater_login(self, contact: dict, password: str) -> str:
        """Log in to a repeater. Returns 'ok' or error string."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_login(dst=contact, pwd=password)
            return str(result.payload)
        except Exception as exc:
            return f"error: {exc}"

    async def send_repeater_cmd(self, contact: dict, cmd: str) -> str:
        """Send an arbitrary command to a repeater."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_cmd(dst=contact, cmd=cmd)
            return str(result.payload)
        except Exception as exc:
            return f"error: {exc}"

    async def send_repeater_trace(self, contact: dict) -> str:
        """Trace route to a repeater."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_trace(
                auth_code=0, tag=None, flags=None, path=None
            )
            return str(result.payload)
        except Exception as exc:
            return f"error: {exc}"

    async def send_repeater_reboot(self, contact: dict) -> str:
        """Reboot a repeater."""
        if not self._client or not self._connected:
            return "not connected"
        try:
            result = await self._client.commands.send_cmd(dst=contact, cmd="reboot")
            return str(result.payload)
        except Exception as exc:
            return f"error: {exc}"
```

- [ ] **Step 4: Run message class tests**

```bash
pytest tests/test_companion_messages.py -v
```
Expected: all PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest -v
```
Expected: all existing tests PASS; new tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/meshcore_tools/companion.py tests/test_companion_messages.py
git commit -m "feat: add CompanionManager and Textual message classes"
```

---

### Task 5: monitor.py — extract MonitorTab widget

**Files:**
- Modify: `src/meshcore_tools/monitor.py`

The goal: extract `PacketMonitorApp`'s internal widgets and logic into a `MonitorTab(TabPane)` class. `PacketMonitorApp` becomes a thin wrapper (`MeshCoreApp` launched with monitor params). `run_monitor()` is updated to launch `MeshCoreApp`.

- [ ] **Step 1: Add `MonitorTab` class to monitor.py**

In `src/meshcore_tools/monitor.py`, add the following imports at the top (alongside existing ones):

```python
from textual.widgets import TabPane
from textual.widgets import TabbedContent
```

Then, immediately after the `PacketMonitorApp` class definition (before `run_monitor`), insert the `MonitorTab` class. It mirrors `PacketMonitorApp` but:
- Inherits from `TabPane` instead of `App`
- `compose()` omits `Header` and `Footer` (those are in `MeshCoreApp`)
- Removes the `q` (quit) binding (handled by `MeshCoreApp`)
- `on_mount()` does not set `sub_title`

```python
class MonitorTab(TabPane):
    """The packet monitor extracted as a TabPane widget for use in MeshCoreApp."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("p", "pause", "Pause/Resume"),
        Binding("f", "filter", "Filter"),
        Binding("d", "toggle_detail_panel", "Detail", key_display="(Shift-)d"),
        Binding("D", "open_detail", "Detail popup", show=False),
        Binding("m", "toggle_map_panel", "Map", key_display="(Shift-)m"),
        Binding("M", "open_map", "Map popup", show=False),
        Binding("a", "toggle_follow", "Follow"),
        Binding("l", "toggle_layout", "Layout"),
        Binding("n", "toggle_names", "Names"),
        Binding("w", "toggle_wrap", "Wrap"),
        Binding("c", "clear", "Clear"),
    ]

    CSS = """
    MonitorTab #main_area {
        height: 1fr;
        layout: horizontal;
    }
    MonitorTab DataTable {
        width: 1fr;
        height: 1fr;
    }
    MonitorTab #panel_area {
        display: none;
        layout: vertical;
        width: 60;
        height: 1fr;
        border-left: solid $accent;
        background: $surface;
    }
    MonitorTab #detail_side {
        display: none;
        height: 1fr;
        padding: 1 2;
    }
    MonitorTab MapSidePanel {
        display: none;
        height: 1fr;
    }
    MonitorTab.panels-bottom #main_area {
        layout: vertical;
    }
    MonitorTab.panels-bottom #panel_area {
        layout: horizontal;
        width: 1fr;
        height: 18;
        border-left: none;
        border-top: solid $accent;
    }
    MonitorTab.panels-bottom #detail_side,
    MonitorTab.panels-bottom MapSidePanel {
        width: 1fr;
        height: 1fr;
    }
    MonitorTab #status {
        height: 1;
        background: $panel;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        region: str,
        packet_provider: "PacketProvider",
        poll_interval: int = 5,
        channels_path: str | None = None,
    ) -> None:
        super().__init__("Monitor", id="tab_monitor")
        self.region = region
        self.poll_interval = poll_interval
        self._packet_provider = packet_provider
        channels = load_channels(channels_path) if channels_path else []
        self._channel_lookup = build_channel_lookup(channels)
        self._db: dict = {"nodes": {}}
        self._seen_ids: set[str] = set()
        self._paused = False
        self._pkt_filters: dict = {"observer": "", "path_node": ""}
        self._all_packets: list[dict] = []
        self._packets_by_id: dict[str, dict] = {}
        self._displayed: list[dict] = []
        self._resolve_path: int = 2
        self._wrap_path: bool = False
        self._detail_panel_open: bool = False
        self._map_panel_open: bool = False
        self._follow: bool = False
        self._layout_bottom: bool = False

    def compose(self) -> ComposeResult:
        with Container(id="main_area"):
            yield DataTable(id="packets")
            with Container(id="panel_area"):
                with VerticalScroll(id="detail_side"):
                    yield Static("", id="detail_content", markup=True)
                yield MapSidePanel(id="map_side")
        yield Label("", id="status")

    def on_mount(self) -> None:
        self._db = load_db()
        table = self.query_one("#packets", DataTable)
        table.add_columns("Time", "Observer", "Type", "SNR", "RSSI", "Src→Relays")
        table.cursor_type = "row"
        self._set_status(None)
        self._poll_worker()

    # All action_* methods and helper methods from PacketMonitorApp are copied here
    # verbatim, replacing `self.app.query_one(...)` patterns with `self.query_one(...)`
    # where the element is inside this tab, and keeping `self.app.push_screen(...)`.

    @work(thread=True, exclusive=True)
    def _poll_worker(self) -> None:
        worker = get_current_worker()
        while not worker.is_cancelled:
            try:
                packets = self._packet_provider.fetch_packets(self.region, limit=500)
                self.call_from_thread(self._ingest_packets, packets)
            except Exception as e:
                self.call_from_thread(self._set_status, str(e))
            for _ in range(self.poll_interval * 10):
                if worker.is_cancelled:
                    return
                time.sleep(0.1)

    def _ingest_packets(self, packets: list[dict]) -> None:
        region = self.region.upper()
        new = [
            p for p in packets
            if p.get("id") not in self._seen_ids
            and region in [r.upper() for r in (p.get("regions") or [])]
        ]
        if not new:
            self._set_status(None)
            return
        db_dirty = False
        for p in new:
            self._seen_ids.add(p["id"])
            pkt_dec = decode_packet(p.get("raw_data", "") or "")
            p["_path"] = pkt_dec.get("path") or []
            p["_decoded"] = pkt_dec
            decoded_payload = pkt_dec.get("decoded") or {}
            p["_src_hash"] = decoded_payload.get("src_hash", "")
            p["_route_type"] = pkt_dec.get("route_type", "")
            p["_path_hop_size"] = pkt_dec.get("path_hop_size", 1)
            if pkt_dec.get("payload_type") == "Advert" and decoded_payload.get("public_key"):
                pub = decoded_payload["public_key"]
                name = decoded_payload.get("name") or pub[:8]
                role = decoded_payload.get("role", "")
                lat = decoded_payload.get("lat")
                lon = decoded_payload.get("lon")
                if learn_from_advert(self._db, pub, name, role, lat, lon):
                    db_dirty = True
                p["_src_hash"] = pub[:12]
            if (pkt_dec.get("payload_type") in GROUP_TYPES and self._channel_lookup):
                raw_payload = bytes.fromhex(pkt_dec.get("payload_hex", "") or "")
                if len(raw_payload) >= 3:
                    ch_byte = raw_payload[0]
                    mac = raw_payload[1:3]
                    ciphertext = raw_payload[3:]
                    result = try_decrypt(ch_byte, mac, ciphertext, self._channel_lookup)
                    if result:
                        p["_decrypted"] = result
            self._packets_by_id[p["id"]] = p
        if db_dirty:
            save_db(self._db)
        self._all_packets = (new + self._all_packets)[:MAX_PACKETS]
        visible_ids = {p["id"] for p in self._all_packets}
        self._packets_by_id = {k: v for k, v in self._packets_by_id.items() if k in visible_ids}
        if not self._paused:
            self._rebuild_table()
        self._set_status(None)

    def _node_matches(self, term: str, node_id: str) -> bool:
        t = term.lower().replace(" ", "")
        return t in resolve_name(node_id, self._db).lower() or node_id.lower().startswith(t)

    def _packet_matches(self, p: dict) -> bool:
        f = self._pkt_filters
        obs_id = p.get("origin_id", "")
        path_ids = p.get("_path") or []
        src_hash = p.get("_src_hash", "")
        if f["observer"]:
            origin_name = (p.get("origin") or "").lower()
            if f["observer"].lower() not in origin_name and not self._node_matches(f["observer"], obs_id):
                return False
        if f["path_node"]:
            obs_id_lower = obs_id.lower()
            def _is_obs(nid: str) -> bool:
                n = nid.lower()
                return obs_id_lower.startswith(n) or n.startswith(obs_id_lower)
            path_and_src = [nid for nid in list(path_ids) + ([src_hash] if src_hash else [])
                            if nid and not _is_obs(nid)]
            if not any(self._node_matches(f["path_node"], nid) for nid in path_and_src):
                return False
        return True

    def _rebuild_table(self) -> None:
        table = self.query_one("#packets", DataTable)
        pinned_id: str | None = None
        if not self._follow and self._displayed:
            cr = table.cursor_row
            if cr < len(self._displayed):
                pinned_id = self._displayed[cr].get("id")
        table.clear()
        self._displayed = [p for p in self._all_packets if self._packet_matches(p)]
        for p in self._displayed:
            heard = p.get("heard_at", "")
            try:
                dt = datetime.fromisoformat(heard.replace("Z", "+00:00"))
                time_str = dt.astimezone().strftime("%H:%M:%S")
            except Exception:
                time_str = heard[:8]
            node = p.get("origin") or resolve_name(p.get("origin_id", ""), self._db)
            ptype = format_payload_type(p.get("payload_type", ""))
            snr = f"{p['snr']:.1f}" if p.get("snr") is not None else "-"
            rssi = str(p.get("rssi", "-"))
            raw_path = p.get("_path") or []
            decrypted = p.get("_decrypted") or {}
            src_display = decrypted.get("sender", "") or p.get("_src_hash", "")
            path = format_path(raw_path, self._db, resolve=self._resolve_path,
                               src_hash=src_display,
                               route_type=p.get("_route_type", ""),
                               hop_size=p.get("_path_hop_size", 1),
                               ptype=p.get("payload_type", ""))
            if self._wrap_path:
                wrap_width = max(20, self.app.size.width - 58)
                lines = textwrap.wrap(path, width=wrap_width) or [path]
                path_cell = Text.from_markup("\n".join(lines))
                row_height = len(lines)
            else:
                path_cell = Text.from_markup(path)
                row_height = 1
            table.add_row(time_str, node, ptype, snr, rssi, path_cell, height=row_height, key=p["id"])
        target_row = 0
        if pinned_id:
            for i, p in enumerate(self._displayed):
                if p.get("id") == pinned_id:
                    target_row = i
                    break
        if target_row > 0:
            table.move_cursor(row=target_row)
        if self._displayed:
            if self._detail_panel_open:
                self._update_detail_side(target_row)
            if self._map_panel_open:
                self._update_map_side(target_row)

    def action_open_detail(self) -> None:
        if not self._displayed:
            return
        row = self.query_one("#packets", DataTable).cursor_row
        self.app.push_screen(PacketDetailScreen(self._displayed, row, self._db))

    def action_open_map(self) -> None:
        if not self._displayed:
            return
        row = self.query_one("#packets", DataTable).cursor_row
        self.app.push_screen(PacketMapScreen(self._displayed, row, self._db))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        row = event.cursor_row
        if not self._displayed or row >= len(self._displayed):
            return
        if self._detail_panel_open:
            self._update_detail_side(row)
        if self._map_panel_open:
            self._update_map_side(row)

    def _update_detail_side(self, row: int) -> None:
        if not self._displayed or row >= len(self._displayed):
            return
        p = self._displayed[row]
        self.query_one("#detail_content", Static).update(_build_detail_text(p, self._db))

    def _update_map_side(self, row: int) -> None:
        if not self._displayed or row >= len(self._displayed):
            return
        self.query_one(MapSidePanel).load_packet(self._displayed, row, self._db)

    def _sync_panel_area(self) -> None:
        self.query_one("#panel_area").display = (
            self._detail_panel_open or self._map_panel_open
        )

    def action_toggle_detail_panel(self) -> None:
        self._detail_panel_open = not self._detail_panel_open
        self.query_one("#detail_side", VerticalScroll).display = self._detail_panel_open
        self._sync_panel_area()
        if self._detail_panel_open:
            row = self.query_one("#packets", DataTable).cursor_row
            self._update_detail_side(row)

    def action_toggle_map_panel(self) -> None:
        self._map_panel_open = not self._map_panel_open
        self.query_one(MapSidePanel).display = self._map_panel_open
        self._sync_panel_area()
        if self._map_panel_open:
            row = self.query_one("#packets", DataTable).cursor_row
            self._update_map_side(row)

    def action_toggle_follow(self) -> None:
        self._follow = not self._follow
        self._set_status(None)

    def action_toggle_layout(self) -> None:
        self._layout_bottom = not self._layout_bottom
        if self._layout_bottom:
            self.add_class("panels-bottom")
        else:
            self.remove_class("panels-bottom")
        self._set_status(None)

    def action_toggle_names(self) -> None:
        self._resolve_path = (self._resolve_path - 1) % 3
        self._rebuild_table()
        self._set_status(None)

    def action_toggle_wrap(self) -> None:
        self._wrap_path = not self._wrap_path
        self._rebuild_table()
        self._set_status(None)

    def action_clear(self) -> None:
        self._all_packets = []
        self._displayed = []
        self._seen_ids = set()
        self._packets_by_id = {}
        self.query_one("#packets", DataTable).clear()
        self.query_one("#detail_content", Static).update("")
        self.query_one(MapSidePanel).clear()
        self._set_status(None)

    def _set_status(self, error: str | None) -> None:
        state = "[PAUSED]" if self._paused else "[LIVE]"
        parts = []
        if self._pkt_filters["observer"]:
            parts.append(f"obs={markup_escape(self._pkt_filters['observer'])}")
        if self._pkt_filters["path_node"]:
            parts.append(f"path={markup_escape(self._pkt_filters['path_node'])}")
        filt = f"  ({', '.join(parts)})" if parts else ""
        names = ("  path:names", "  path:src+hex", "  path:hex")[2 - self._resolve_path]
        wrap = "  wrap:on" if self._wrap_path else ""
        follow = "" if self._follow else "  follow:off"
        layout = "  layout:bottom" if self._layout_bottom else ""
        count = len(self._all_packets)
        now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
        err = f"  ERROR: {error}" if error else ""
        self.query_one("#status", Label).update(
            f"{state}{filt}{names}{wrap}{follow}{layout}  {count} packets  last: {now}{err}"
        )

    def action_refresh(self) -> None:
        self.workers.cancel_all()
        self._poll_worker()

    def action_pause(self) -> None:
        self._paused = not self._paused
        if not self._paused:
            self._rebuild_table()
        self._set_status(None)

    def action_filter(self) -> None:
        def apply_filter(value: dict | None) -> None:
            if value is not None:
                self._pkt_filters = value
            self._rebuild_table()
            self._set_status(None)
        self.app.push_screen(FilterScreen(self._pkt_filters), apply_filter)
```

- [ ] **Step 2: Update `run_monitor()` to launch MeshCoreApp**

Replace the existing `run_monitor` function at the end of `monitor.py`:

```python
def run_monitor(
    region: str,
    packet_provider: "PacketProvider",
    poll_interval: int = 5,
    channels_path: str | None = None,
) -> None:
    """Launch MeshCoreApp with the Monitor tab active (companion tabs optional)."""
    from meshcore_tools.app import MeshCoreApp
    MeshCoreApp(
        region=region,
        packet_provider=packet_provider,
        poll_interval=poll_interval,
        channels_path=channels_path,
    ).run()
```

Keep `PacketMonitorApp` class as-is for reference but it is no longer used by `run_monitor`.

- [ ] **Step 3: Run existing tests**

```bash
pytest -v
```
Expected: all existing tests PASS (no TUI tests; the module import should succeed)

- [ ] **Step 4: Commit**

```bash
git add src/meshcore_tools/monitor.py
git commit -m "feat: extract MonitorTab(TabPane) from PacketMonitorApp"
```

---

### Task 6: chat.py — ChatTab widget

**Files:**
- Create: `src/meshcore_tools/chat.py`

- [ ] **Step 1: Create chat.py**

Create `src/meshcore_tools/chat.py`:

```python
"""ChatTab — companion channel messaging widget."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Button, Input, Label, Static, TabPane

if TYPE_CHECKING:
    from meshcore_tools.companion import CompanionManager

_MAX_MSG_LEN = 133


class _ChannelButton(Button):
    """A tab-strip button representing one channel."""

    def __init__(self, label: str, channel_idx: int) -> None:
        super().__init__(label, id=f"chan_{channel_idx}")
        self.channel_idx = channel_idx


class ChatTab(TabPane):
    """Chat tab: channel strip + message log + input bar."""

    BINDINGS = [
        Binding("enter", "send_message", "Send", show=False),
    ]

    DEFAULT_CSS = """
    ChatTab {
        height: 1fr;
        layout: vertical;
    }
    ChatTab #channel_strip {
        height: 3;
        layout: horizontal;
        background: $panel;
        padding: 0 1;
    }
    ChatTab #channel_strip Button {
        margin-right: 1;
        min-width: 12;
    }
    ChatTab #channel_strip Button.-active-channel {
        border: solid $accent;
    }
    ChatTab #msg_log {
        height: 1fr;
        padding: 1 2;
    }
    ChatTab #input_bar {
        height: 3;
        layout: horizontal;
        padding: 0 1;
        background: $panel;
    }
    ChatTab #msg_input {
        width: 1fr;
    }
    ChatTab #char_count {
        width: 8;
        content-align: right middle;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__("Chat", id="tab_chat")
        # channels: list of {"idx": int, "name": str}
        self._channels: list[dict] = []
        self._active_channel_idx: int = 0
        # messages per channel: {channel_idx: [{"sender": str, "text": str, "ts": int, "status": str}]}
        self._messages: dict[int, list[dict]] = {}

    def compose(self) -> ComposeResult:
        with Container(id="channel_strip"):
            yield Static("No channels", id="no_channels_hint")
        with VerticalScroll(id="msg_log"):
            yield Static("", id="msg_content", markup=True)
        with Container(id="input_bar"):
            yield Input(
                placeholder="type a message…",
                id="msg_input",
                max_length=_MAX_MSG_LEN,
            )
            yield Label(f"0/{_MAX_MSG_LEN}", id="char_count")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "msg_input":
            count = len(event.value)
            self.query_one("#char_count", Label).update(f"{count}/{_MAX_MSG_LEN}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "msg_input":
            self._do_send(event.value)

    def _do_send(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.query_one("#msg_input", Input).value = ""
        self.query_one("#char_count", Label).update(f"0/{_MAX_MSG_LEN}")
        # Add optimistic message with pending status
        msg_entry = {
            "sender": "you",
            "text": text,
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "status": "⏳",
        }
        self._messages.setdefault(self._active_channel_idx, []).append(msg_entry)
        self._refresh_log()
        self._send_worker(self._active_channel_idx, text, msg_entry)

    @work(thread=False, exclusive=False)
    async def _send_worker(
        self, channel_idx: int, text: str, msg_entry: dict
    ) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if manager is None:
            msg_entry["status"] = "✗"
            self._refresh_log()
            return
        success = await manager.send_channel_message(channel_idx, text)
        msg_entry["status"] = "✓" if success else "✗"
        self._refresh_log()

    def _refresh_log(self) -> None:
        msgs = self._messages.get(self._active_channel_idx, [])
        lines: list[str] = []
        for m in msgs:
            ts = datetime.fromtimestamp(m["ts"], tz=timezone.utc).astimezone().strftime("%H:%M")
            sender = m["sender"]
            text = m["text"]
            status = m.get("status", "")
            if sender == "you":
                lines.append(f"[dim]{ts}[/dim]  [bold]you:[/bold]  {text}  {status}")
            else:
                lines.append(f"[dim]{ts}[/dim]  {sender}:  {text}")
        self.query_one("#msg_content", Static).update("\n".join(lines))
        self.query_one("#msg_log", VerticalScroll).scroll_end(animate=False)

    def populate_channels(self, contacts: list[dict]) -> None:
        """Called by MeshCoreApp after companion connects with fresh contacts."""
        # Always include channel 0 (#public); also include contacts for private chat
        self._channels = [{"idx": 0, "name": "#public"}]
        strip = self.query_one("#channel_strip", Container)
        strip.remove_children()
        for ch in self._channels:
            btn = _ChannelButton(ch["name"], ch["idx"])
            if ch["idx"] == self._active_channel_idx:
                btn.add_class("-active-channel")
            strip.mount(btn)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not isinstance(event.button, _ChannelButton):
            return
        self._active_channel_idx = event.button.channel_idx
        for btn in self.query(_ChannelButton):
            btn.remove_class("-active-channel")
        event.button.add_class("-active-channel")
        self._refresh_log()

    def receive_channel_message(
        self,
        channel_idx: int,
        channel_name: str,
        sender: str,
        text: str,
        timestamp: int,
    ) -> None:
        """Called by MeshCoreApp when a ChannelMessage is received."""
        self._messages.setdefault(channel_idx, []).append({
            "sender": sender,
            "text": text,
            "ts": timestamp,
            "status": "",
        })
        if channel_idx == self._active_channel_idx:
            self._refresh_log()

    def clear(self) -> None:
        """Clear all messages (called on disconnect)."""
        self._messages.clear()
        self._channels = []
        self._refresh_log()
```

- [ ] **Step 2: Run tests**

```bash
pytest -v
```
Expected: all PASS (no import errors — `chat.py` imports only Textual, which is installed)

- [ ] **Step 3: Commit**

```bash
git add src/meshcore_tools/chat.py
git commit -m "feat: add ChatTab widget"
```

---

### Task 7: repeaters.py — RepeatersTab widget

**Files:**
- Create: `src/meshcore_tools/repeaters.py`

- [ ] **Step 1: Create repeaters.py**

Create `src/meshcore_tools/repeaters.py`:

```python
"""RepeatersTab — companion repeater management widget."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, TabPane

if TYPE_CHECKING:
    from meshcore_tools.companion import CompanionManager


class _PasswordScreen(ModalScreen[str | None]):
    """Modal prompt for repeater password."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Repeater login[/bold]", markup=True)
            yield Label("Password:")
            yield Input(password=True, id="pwd")
            with Horizontal():
                yield Button("Login", variant="primary", id="btn_ok")
                yield Button("Cancel", id="btn_cancel")

    def on_mount(self) -> None:
        self.query_one("#pwd", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_ok":
            self.dismiss(self.query_one("#pwd", Input).value)

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.dismiss(self.query_one("#pwd", Input).value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class _CmdScreen(ModalScreen[str | None]):
    """Modal prompt for free-text repeater command."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Send command[/bold]", markup=True)
            yield Label("Command:")
            yield Input(placeholder="e.g. uptime", id="cmd")
            with Horizontal():
                yield Button("Send", variant="primary", id="btn_ok")
                yield Button("Cancel", id="btn_cancel")

    def on_mount(self) -> None:
        self.query_one("#cmd", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_ok":
            self.dismiss(self.query_one("#cmd", Input).value)

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.dismiss(self.query_one("#cmd", Input).value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RepeatersTab(TabPane):
    """Repeater management: list on left, commands + output log on right."""

    DEFAULT_CSS = """
    RepeatersTab {
        height: 1fr;
        layout: horizontal;
    }
    RepeatersTab #repeater_list {
        width: 20;
        height: 1fr;
        border-right: solid $accent;
    }
    RepeatersTab #right_pane {
        width: 1fr;
        height: 1fr;
        layout: vertical;
    }
    RepeatersTab #cmd_buttons {
        height: 3;
        layout: horizontal;
        padding: 0 1;
        background: $panel;
    }
    RepeatersTab #cmd_buttons Button {
        margin-right: 1;
    }
    RepeatersTab #output_log {
        height: 1fr;
        padding: 1 2;
    }
    """

    def __init__(self) -> None:
        super().__init__("Repeaters", id="tab_repeaters")
        self._repeaters: list[dict] = []
        self._selected_idx: int | None = None
        self._log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield ListView(id="repeater_list")
        with Container(id="right_pane"):
            with Container(id="cmd_buttons"):
                yield Button("Status", id="btn_status")
                yield Button("Login", id="btn_login")
                yield Button("Cmd", id="btn_cmd")
                yield Button("Trace", id="btn_trace")
                yield Button("Reboot", variant="error", id="btn_reboot")
            with VerticalScroll(id="output_log"):
                yield Static("", id="output_content", markup=True)

    def populate_repeaters(self, contacts: list[dict]) -> None:
        """Called by MeshCoreApp to fill the repeater list from contacts."""
        # Repeaters have role containing "repeater" (case-insensitive) or type indicator
        self._repeaters = [
            c for c in contacts
            if "repeater" in str(c.get("type", "")).lower()
            or "repeater" in str(c.get("role", "")).lower()
        ]
        list_view = self.query_one("#repeater_list", ListView)
        list_view.clear()
        for r in self._repeaters:
            name = r.get("name") or r.get("adv_name") or r.get("public_key", "?")[:8]
            list_view.append(ListItem(Label(name)))
        if self._repeaters:
            self._selected_idx = 0

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self._selected_idx = event.list_view.index

    def _selected_contact(self) -> dict | None:
        if self._selected_idx is None or self._selected_idx >= len(self._repeaters):
            return None
        return self._repeaters[self._selected_idx]

    def _log(self, line: str) -> None:
        ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
        self._log_lines.append(f"[dim]{ts}[/dim]  {line}")
        self.query_one("#output_content", Static).update("\n".join(self._log_lines))
        self.query_one("#output_log", VerticalScroll).scroll_end(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        contact = self._selected_contact()
        if contact is None:
            self._log("[red]No repeater selected[/red]")
            return
        if event.button.id == "btn_status":
            self._run_status(contact)
        elif event.button.id == "btn_login":
            self.app.push_screen(_PasswordScreen(), lambda pwd: self._run_login(contact, pwd))
        elif event.button.id == "btn_cmd":
            self.app.push_screen(_CmdScreen(), lambda cmd: self._run_cmd(contact, cmd))
        elif event.button.id == "btn_trace":
            self._run_trace(contact)
        elif event.button.id == "btn_reboot":
            self._run_reboot(contact)

    @work(thread=False, exclusive=False)
    async def _run_status(self, contact: dict) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("[red]Companion not connected[/red]")
            return
        self._log(f"status → {contact.get('name', '?')} …")
        result = await manager.send_repeater_status(contact)
        self._log(f"status: {result}")

    def _run_login(self, contact: dict, pwd: str | None) -> None:
        if not pwd:
            return
        self._do_login(contact, pwd)

    @work(thread=False, exclusive=False)
    async def _do_login(self, contact: dict, pwd: str) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("[red]Companion not connected[/red]")
            return
        self._log(f"login → {contact.get('name', '?')} …")
        result = await manager.send_repeater_login(contact, pwd)
        self._log(f"login: {result}")

    def _run_cmd(self, contact: dict, cmd: str | None) -> None:
        if not cmd:
            return
        self._do_cmd(contact, cmd)

    @work(thread=False, exclusive=False)
    async def _do_cmd(self, contact: dict, cmd: str) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("[red]Companion not connected[/red]")
            return
        self._log(f"cmd {cmd!r} → {contact.get('name', '?')} …")
        result = await manager.send_repeater_cmd(contact, cmd)
        self._log(f"result: {result}")

    @work(thread=False, exclusive=False)
    async def _run_trace(self, contact: dict) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("[red]Companion not connected[/red]")
            return
        self._log(f"trace → {contact.get('name', '?')} …")
        result = await manager.send_repeater_trace(contact)
        self._log(f"trace: {result}")

    def _run_reboot(self, contact: dict) -> None:
        from textual.widgets import Button
        from textual.screen import ModalScreen
        from textual.app import ComposeResult as _CR

        class _ConfirmReboot(ModalScreen[bool]):
            BINDINGS = [Binding("escape", "cancel", "Cancel")]
            def compose(self) -> _CR:
                with Container():
                    yield Static(f"[bold]Reboot {contact.get('name','?')}?[/bold]", markup=True)
                    with Horizontal():
                        yield Button("Reboot", variant="error", id="btn_yes")
                        yield Button("Cancel", id="btn_no")
            def on_button_pressed(self, event: Button.Pressed) -> None:
                self.dismiss(event.button.id == "btn_yes")
            def action_cancel(self) -> None:
                self.dismiss(False)

        self.app.push_screen(_ConfirmReboot(), lambda confirmed: self._do_reboot(contact, confirmed))

    def _do_reboot(self, contact: dict, confirmed: bool) -> None:
        if not confirmed:
            return
        self._exec_reboot(contact)

    @work(thread=False, exclusive=False)
    async def _exec_reboot(self, contact: dict) -> None:
        manager: CompanionManager | None = getattr(self.app, "companion", None)
        if not manager:
            self._log("[red]Companion not connected[/red]")
            return
        self._log(f"reboot → {contact.get('name', '?')} …")
        result = await manager.send_repeater_reboot(contact)
        self._log(f"reboot: {result}")

    def clear(self) -> None:
        """Clear log and repeater list (called on disconnect)."""
        self._repeaters = []
        self._selected_idx = None
        self._log_lines = []
        self.query_one("#repeater_list", ListView).clear()
        self.query_one("#output_content", Static).update("")
```

- [ ] **Step 2: Run tests**

```bash
pytest -v
```
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add src/meshcore_tools/repeaters.py
git commit -m "feat: add RepeatersTab widget"
```

---

### Task 8: app.py — MeshCoreApp

**Files:**
- Create: `src/meshcore_tools/app.py`

- [ ] **Step 1: Create app.py**

Create `src/meshcore_tools/app.py`:

```python
"""MeshCoreApp — unified TUI entry point with Monitor, Chat, and Repeater tabs."""

from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent

from meshcore_tools.monitor import MonitorTab
from meshcore_tools.connection import (
    ConnectScreen,
    ConnectionConfig,
    load_connection_config,
    save_connection_config,
)

try:
    from meshcore_tools.companion import (
        CompanionManager,
        ChannelMessage,
        CompanionConnected,
        CompanionConnectionError,
        CompanionDisconnected,
        ContactsUpdated,
    )
    from meshcore_tools.chat import ChatTab
    from meshcore_tools.repeaters import RepeatersTab
    COMPANION_AVAILABLE = True
except ImportError:
    COMPANION_AVAILABLE = False

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meshcore_tools.providers import PacketProvider


class MeshCoreApp(App):
    """Unified MeshCore TUI: Monitor + optional Chat and Repeater tabs."""

    TITLE = "MeshCore Tools"

    BINDINGS = [
        Binding("f1", "switch_tab('tab_monitor')", "Monitor"),
        Binding("f2", "switch_tab('tab_chat')", "Chat", show=False),
        Binding("f3", "switch_tab('tab_repeaters')", "Repeaters", show=False),
        Binding("C", "connect", "Connect"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    MeshCoreApp TabbedContent {
        height: 1fr;
    }
    MeshCoreApp TabbedContent ContentSwitcher {
        height: 1fr;
    }
    """

    def __init__(
        self,
        region: str,
        packet_provider: "PacketProvider",
        poll_interval: int = 5,
        channels_path: str | None = None,
    ) -> None:
        super().__init__()
        self._region = region
        self._packet_provider = packet_provider
        self._poll_interval = poll_interval
        self._channels_path = channels_path
        self.companion: CompanionManager | None = None  # set in on_mount if companion available

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            yield MonitorTab(
                region=self._region,
                packet_provider=self._packet_provider,
                poll_interval=self._poll_interval,
                channels_path=self._channels_path,
            )
            if COMPANION_AVAILABLE:
                yield ChatTab()
                yield RepeatersTab()
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"region={self._region}  poll={self._poll_interval}s"
        if not COMPANION_AVAILABLE:
            self.sub_title += "  [companion features require: pip install meshcore-tools[companion]]"
            return
        self.companion = CompanionManager(self)
        config = load_connection_config()
        if config is not None:
            self._do_connect(config)

    # --- Tab switching ---

    def action_switch_tab(self, tab_id: str) -> None:
        if tab_id in ("tab_chat", "tab_repeaters") and not COMPANION_AVAILABLE:
            return
        try:
            self.query_one(TabbedContent).active = tab_id
        except Exception:
            pass

    # --- Connect action ---

    def action_connect(self) -> None:
        if not COMPANION_AVAILABLE:
            return
        current_config = load_connection_config()
        self.push_screen(
            ConnectScreen(current=current_config),
            self._on_connect_screen_result,
        )

    def _on_connect_screen_result(self, config: ConnectionConfig | None) -> None:
        if config is None:
            return
        save_connection_config(config)
        self._do_connect(config)

    def _do_connect(self, config: ConnectionConfig) -> None:
        self._connect_worker(config)

    @work(thread=False, exclusive=True)
    async def _connect_worker(self, config: ConnectionConfig) -> None:
        if self.companion is None:
            return
        await self.companion.disconnect()
        self.sub_title = f"region={self._region}  connecting…"
        await self.companion.connect(config)

    # --- Companion event handlers ---

    def on_companion_connected(self, message: "CompanionConnected") -> None:
        self.sub_title = f"region={self._region}  companion: {message.node_name} [connected]"

    def on_companion_disconnected(self, _: "CompanionDisconnected") -> None:
        self.sub_title = f"region={self._region}  companion: [disconnected]"
        if COMPANION_AVAILABLE:
            try:
                self.query_one(ChatTab).clear()
                self.query_one(RepeatersTab).clear()
            except Exception:
                pass

    def on_companion_connection_error(self, message: "CompanionConnectionError") -> None:
        self.sub_title = f"region={self._region}  companion error: {message.reason}"

    def on_contacts_updated(self, message: "ContactsUpdated") -> None:
        if not COMPANION_AVAILABLE:
            return
        try:
            self.query_one(ChatTab).populate_channels(message.contacts)
            self.query_one(RepeatersTab).populate_repeaters(message.contacts)
        except Exception:
            pass

    def on_channel_message(self, message: "ChannelMessage") -> None:
        if not COMPANION_AVAILABLE:
            return
        try:
            self.query_one(ChatTab).receive_channel_message(
                channel_idx=message.channel_idx,
                channel_name=message.channel_name,
                sender=message.sender,
                text=message.text,
                timestamp=message.timestamp,
            )
        except Exception:
            pass
```

- [ ] **Step 2: Run tests**

```bash
pytest -v
```
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add src/meshcore_tools/app.py
git commit -m "feat: add MeshCoreApp with TabbedContent"
```

---

### Task 9: cli.py — update entry point

**Files:**
- Modify: `src/meshcore_tools/cli.py`

The change: make the subcommand optional so `meshcore-tools` with no args launches `MeshCoreApp`. `monitor` becomes an alias for the same. All other subcommands unchanged.

- [ ] **Step 1: Replace cli.py**

Replace `src/meshcore_tools/cli.py` with:

```python
"""meshcore-tools — CLI entry point."""

import argparse
import os

from meshcore_tools.providers.letsmesh_rest import DEFAULT_REGION


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="meshcore-tools",
        description="meshcore tools — node database and live packet monitor",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = False  # no subcommand → launch MeshCoreApp

    # --- nodes subcommand ---
    nodes_p = sub.add_parser("nodes", help="node database commands")
    nodes_sub = nodes_p.add_subparsers(dest="nodes_command", metavar="SUBCOMMAND")
    nodes_sub.required = True

    update_p = nodes_sub.add_parser("update", help="update database from input files and API")
    update_p.add_argument("--region", default=DEFAULT_REGION, metavar="REGION")

    lookup_p = nodes_sub.add_parser("lookup", help="find node(s) by public key prefix")
    lookup_p.add_argument("prefix", metavar="HEX_PREFIX")

    list_p = nodes_sub.add_parser("list", help="list all nodes")
    list_p.add_argument("--by-key", action="store_true", help="sort by public key instead of name")

    # --- monitor subcommand (alias for default TUI) ---
    monitor_p = sub.add_parser("monitor", help="live packet monitoring TUI (default)")
    monitor_p.add_argument("--region", default=DEFAULT_REGION, metavar="REGION")
    monitor_p.add_argument("--poll", type=int, default=5, metavar="SECONDS",
                           help="polling interval in seconds (default: 5)")
    monitor_p.add_argument("--channels", metavar="FILE", default=None,
                           help="channel keys file for decryption (default: channels.txt if present)")

    args = parser.parse_args()

    if args.command == "nodes":
        if args.nodes_command == "update":
            from meshcore_tools.db import update
            from meshcore_tools.providers.letsmesh_rest import LetsmeshRestProvider
            from meshcore_tools.providers.meshcore_rest import MeshcoreRestProvider
            update(args.region, node_provider=LetsmeshRestProvider(), coord_provider=MeshcoreRestProvider())
        elif args.nodes_command == "lookup":
            from meshcore_tools.nodes import lookup
            lookup(args.prefix)
        elif args.nodes_command == "list":
            from meshcore_tools.nodes import list_nodes
            list_nodes(by_key=args.by_key)

    else:
        # Default (no subcommand) and "monitor" both launch MeshCoreApp
        region = getattr(args, "region", DEFAULT_REGION)
        poll = getattr(args, "poll", 5)
        channels = getattr(args, "channels", None)
        if channels is None and os.path.exists("channels.txt"):
            channels = "channels.txt"
        from meshcore_tools.app import MeshCoreApp
        from meshcore_tools.providers.letsmesh_rest import LetsmeshRestProvider
        MeshCoreApp(
            region=region,
            packet_provider=LetsmeshRestProvider(),
            poll_interval=poll,
            channels_path=channels,
        ).run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run tests**

```bash
pytest -v
```
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add src/meshcore_tools/cli.py
git commit -m "feat: update CLI — default launch MeshCoreApp, monitor as alias"
```

---

### Task 10: Verify end-to-end import and smoke test

- [ ] **Step 1: Verify all modules import cleanly**

```bash
python -c "
from meshcore_tools.connection import ConnectionConfig, load_connection_config, save_connection_config, ConnectScreen
from meshcore_tools.companion import CompanionManager, ChannelMessage, CompanionConnected
from meshcore_tools.monitor import MonitorTab, run_monitor
from meshcore_tools.chat import ChatTab
from meshcore_tools.repeaters import RepeatersTab
from meshcore_tools.app import MeshCoreApp, COMPANION_AVAILABLE
print('COMPANION_AVAILABLE:', COMPANION_AVAILABLE)
print('all imports OK')
"
```
Expected output:
```
COMPANION_AVAILABLE: False
all imports OK
```
(False because meshcore is not installed in the dev environment without `pip install meshcore-tools[companion]`)

- [ ] **Step 2: Run full test suite**

```bash
pytest -v
```
Expected: all tests PASS

- [ ] **Step 3: Verify CLI help**

```bash
python -m meshcore_tools.cli --help
```
Expected: help text showing `COMMAND` is optional with `nodes` and `monitor` listed.

- [ ] **Step 4: Final commit**

```bash
git add -u
git commit -m "feat: companion TUI — complete implementation"
```
