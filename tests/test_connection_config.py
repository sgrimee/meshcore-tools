"""Tests for ConnectionConfig load/save."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from meshcore_tools.connection import (
    ConnectionConfig,
    format_ble_devices,
    list_serial_ports,
    load_connection_config,
    save_connection_config,
)


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


# --- list_serial_ports tests ---


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


# --- format_ble_devices tests ---


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


# --- ConnectScreen structural tests ---


def test_connect_screen_has_three_sections():
    """ConnectScreen.compose must yield tcp-section, serial-section, and ble-section."""
    import inspect
    from meshcore_tools.connection import ConnectScreen
    src = inspect.getsource(ConnectScreen.compose)
    assert '"tcp-section"' in src or "'tcp-section'" in src
    assert '"serial-section"' in src or "'serial-section'" in src
    assert '"ble-section"' in src or "'ble-section'" in src
