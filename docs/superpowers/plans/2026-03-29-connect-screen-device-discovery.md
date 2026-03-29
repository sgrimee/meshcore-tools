# ConnectScreen Device Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual text inputs in `ConnectScreen` with dynamic sections: a `Select` of live serial ports and a BLE scanner with spinner that discovers nearby MeshCore devices.

**Architecture:** All changes confined to `src/meshcore_tools/connection.py` and `tests/test_connection_config.py`. Two pure helper functions (`list_serial_ports`, `format_ble_devices`) are extracted for testability. `ConnectScreen` gains three mutually-exclusive CSS-toggled sections for TCP/Serial/BLE, a Textual `@work` async BLE scan worker, and connect-button state management.

**Tech Stack:** Textual 8.x (`Select.set_options`, `LoadingIndicator`, `@work`), `serial.tools.list_ports` (pyserial), `bleak.BleakScanner` (optional, guarded by `_BLEAK_AVAILABLE`).

---

### Task 1: Add helper functions and their tests

**Files:**
- Modify: `src/meshcore_tools/connection.py`
- Modify: `tests/test_connection_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_connection_config.py`:

```python
from unittest.mock import MagicMock, patch
from meshcore_tools.connection import list_serial_ports, format_ble_devices


# --- list_serial_ports ---

def test_list_serial_ports_empty():
    with patch("meshcore_tools.connection.serial.tools.list_ports.comports", return_value=[]):
        assert list_serial_ports() == []


def test_list_serial_ports_sorted_and_formatted():
    fake = [
        ("/dev/ttyUSB1", "CP2102", "USB VID:PID"),
        ("/dev/ttyUSB0", "FTDI", "USB VID:PID"),
    ]
    with patch("meshcore_tools.connection.serial.tools.list_ports.comports", return_value=fake):
        result = list_serial_ports()
    assert result == [
        ("/dev/ttyUSB0 — FTDI", "/dev/ttyUSB0"),
        ("/dev/ttyUSB1 — CP2102", "/dev/ttyUSB1"),
    ]


# --- format_ble_devices ---

def _make_ble_device(name, address):
    d = MagicMock()
    d.name = name
    d.address = address
    return d


def test_format_ble_devices_empty():
    assert format_ble_devices([]) == []


def test_format_ble_devices_filters_non_meshcore():
    devices = [_make_ble_device("SomeOtherDevice", "AA:BB:CC:DD:EE:FF")]
    assert format_ble_devices(devices) == []


def test_format_ble_devices_includes_meshcore():
    devices = [_make_ble_device("MeshCore-abc", "11:22:33:44:55:66")]
    result = format_ble_devices(devices)
    assert result == [("MeshCore-abc (11:22:33:44:55:66)", "MeshCore-abc")]


def test_format_ble_devices_skips_none_name():
    devices = [_make_ble_device(None, "11:22:33:44:55:66")]
    assert format_ble_devices(devices) == []


def test_format_ble_devices_multiple():
    devices = [
        _make_ble_device("MeshCore-1", "AA:AA:AA:AA:AA:AA"),
        _make_ble_device("Unrelated", "BB:BB:BB:BB:BB:BB"),
        _make_ble_device("MeshCore-2", "CC:CC:CC:CC:CC:CC"),
    ]
    result = format_ble_devices(devices)
    assert len(result) == 2
    assert result[0] == ("MeshCore-1 (AA:AA:AA:AA:AA:AA)", "MeshCore-1")
    assert result[1] == ("MeshCore-2 (CC:CC:CC:CC:CC:CC)", "MeshCore-2")
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /path/to/meshcore-tools
uv run pytest tests/test_connection_config.py::test_list_serial_ports_empty -v
```

Expected: `ImportError` or `AttributeError` — `list_serial_ports` not defined yet.

- [ ] **Step 3: Add imports and helper functions to connection.py**

At the top of `src/meshcore_tools/connection.py`, add after existing imports:

```python
import serial.tools.list_ports

try:
    from bleak import BleakScanner
    from bleak.exc import BleakDBusError, BleakError
    _BLEAK_AVAILABLE = True
except ImportError:
    _BLEAK_AVAILABLE = False
```

Add these two functions after `save_connection_config`:

```python
def list_serial_ports() -> list[tuple[str, str]]:
    """Return (display_label, port_path) pairs for available serial ports, sorted by port."""
    ports = serial.tools.list_ports.comports()
    return [(f"{port} — {desc}", port) for port, desc, _ in sorted(ports)]


def format_ble_devices(devices: list) -> list[tuple[str, str]]:
    """Return (display_label, device_name) pairs for MeshCore BLE devices."""
    result = []
    for d in devices:
        if d.name and d.name.startswith("MeshCore"):
            result.append((f"{d.name} ({d.address})", d.name))
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/test_connection_config.py -k "serial_ports or ble_devices" -v
```

Expected: all 7 new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/meshcore_tools/connection.py tests/test_connection_config.py
git commit -m "feat: add list_serial_ports and format_ble_devices helpers"
```

---

### Task 2: Rework ConnectScreen.compose() with sections

**Files:**
- Modify: `src/meshcore_tools/connection.py`

- [ ] **Step 1: Write a structural test**

Add to `tests/test_connection_config.py`:

```python
def test_connect_screen_has_three_sections():
    """ConnectScreen.compose must yield tcp-section, serial-section, and ble-section."""
    import inspect
    from meshcore_tools.connection import ConnectScreen
    src = inspect.getsource(ConnectScreen.compose)
    assert '"tcp-section"' in src or "'tcp-section'" in src
    assert '"serial-section"' in src or "'serial-section'" in src
    assert '"ble-section"' in src or "'ble-section'" in src
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/test_connection_config.py::test_connect_screen_has_three_sections -v
```

Expected: FAIL — sections not yet defined.

- [ ] **Step 3: Replace ConnectScreen.compose() and update imports**

Update the import line in `connection.py` to add `LoadingIndicator`:

```python
from textual.widgets import Button, Input, Label, LoadingIndicator, Select, Static
```

Add `work` import:

```python
from textual.worker import work
```

Replace the entire `compose` method:

```python
def compose(self) -> ComposeResult:
    with Container():
        yield Static("[bold]Connect to companion device[/bold]", markup=True)
        yield Label("Connection type:")
        yield Select(
            [("TCP", "tcp"), ("Serial", "serial"), ("BLE", "ble")],
            value=self._current.type,
            id="conn_type",
            allow_blank=False,
        )
        with Container(id="tcp-section"):
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
        with Container(id="serial-section"):
            yield Label("Serial port:")
            yield Select([], id="serial-select", allow_blank=True)
            yield Button("Refresh", id="btn_serial_refresh", variant="default")
        with Container(id="ble-section"):
            yield Button("Scan for BLE devices", id="btn_ble_scan", variant="default")
            yield LoadingIndicator(id="ble-loading")
            yield Select([], id="ble-select", allow_blank=True)
            yield Static("", id="ble-status", markup=False)
        with Container(id="buttons"):
            yield Button("Connect", variant="primary", id="btn_connect")
            yield Button("Cancel", id="btn_cancel")
```

Update `DEFAULT_CSS` to add styles for new widgets (add after the existing `Button` rule):

```python
    ConnectScreen LoadingIndicator {
        height: 3;
    }
    ConnectScreen #ble-status {
        margin-top: 1;
        color: $warning;
    }
```

- [ ] **Step 4: Run structural test**

```
uv run pytest tests/test_connection_config.py::test_connect_screen_has_three_sections -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```
uv run pytest tests/test_connection_config.py -v
```

Expected: all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add src/meshcore_tools/connection.py tests/test_connection_config.py
git commit -m "feat: rework ConnectScreen.compose with TCP/Serial/BLE sections"
```

---

### Task 3: Implement section switching, serial population, and connect-button state

**Files:**
- Modify: `src/meshcore_tools/connection.py`

- [ ] **Step 1: Write structural tests**

Add to `tests/test_connection_config.py`:

```python
def test_connect_screen_on_mount_calls_show_section():
    import inspect
    from meshcore_tools.connection import ConnectScreen
    src = inspect.getsource(ConnectScreen.on_mount)
    assert "_show_section" in src


def test_connect_screen_has_populate_serial():
    import inspect
    from meshcore_tools.connection import ConnectScreen
    src = inspect.getsource(ConnectScreen._populate_serial_ports)
    assert "list_serial_ports" in src
    assert "serial-select" in src


def test_connect_screen_update_connect_button_checks_type():
    import inspect
    from meshcore_tools.connection import ConnectScreen
    src = inspect.getsource(ConnectScreen._update_connect_button)
    assert '"tcp"' in src
    assert '"serial"' in src
    assert '"ble"' in src
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/test_connection_config.py -k "on_mount or populate_serial or update_connect" -v
```

Expected: FAIL — methods not yet defined.

- [ ] **Step 3: Implement section switching and serial population**

Replace the existing `on_button_pressed` and `_submit` methods (and everything between `compose` and the end of the class) with:

```python
def on_mount(self) -> None:
    self.query_one("#ble-loading").display = False
    self.query_one("#ble-select").display = False
    self._show_section(self._current.type)
    if self._current.type == "serial":
        self._populate_serial_ports()

def _show_section(self, conn_type: str) -> None:
    self.query_one("#tcp-section").display = (conn_type == "tcp")
    self.query_one("#serial-section").display = (conn_type == "serial")
    self.query_one("#ble-section").display = (conn_type == "ble")
    self._update_connect_button()

def on_select_changed(self, event: Select.Changed) -> None:
    if event.select.id == "conn_type":
        self._show_section(str(event.value))
        if str(event.value) == "serial":
            self._populate_serial_ports()
    else:
        self._update_connect_button()

def on_input_changed(self, event: Input.Changed) -> None:
    if event.input.id == "host":
        self._update_connect_button()

def _populate_serial_ports(self) -> None:
    ports = list_serial_ports()
    sel = self.query_one("#serial-select", Select)
    if ports:
        sel.set_options(ports)
        sel.disabled = False
    else:
        sel.set_options([("No ports found", "")])
        sel.disabled = True
    self._update_connect_button()

def _update_connect_button(self) -> None:
    conn_type = str(self.query_one("#conn_type", Select).value)
    btn = self.query_one("#btn_connect", Button)
    if conn_type == "tcp":
        btn.disabled = not bool(self.query_one("#host", Input).value.strip())
    elif conn_type == "serial":
        sel = self.query_one("#serial-select", Select)
        btn.disabled = sel.value is Select.NULL or sel.disabled
    elif conn_type == "ble":
        sel = self.query_one("#ble-select", Select)
        btn.disabled = sel.value is Select.NULL or not sel.display
    else:
        btn.disabled = True

@work
async def _scan_ble(self) -> None:
    scan_btn = self.query_one("#btn_ble_scan", Button)
    loading = self.query_one("#ble-loading", LoadingIndicator)
    ble_sel = self.query_one("#ble-select", Select)
    status = self.query_one("#ble-status", Static)

    scan_btn.display = False
    loading.display = True
    status.update("")

    try:
        if not _BLEAK_AVAILABLE:
            raise ImportError(
                "bleak not installed. Run: pip install meshcore-tools[companion]"
            )
        devices = await BleakScanner.discover(timeout=5.0)
        options = format_ble_devices(devices)
        if options:
            ble_sel.set_options(options)
            ble_sel.display = True
        else:
            status.update("No MeshCore devices found.")
            scan_btn.display = True
    except ImportError as exc:
        status.update(str(exc))
        scan_btn.display = True
    except Exception as exc:
        status.update(
            f"Bluetooth error: {exc}\nTry: sudo usermod -aG bluetooth $USER"
        )
        scan_btn.display = True
    finally:
        loading.display = False

    self._update_connect_button()

def on_button_pressed(self, event: Button.Pressed) -> None:
    if event.button.id == "btn_cancel":
        self.dismiss(None)
    elif event.button.id == "btn_connect":
        self._submit()
    elif event.button.id == "btn_serial_refresh":
        self._populate_serial_ports()
    elif event.button.id == "btn_ble_scan":
        self._scan_ble()

def action_cancel(self) -> None:
    self.dismiss(None)

def _submit(self) -> None:
    conn_type = str(self.query_one("#conn_type", Select).value)
    if conn_type == "tcp":
        port_str = self.query_one("#port", Input).value.strip()
        try:
            port = int(port_str)
        except ValueError:
            self.query_one("#port", Input).focus()
            return
        config = ConnectionConfig(
            type="tcp",
            host=self.query_one("#host", Input).value.strip() or None,
            port=port,
        )
    elif conn_type == "serial":
        config = ConnectionConfig(
            type="serial",
            device=str(self.query_one("#serial-select", Select).value),
        )
    elif conn_type == "ble":
        config = ConnectionConfig(
            type="ble",
            ble_name=str(self.query_one("#ble-select", Select).value),
        )
    else:
        return
    self.dismiss(config)
```

- [ ] **Step 4: Run structural tests**

```
uv run pytest tests/test_connection_config.py -k "on_mount or populate_serial or update_connect" -v
```

Expected: all 3 new tests PASS.

- [ ] **Step 5: Run full test suite**

```
uv run pytest tests/test_connection_config.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/meshcore_tools/connection.py tests/test_connection_config.py
git commit -m "feat: implement ConnectScreen section switching, serial discovery, BLE scan worker"
```

---

### Task 4: Smoke-test the UI manually

**Files:** none (manual verification step)

- [ ] **Step 1: Launch the TUI and open ConnectScreen**

```
uv run meshcore-tools
```

Press `c` or use the connect action to open the connect modal.

- [ ] **Step 2: Verify Serial section**

Switch type to "Serial". Confirm:
- A `Select` appears populated with serial ports (or "No ports found" if none)
- "Refresh" button is present
- "Connect" button is disabled until a port is selected

- [ ] **Step 3: Verify BLE section**

Switch type to "BLE". Confirm:
- "Scan for BLE devices" button appears
- Clicking it shows a spinner for ~5 seconds
- Results appear in a `Select` (or error/no-devices message)
- On Linux without bluetooth group: error message includes `sudo usermod -aG bluetooth $USER`

- [ ] **Step 4: Verify TCP section**

Switch type to "TCP". Confirm host/port inputs appear. Connect button disabled until host filled.

- [ ] **Step 5: Final commit if any last-minute fixes were needed**

```bash
git add -p
git commit -m "fix: <describe any fixups from manual testing>"
```
