"""Tests for config.py — XDG-compliant settings persistence."""



from meshcore_tools.config import (
    get_blacklist,
    get_mqtt_config,
    get_packet_source_type,
    get_region,
    load_config,
    save_region,
    save_config,
)


def test_load_config_missing_file(tmp_path):
    assert load_config(tmp_path) == {}


def test_load_config_corrupt_toml(tmp_path):
    (tmp_path / "config.toml").write_text("not valid toml ][")
    assert load_config(tmp_path) == {}


def test_save_and_load_config(tmp_path):
    save_config({"general": {"region": "EU"}}, tmp_path)
    result = load_config(tmp_path)
    assert result == {"general": {"region": "EU"}}


def test_save_config_creates_directory(tmp_path):
    deep = tmp_path / "a" / "b" / "meshcore-tools"
    save_config({"general": {"region": "US"}}, deep)
    assert (deep / "config.toml").exists()


def test_save_config_preserves_other_keys(tmp_path):
    save_config({"general": {"region": "LUX", "other": "value"}}, tmp_path)
    result = load_config(tmp_path)
    assert result["general"]["other"] == "value"
    assert result["general"]["region"] == "LUX"


def test_get_region_returns_none_when_missing(tmp_path):
    assert get_region(tmp_path) is None


def test_get_region_returns_saved_value(tmp_path):
    save_config({"general": {"region": "AP"}}, tmp_path)
    assert get_region(tmp_path) == "AP"


def test_save_region_creates_file(tmp_path):
    save_region("NA", tmp_path)
    assert (tmp_path / "config.toml").exists()
    assert get_region(tmp_path) == "NA"


def test_save_region_overwrites_previous(tmp_path):
    save_region("LUX", tmp_path)
    save_region("EU", tmp_path)
    assert get_region(tmp_path) == "EU"


def test_save_region_preserves_other_settings(tmp_path):
    save_config({"general": {"region": "LUX", "foo": "bar"}}, tmp_path)
    save_region("EU", tmp_path)
    result = load_config(tmp_path)
    assert result["general"]["foo"] == "bar"
    assert result["general"]["region"] == "EU"


def test_get_blacklist_empty_when_missing(tmp_path):
    assert get_blacklist(tmp_path) == []


def test_get_blacklist_returns_list(tmp_path):
    (tmp_path / "config.toml").write_text('[filtering]\nblacklist = ["Valto Rasta", "abc123"]\n')
    assert get_blacklist(tmp_path) == ["Valto Rasta", "abc123"]


def test_get_blacklist_empty_section(tmp_path):
    (tmp_path / "config.toml").write_text("[filtering]\n")
    assert get_blacklist(tmp_path) == []


def test_save_region_preserves_blacklist(tmp_path):
    """save_region() must not corrupt a blacklist array already in config.toml."""
    (tmp_path / "config.toml").write_text('[general]\nregion = "LUX"\n\n[filtering]\nblacklist = ["Valto Rasta"]\n')
    save_region("EU", tmp_path)
    assert get_region(tmp_path) == "EU"
    assert get_blacklist(tmp_path) == ["Valto Rasta"]


def test_toml_list_round_trip(tmp_path):
    save_config({"filtering": {"blacklist": ["A", "B"]}}, tmp_path)
    result = load_config(tmp_path)
    assert result["filtering"]["blacklist"] == ["A", "B"]


def test_xdg_config_home_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_region("XDG", config_dir=None)  # uses env var path
    expected_dir = tmp_path / "meshcore-tools"
    assert (expected_dir / "config.toml").exists()
    assert get_region(config_dir=None) == "XDG"


# ---------------------------------------------------------------------------
# get_packet_source_type
# ---------------------------------------------------------------------------

def test_get_packet_source_type_default(tmp_path):
    assert get_packet_source_type(tmp_path) == "letsmesh"


def test_get_packet_source_type_mqtt(tmp_path):
    (tmp_path / "config.toml").write_text('[packet_source]\ntype = "mqtt"\n')
    assert get_packet_source_type(tmp_path) == "mqtt"


def test_get_packet_source_type_letsmesh_explicit(tmp_path):
    (tmp_path / "config.toml").write_text('[packet_source]\ntype = "letsmesh"\n')
    assert get_packet_source_type(tmp_path) == "letsmesh"


# ---------------------------------------------------------------------------
# get_mqtt_config
# ---------------------------------------------------------------------------

def test_get_mqtt_config_defaults(tmp_path):
    cfg = get_mqtt_config(tmp_path)
    assert cfg["broker"] == "localhost"
    assert cfg["port"] == 1883
    assert cfg["topic"] == "meshcore/raw"
    assert "username" not in cfg
    assert "password" not in cfg


def test_get_mqtt_config_all_fields(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[mqtt]\nbroker = "mqtt.example.com"\nport = 8883\n'
        'topic = "mesh/raw"\nusername = "alice"\npassword = "s3cr3t"\n'
    )
    cfg = get_mqtt_config(tmp_path)
    assert cfg["broker"] == "mqtt.example.com"
    assert cfg["port"] == 8883
    assert cfg["topic"] == "mesh/raw"
    assert cfg["username"] == "alice"
    assert cfg["password"] == "s3cr3t"


def test_get_mqtt_config_partial_fields(tmp_path):
    (tmp_path / "config.toml").write_text('[mqtt]\nbroker = "broker.local"\n')
    cfg = get_mqtt_config(tmp_path)
    assert cfg["broker"] == "broker.local"
    assert cfg["port"] == 1883
    assert "username" not in cfg
