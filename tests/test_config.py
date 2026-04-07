"""Tests for config.py — XDG-compliant settings persistence."""

from pathlib import Path

import pytest

from meshcore_tools.config import (
    get_region,
    load_settings,
    save_region,
    save_settings,
)


def test_load_settings_missing_file(tmp_path):
    assert load_settings(tmp_path) == {}


def test_load_settings_corrupt_toml(tmp_path):
    (tmp_path / "settings.toml").write_text("not valid toml ][")
    assert load_settings(tmp_path) == {}


def test_save_and_load_settings(tmp_path):
    save_settings({"general": {"region": "EU"}}, tmp_path)
    result = load_settings(tmp_path)
    assert result == {"general": {"region": "EU"}}


def test_save_settings_creates_directory(tmp_path):
    deep = tmp_path / "a" / "b" / "meshcore-tools"
    save_settings({"general": {"region": "US"}}, deep)
    assert (deep / "settings.toml").exists()


def test_save_settings_preserves_other_keys(tmp_path):
    save_settings({"general": {"region": "LUX", "other": "value"}}, tmp_path)
    result = load_settings(tmp_path)
    assert result["general"]["other"] == "value"
    assert result["general"]["region"] == "LUX"


def test_get_region_returns_none_when_missing(tmp_path):
    assert get_region(tmp_path) is None


def test_get_region_returns_saved_value(tmp_path):
    save_settings({"general": {"region": "AP"}}, tmp_path)
    assert get_region(tmp_path) == "AP"


def test_save_region_creates_file(tmp_path):
    save_region("NA", tmp_path)
    assert (tmp_path / "settings.toml").exists()
    assert get_region(tmp_path) == "NA"


def test_save_region_overwrites_previous(tmp_path):
    save_region("LUX", tmp_path)
    save_region("EU", tmp_path)
    assert get_region(tmp_path) == "EU"


def test_save_region_preserves_other_settings(tmp_path):
    save_settings({"general": {"region": "LUX", "foo": "bar"}}, tmp_path)
    save_region("EU", tmp_path)
    result = load_settings(tmp_path)
    assert result["general"]["foo"] == "bar"
    assert result["general"]["region"] == "EU"


def test_xdg_config_home_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_region("XDG", config_dir=None)  # uses env var path
    expected_dir = tmp_path / "meshcore-tools"
    assert (expected_dir / "settings.toml").exists()
    assert get_region(config_dir=None) == "XDG"
