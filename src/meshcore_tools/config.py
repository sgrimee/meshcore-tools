"""User settings persistence — XDG-compliant TOML config file."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path


def _default_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "meshcore-tools"


def load_settings(config_dir: Path | None = None) -> dict:
    """Load settings from settings.toml; return empty dict if missing or corrupt."""
    if config_dir is None:
        config_dir = _default_config_dir()
    path = config_dir / "settings.toml"
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        return {}


def save_settings(data: dict, config_dir: Path | None = None) -> None:
    """Write *data* to settings.toml, creating the directory if needed."""
    if config_dir is None:
        config_dir = _default_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "settings.toml"
    path.write_text(_to_toml(data))


def get_blacklist(config_dir: Path | None = None) -> list[str]:
    """Return the node blacklist from settings.toml, or [] if not set."""
    settings = load_settings(config_dir)
    val = settings.get("filtering", {}).get("blacklist", [])
    return [str(x) for x in val] if isinstance(val, list) else []


def get_region(config_dir: Path | None = None) -> str | None:
    """Return the saved default region, or None if not set."""
    settings = load_settings(config_dir)
    return settings.get("general", {}).get("region")


def save_region(region: str, config_dir: Path | None = None) -> None:
    """Persist *region* as the default region in settings.toml."""
    settings = load_settings(config_dir)
    settings.setdefault("general", {})["region"] = region
    save_settings(settings, config_dir)


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
    raise TypeError(f"Unsupported TOML value type: {type(v)}")
