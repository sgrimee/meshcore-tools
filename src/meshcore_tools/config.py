"""User settings persistence — XDG-compliant TOML config file.

Non-secret settings are stored in config.toml:
  [general]                region
  [filtering]              blacklist
  [connection]             last-used connection parameters
  [[connection.history]]   recent connections (array of tables)

Secret settings (passwords) are stored separately in secrets.toml — see passwords.py.

On first run after an upgrade from a previous version the non-secret fields in the
old settings.toml are transparently migrated to config.toml.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path


def _default_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "meshcore-tools"


def load_config(config_dir: Path | None = None) -> dict:
    """Load non-secret settings from config.toml; return {} if missing or corrupt.

    On the first call after an upgrade, transparently migrates non-secret data from
    the old settings.toml into config.toml.
    """
    if config_dir is None:
        config_dir = _default_config_dir()
    path = config_dir / "config.toml"
    if not path.exists():
        _migrate_settings_to_config(config_dir)
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
    (config_dir / "config.toml").write_text(_to_toml(data))


def _migrate_settings_to_config(config_dir: Path) -> None:
    """One-time migration: copy non-secret data from settings.toml → config.toml."""
    old = config_dir / "settings.toml"
    if not old.exists():
        return
    try:
        data = tomllib.loads(old.read_text())
    except Exception:
        return
    data.pop("default_password", None)  # secrets belong in secrets.toml
    if data:
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.toml").write_text(_to_toml(data))


def get_blacklist(config_dir: Path | None = None) -> list[str]:
    """Return the node blacklist from config.toml, or [] if not set."""
    cfg = load_config(config_dir)
    val = cfg.get("filtering", {}).get("blacklist", [])
    return [str(x) for x in val] if isinstance(val, list) else []


def get_region(config_dir: Path | None = None) -> str | None:
    """Return the saved default region, or None if not set."""
    return load_config(config_dir).get("general", {}).get("region")


def save_region(region: str, config_dir: Path | None = None) -> None:
    """Persist *region* as the default region in config.toml."""
    cfg = load_config(config_dir)
    cfg.setdefault("general", {})["region"] = region
    save_config(cfg, config_dir)


# ---------------------------------------------------------------------------
# TOML serializer — supports nested tables and arrays of tables
# ---------------------------------------------------------------------------


def _to_toml(data: dict) -> str:
    """Serialize a nested dict to TOML text."""
    lines: list[str] = []
    _emit_section(data, "", lines)
    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")
    return "\n".join(lines)


def _emit_section(data: dict, prefix: str, lines: list[str]) -> None:
    """Append TOML key=value lines for *data* under the given key prefix."""
    # 1. Scalar values and plain arrays (not arrays-of-tables)
    for k, v in data.items():
        if not isinstance(v, dict) and not _is_aot(v):
            lines.append(f"{k} = {_toml_value(v)}")
    # 2. Nested tables → [section] headers
    for k, v in data.items():
        if isinstance(v, dict):
            section = f"{prefix}.{k}" if prefix else k
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[{section}]")
            _emit_section(v, section, lines)
    # 3. Arrays of tables → [[section]] headers
    for k, v in data.items():
        if _is_aot(v):
            section = f"{prefix}.{k}" if prefix else k
            for item in v:
                if lines and lines[-1] != "":
                    lines.append("")
                lines.append(f"[[{section}]]")
                _emit_section(item, section, lines)


def _is_aot(v: object) -> bool:
    """True if *v* is a non-empty list of dicts (TOML array-of-tables candidate)."""
    return isinstance(v, list) and bool(v) and all(isinstance(i, dict) for i in v)


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
