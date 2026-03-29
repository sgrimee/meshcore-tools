"""Connection configuration: ConnectionConfig, config I/O, and ConnectScreen modal."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static
from textual.containers import Container


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
                allow_blank=False,
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
