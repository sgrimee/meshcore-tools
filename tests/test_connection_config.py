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
