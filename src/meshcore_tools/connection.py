"""Connection configuration: ConnectionConfig, config I/O, and ConnectScreen modal."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, LoadingIndicator, Select, Static
from textual.containers import Container
from textual import work

import serial.tools.list_ports

try:
    from bleak import BleakScanner
    from bleak.exc import BleakDBusError, BleakError
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
        elif event.button.id == "btn_connect":
            self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        conn_type = str(self.query_one("#conn_type", Select).value)
        port_str = self.query_one("#port", Input).value.strip()
        if conn_type == "tcp":
            try:
                port = int(port_str)
            except ValueError:
                self.query_one("#port", Input).focus()
                return  # don't dismiss — keep modal open for correction
        else:
            port = None
        config = ConnectionConfig(
            type=conn_type,
            host=self.query_one("#host", Input).value.strip() or None,
            port=port,
            device=self.query_one("#device", Input).value.strip() or None,
            ble_name=self.query_one("#ble_name", Input).value.strip() or None,
        )
        self.dismiss(config)
