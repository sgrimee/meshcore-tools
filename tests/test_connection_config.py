"""Tests for ConnectionConfig load/save."""

import tomllib
from unittest.mock import MagicMock, patch

from meshcore_tools.connection import (
    ConnectionConfig,
    connection_label,
    format_ble_devices,
    list_serial_ports,
    load_connection_config,
    load_connection_history,
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


def test_config_file_is_toml(tmp_path):
    cfg = ConnectionConfig(type="tcp", host="127.0.0.1", port=4000)
    save_connection_config(cfg, config_dir=tmp_path)
    raw = tomllib.loads((tmp_path / "config.toml").read_text())
    assert raw["connection"]["type"] == "tcp"
    assert raw["connection"]["host"] == "127.0.0.1"
    assert raw["connection"]["port"] == 4000


def test_load_ignores_unknown_keys(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[connection]\ntype = "tcp"\nhost = "1.2.3.4"\nport = 1234\nfuture_field = "x"\n'
    )
    loaded = load_connection_config(config_dir=tmp_path)
    assert loaded is not None
    assert loaded.host == "1.2.3.4"


# --- legacy BLE history migration tests ---


def test_legacy_ble_history_macos_uuid_migrated(tmp_path):
    """Legacy entries with macOS UUID in ble_name are migrated to ble_address."""
    addr = "20F10AA2-D97A-D4F9-CFED-484C7576B8D4"
    (tmp_path / "config.toml").write_text(
        f'[connection]\nhistory = [{{type = "ble", ble_name = "{addr}"}}]\n'
    )
    history = load_connection_history(config_dir=tmp_path)
    assert len(history) == 1
    assert history[0].ble_address == addr
    assert history[0].ble_name is None


def test_legacy_ble_history_linux_mac_migrated(tmp_path):
    """Legacy entries with Linux MAC in ble_name are migrated to ble_address."""
    addr = "AA:BB:CC:DD:EE:FF"
    (tmp_path / "config.toml").write_text(
        f'[connection]\nhistory = [{{type = "ble", ble_name = "{addr}"}}]\n'
    )
    history = load_connection_history(config_dir=tmp_path)
    assert len(history) == 1
    assert history[0].ble_address == addr
    assert history[0].ble_name is None


def test_ble_history_with_name_not_migrated(tmp_path):
    """Entries with a human-readable ble_name are left untouched."""
    (tmp_path / "config.toml").write_text(
        '[connection]\nhistory = [{type = "ble", ble_name = "MeshCore-ABC", ble_address = "AA:BB:CC:DD:EE:FF"}]\n'
    )
    history = load_connection_history(config_dir=tmp_path)
    assert history[0].ble_name == "MeshCore-ABC"
    assert history[0].ble_address == "AA:BB:CC:DD:EE:FF"


def test_connection_label_legacy_ble_shows_address_suffix(tmp_path):
    """Legacy BLE entry (no name) shows last 12 chars of address."""
    cfg = ConnectionConfig(type="ble", ble_address="20F10AA2-D97A-D4F9-CFED-484C7576B8D4")
    label = connection_label(cfg)
    assert label == "BLE: …484C7576B8D4"


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
    """Devices whose name does not start with MeshCore are excluded."""
    devices = [_make_ble_device("SomeOtherDevice", "AA:BB:CC:DD:EE:FF")]
    assert format_ble_devices(devices) == []


def test_format_ble_devices_value_is_address():
    """Value stored in Select is the MAC address for direct connection."""
    devices = [_make_ble_device("MeshCore-abc", "11:22:33:44:55:66")]
    result = format_ble_devices(devices)
    assert result == [("MeshCore-abc  11:22:33:44:55:66", "11:22:33:44:55:66")]


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
    assert result[0] == ("MeshCore-1  AA:AA:AA:AA:AA:AA", "AA:AA:AA:AA:AA:AA")
    assert result[1] == ("MeshCore-2  CC:CC:CC:CC:CC:CC", "CC:CC:CC:CC:CC:CC")


# --- ConnectScreen structural tests ---


def test_connect_screen_has_three_sections():
    """ConnectScreen.compose must yield tcp-section, serial-section, and ble-section."""
    import inspect
    from meshcore_tools.connection import ConnectScreen
    src = inspect.getsource(ConnectScreen.compose)
    assert '"tcp-section"' in src or "'tcp-section'" in src
    assert '"serial-section"' in src or "'serial-section'" in src
    assert '"ble-section"' in src or "'ble-section'" in src


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
