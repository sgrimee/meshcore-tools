"""Connection configuration: ConnectionConfig, config I/O, and ConnectScreen modal."""

from __future__ import annotations

import asyncio
import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Label, LoadingIndicator, Select, Static
from textual.containers import Container
from textual import work

import serial.tools.list_ports

try:
    from bleak import BleakScanner
    _BLEAK_AVAILABLE = True
except ImportError:
    _BLEAK_AVAILABLE = False


_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "meshcore-tools"


@dataclass
class ConnectionConfig:
    """Stores connection parameters for a companion device."""

    type: str  # "tcp", "serial", or "ble"
    host: str | None = None
    port: int | None = None
    device: str | None = None
    ble_name: str | None = None
    ble_pin: str | None = None
    # Not serialized — holds a freshly scanned BLEDevice for reliable connect.
    ble_device: object | None = None


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
        ble_pin=data.get("ble_pin"),
    )


def save_connection_config(
    config: ConnectionConfig, config_dir: Path = _DEFAULT_CONFIG_DIR
) -> None:
    """Persist config as JSON, creating parent directories as needed."""
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "connection.json"
    data = {k: v for k, v in asdict(config).items() if v is not None and k != "ble_device"}
    path.write_text(json.dumps(data, indent=2))
    save_connection_history(config, config_dir)


_HISTORY_MAX = 5


def _config_key(c: ConnectionConfig) -> tuple[str, str | None, int | None, str | None, str | None]:
    return (c.type, c.host, c.port, c.device, c.ble_name)


def save_connection_history(
    config: ConnectionConfig, config_dir: Path = _DEFAULT_CONFIG_DIR
) -> None:
    """Prepend config to the recent-connections list, deduplicating by identity."""
    existing = load_connection_history(config_dir)
    deduped = [h for h in existing if _config_key(h) != _config_key(config)]
    history = ([config] + deduped)[:_HISTORY_MAX]
    config_dir.mkdir(parents=True, exist_ok=True)
    data = [
        {k: v for k, v in asdict(h).items() if v is not None and k != "ble_device"}
        for h in history
    ]
    (config_dir / "history.json").write_text(json.dumps(data, indent=2))


def load_connection_history(config_dir: Path = _DEFAULT_CONFIG_DIR) -> list[ConnectionConfig]:
    """Return recent connections, most recent first. Returns [] on any error."""
    path = config_dir / "history.json"
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text())
        return [
            ConnectionConfig(
                type=e.get("type", "tcp"),
                host=e.get("host"),
                port=e.get("port"),
                device=e.get("device"),
                ble_name=e.get("ble_name"),
                ble_pin=e.get("ble_pin"),
            )
            for e in entries
            if isinstance(e, dict)
        ]
    except Exception:
        return []


def connection_label(c: ConnectionConfig) -> str:
    """Human-readable one-liner for display in the Recent section."""
    if c.type == "ble":
        return f"BLE: {c.ble_name or '?'}"
    if c.type == "tcp":
        return f"TCP: {c.host or '?'}:{c.port or 5000}"
    if c.type == "serial":
        return f"Serial: {c.device or '?'}"
    return c.type


def list_serial_ports() -> list[tuple[str, str]]:
    """Return (display_label, port_path) pairs for available serial ports, sorted by port."""
    ports = serial.tools.list_ports.comports()
    return [(f"{port} — {desc}", port) for port, desc, _ in sorted(ports)]


def format_ble_devices(devices: list) -> list[tuple[str, str]]:
    """Return (display_label, address) pairs for MeshCore BLE devices.

    Filters to devices whose name starts with 'MeshCore'. Devices with no name are skipped.
    """
    result = []
    for d in devices:
        if d.name and d.name.startswith("MeshCore"):
            result.append((f"{d.name}  {d.address}", d.address))
    return result


async def _known_ble_devices() -> list[tuple[str, str]]:
    """Return (display_label, address) for MeshCore devices known to BlueZ.

    Queries `bluetoothctl devices` so paired/cached devices show up even when
    they are not actively advertising.  Returns [] if bluetoothctl is absent.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl", "devices",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        result = []
        for line in stdout.decode().splitlines():
            parts = line.strip().split(" ", 2)  # "Device AA:BB:CC name"
            if len(parts) == 3 and parts[0] == "Device":
                address, name = parts[1], parts[2]
                if name.startswith("MeshCore"):
                    result.append((f"{name}  {address}", address))
        return result
    except Exception:
        return []


async def _scan_ble_subprocess() -> list[tuple[str, str]]:
    """Run BLE scan in a child process to catch macOS SIGABRT on permission denial.

    Returns [(label, address)] for discovered MeshCore devices.
    Raises PermissionError when the OS kills the child with SIGABRT/SIGKILL,
    which on macOS indicates Bluetooth permission has not been granted to the
    terminal app.
    """
    script = (
        b"import asyncio, json\n"
        b"from bleak import BleakScanner\n"
        b"async def _scan():\n"
        b"    devs = await BleakScanner.discover(timeout=5.0)\n"
        b"    print(json.dumps([[d.name, d.address] for d in devs\n"
        b"        if d.name and d.name.startswith('MeshCore')]))\n"
        b"asyncio.run(_scan())\n"
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(input=script), timeout=12.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("BLE scan timed out")
    if proc.returncode in (-6, -9):  # SIGABRT or SIGKILL — Bluetooth permission denied
        raise PermissionError(
            "Bluetooth permission denied — in System Settings → Privacy & Security → "
            "Bluetooth, enable access for your terminal app, then restart it."
        )
    if proc.returncode != 0:
        raise RuntimeError(f"BLE scan process exited with code {proc.returncode}")
    data = json.loads(stdout or b"[]")
    return [(f"{name}  {addr}", addr) for name, addr in data]


def _ble_scan_error(exc: Exception) -> str:
    """Plain-English error message for BLE scan failures."""
    msg = str(exc)
    if "InProgress" in msg:
        return "Scan already in progress — wait a moment and try again."
    if "NotPermitted" in msg or "NotAuthorized" in msg:
        return "Bluetooth permission denied.\nTry: sudo usermod -aG bluetooth $USER"
    if "org.bluez.Error" in msg:
        return msg.split("] ", 1)[-1] if "] " in msg else msg
    return msg


class _RecentButton(Button):
    """A quick-connect button for a previously used connection."""

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(connection_label(config), variant="default")
        self.config = config


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
    ConnectScreen LoadingIndicator {
        height: 3;
    }
    ConnectScreen #ble-status {
        margin-top: 1;
        color: $warning;
    }
    ConnectScreen #recent-section {
        margin-bottom: 1;
        height: auto;
    }
    ConnectScreen #recent-buttons {
        layout: vertical;
        height: auto;
    }
    ConnectScreen #recent-buttons Button {
        margin-bottom: 1;
        width: 100%;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current: ConnectionConfig | None = None) -> None:
        super().__init__()
        self._current = current or ConnectionConfig(type="tcp")
        self._ble_devices: dict[str, object] = {}  # address → BLEDevice

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Connect to companion device[/bold]", markup=True)
            with Collapsible(title="Recent connections", id="recent-section", collapsed=False):
                with Container(id="recent-buttons"):
                    pass  # populated in on_mount
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
                with Container(id="ble-pin-section"):
                    yield Label("PIN (optional, for pairing):")
                    yield Input(
                        value=self._current.ble_pin or "",
                        placeholder="leave blank if not required",
                        id="ble_pin",
                    )
            with Container(id="buttons"):
                yield Button("Connect", variant="primary", id="btn_connect")
                yield Button("Cancel", id="btn_cancel")

    def on_mount(self) -> None:
        self.query_one("#ble-loading").display = False
        self.query_one("#ble-select").display = False
        self.query_one("#ble-pin-section").display = False
        self._show_section(self._current.type)
        if self._current.type == "serial":
            self._populate_serial_ports()
        history = load_connection_history()
        recent_section = self.query_one("#recent-section")
        if history:
            recent_buttons = self.query_one("#recent-buttons")
            first_btn: _RecentButton | None = None
            for cfg in history:
                btn = _RecentButton(cfg)
                recent_buttons.mount(btn)
                if first_btn is None:
                    first_btn = btn
            if first_btn is not None:
                self.call_after_refresh(first_btn.focus)
        else:
            recent_section.display = False

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
        elif event.select.id == "ble-select":
            self.query_one("#ble-pin-section").display = (event.value is not Select.NULL)
            self._update_connect_button()
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
        status.update("Scanning for BLE devices…")

        try:
            if not _BLEAK_AVAILABLE:
                raise ImportError(
                    "bleak not installed. Run: pip install meshcore-tools[companion]"
                )
            if platform.system() == "Darwin":
                # On macOS, run the scan in a child process so that a SIGABRT
                # from CoreBluetooth (Bluetooth permission denied) is caught and
                # turned into a readable error instead of crashing the app.
                options = await _scan_ble_subprocess()
            else:
                devices = await BleakScanner.discover(timeout=5.0)
                # Build options and keep BLEDevice objects for reliable connect
                self._ble_devices = {}
                options = []
                for d in devices:
                    if d.name and d.name.startswith("MeshCore"):
                        options.append((f"{d.name}  {d.address}", d.address))
                        self._ble_devices[d.address] = d
            # Merge in paired/cached devices from BlueZ that weren't advertising
            known = await _known_ble_devices()
            seen = {addr for _, addr in options}
            options += [entry for entry in known if entry[1] not in seen]
            if options:
                ble_sel.set_options(options)
                ble_sel.value = options[0][1]
                ble_sel.display = True
                self.query_one("#ble-pin-section").display = True
                status.update("")
            else:
                status.update("No MeshCore devices found.")
                scan_btn.display = True
        except ImportError as exc:
            status.update(str(exc))
            scan_btn.display = True
        except Exception as exc:
            status.update(_ble_scan_error(exc))
            scan_btn.display = True
        finally:
            loading.display = False

        self._update_connect_button()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if isinstance(event.button, _RecentButton):
            self.dismiss(event.button.config)
            return
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
            val = self.query_one("#serial-select", Select).value
            if val is Select.NULL:
                return
            config = ConnectionConfig(type="serial", device=str(val))
        elif conn_type == "ble":
            val = self.query_one("#ble-select", Select).value
            if val is Select.NULL:
                return
            addr = str(val)
            pin = self.query_one("#ble_pin", Input).value.strip() or None
            config = ConnectionConfig(
                type="ble",
                ble_name=addr,
                ble_pin=pin,
                ble_device=self._ble_devices.get(addr),
            )
        else:
            return
        self.dismiss(config)
