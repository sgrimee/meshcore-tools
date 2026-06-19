"""User settings persistence — XDG-compliant TOML config file."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path


def _default_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "meshcore-tools"


def _ensure_config_dir(config_dir: Path | None) -> Path:
    return config_dir if config_dir is not None else _default_config_dir()


def load_config(config_dir: Path | None = None) -> dict:
    """Load config from config.toml; return empty dict if missing or corrupt."""
    config_dir = _ensure_config_dir(config_dir)
    path = config_dir / "config.toml"
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        return {}


def save_config(data: dict, config_dir: Path | None = None) -> None:
    """Write *data* to config.toml, creating the directory if needed."""
    config_dir = _ensure_config_dir(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "config.toml"
    path.write_text(_to_toml(data))


def get_blacklist(config_dir: Path | None = None) -> list[str]:
    """Return the node blacklist from config.toml, or [] if not set."""
    config = load_config(config_dir)
    val = config.get("filtering", {}).get("blacklist", [])
    return [str(x) for x in val] if isinstance(val, list) else []


def get_region(config_dir: Path | None = None) -> str | None:
    """Return the saved default region, or None if not set."""
    config = load_config(config_dir)
    return config.get("general", {}).get("region")


def save_region(region: str, config_dir: Path | None = None) -> None:
    """Persist *region* as the default region in config.toml."""
    config = load_config(config_dir)
    config.setdefault("general", {})["region"] = region
    save_config(config, config_dir)


def get_packet_source_type(config_dir: Path | None = None) -> str:
    """Return configured packet source type: 'letsmesh' (default) or 'mqtt'."""
    config = load_config(config_dir)
    return config.get("packet_source", {}).get("type", "letsmesh")


DEFAULT_MQTT_SERVER = "luxmesh"

# Built-in MQTT server profiles, used when a profile isn't defined in
# config.toml's [mqtt.<name>] tables. "luxmesh" ships configured out of the
# box so packet_source.type = "mqtt" works with no further setup.
_BUILTIN_MQTT_SERVERS: dict[str, dict] = {
    "luxmesh": {
        "broker": "live.luxmesh.lu",
        "port": 1883,
        "topic": "meshcore/LUX/+/packets",
    },
}


def get_mqtt_server_name(config_dir: Path | None = None) -> str:
    """Return the selected MQTT server profile name (packet_source.mqtt_server).

    Defaults to "luxmesh" — the public live.luxmesh.lu broker.
    """
    config = load_config(config_dir)
    return config.get("packet_source", {}).get("mqtt_server", DEFAULT_MQTT_SERVER)


def get_mqtt_config(config_dir: Path | None = None, server: str | None = None) -> dict:
    """Return MQTT connection parameters for one named server profile.

    Several MQTT broker profiles can be defined under config.toml's
    [mqtt.<name>] tables; packet_source.mqtt_server selects which one is
    active (default: "luxmesh", which works with no config.toml entry at
    all — see _BUILTIN_MQTT_SERVERS). Pass *server* to look up a specific
    profile regardless of what's selected in config.toml.

    Credentials are read from secrets.toml's [mqtt."<broker-hostname>"]
    table, keyed by the resolved broker hostname (not the profile name) so
    that switching mqtt_server to a profile pointing at an already-known
    broker picks up its saved credentials automatically. Falls back to the
    profile's own username/password keys in config.toml for backwards
    compatibility.

    Keys: broker, port (int, default 1883), topic (default 'meshcore/raw'),
    username (optional), password (optional).
    """
    from meshcore_tools.passwords import load_mqtt_credentials

    config = load_config(config_dir)
    name = server if server is not None else get_mqtt_server_name(config_dir)
    profile = config.get("mqtt", {}).get(name)
    if not isinstance(profile, dict):
        profile = _BUILTIN_MQTT_SERVERS.get(name, {})
    broker = profile.get("broker", "localhost")
    cfg: dict = {
        "broker": broker,
        "port": int(profile.get("port", 1883)),
        "topic": profile.get("topic", "meshcore/raw"),
    }
    creds = load_mqtt_credentials(broker, config_dir)
    username = creds.get("username") or profile.get("username")
    password = creds.get("password") or profile.get("password")
    if username is not None:
        cfg["username"] = username
    if password is not None:
        cfg["password"] = password
    return cfg


# ---------------------------------------------------------------------------
# Minimal TOML writer (no third-party dependency needed for writing)
# ---------------------------------------------------------------------------

def _to_toml(data: dict) -> str:
    """Serialize a dict of arbitrarily nested tables to TOML text."""
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_value(v)}")
    for section, inner in tables.items():
        _emit_table(lines, [section], inner)
    lines.append("")
    return "\n".join(lines)


def _emit_table(lines: list[str], path: list[str], table: dict) -> None:
    """Recursively emit a [a.b.c] table header plus its scalar keys, then nested subtables."""
    scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
    subtables = {k: v for k, v in table.items() if isinstance(v, dict)}
    if scalars or not subtables:
        if lines:
            lines.append("")
        lines.append(f"[{'.'.join(path)}]")
        for k, v in scalars.items():
            lines.append(f"{k} = {_toml_value(v)}")
    for name, sub in subtables.items():
        _emit_table(lines, path + [name], sub)


def _toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(i) for i in v) + "]"
    if isinstance(v, dict):
        inner = ", ".join(f"{k} = {_toml_value(val)}" for k, val in v.items())
        return "{" + inner + "}"
    raise TypeError(f"Unsupported TOML value type: {type(v)}")
