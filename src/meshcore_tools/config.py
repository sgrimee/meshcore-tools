"""User settings persistence — XDG-compliant TOML config file."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path


def _default_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "meshcore-tools"


def load_config(config_dir: Path | None = None) -> dict:
    """Load config from config.toml; return empty dict if missing or corrupt."""
    if config_dir is None:
        config_dir = _default_config_dir()
    path = config_dir / "config.toml"
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        return {}


def save_config(data: dict, config_dir: Path | None = None) -> None:
    """Write *data* to config.toml, creating the directory if needed."""
    if config_dir is None:
        config_dir = _default_config_dir()
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


def get_mqtt_config(config_dir: Path | None = None) -> dict:
    """Return MQTT connection parameters from config.toml [mqtt] section.

    Keys: broker, port (int, default 1883), topic (default 'meshcore/raw'),
    username (optional), password (optional).
    """
    config = load_config(config_dir)
    mqtt = config.get("mqtt", {})
    cfg: dict = {
        "broker": mqtt.get("broker", "localhost"),
        "port": int(mqtt.get("port", 1883)),
        "topic": mqtt.get("topic", "meshcore/raw"),
    }
    if "username" in mqtt:
        cfg["username"] = mqtt["username"]
    if "password" in mqtt:
        cfg["password"] = mqtt["password"]
    return cfg


# ---------------------------------------------------------------------------
# Minimal TOML writer (no third-party dependency needed for writing)
# ---------------------------------------------------------------------------

def _to_toml(data: dict) -> str:
    """Serialize a shallow dict-of-dicts to TOML text."""
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_value(v)}")
    for section, inner in tables.items():
        if lines:
            lines.append("")
        lines.append(f"[{section}]")
        for k, v in inner.items():
            lines.append(f"{k} = {_toml_value(v)}")
    lines.append("")
    return "\n".join(lines)


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
