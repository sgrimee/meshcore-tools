"""Password storage for repeater logins.

Passwords are stored in plaintext on disk. The file is always created with 600
permissions (owner read/write only) to limit exposure.

  ~/.config/meshcore-tools/secrets.toml — default_password + [passwords] table

On first run after an upgrade the old settings.toml (default_password field) and
passwords.toml ([passwords] table) are transparently migrated to secrets.toml.
"""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path

_SECRETS_FILE = "secrets.toml"


def _default_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "meshcore-tools"


def _write_secure(path: Path, content: str) -> None:
    """Write content to path with 600 permissions (owner read/write only)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Open with O_CREAT so it is created with restricted mode even before chmod
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    # Enforce 600 regardless of umask
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _escape_toml_string(value: str) -> str:
    """Return value escaped for use inside a TOML double-quoted string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _serialize_secrets(data: dict) -> str:
    """Serialize secrets dict to TOML text with a warning header."""
    lines = [
        "# meshcore-tools secrets\n",
        "# WARNING: This file contains plaintext passwords. Keep it private.\n",
    ]
    dp = data.get("default_password")
    if dp is not None:
        lines.append("\n")
        lines.append(f'default_password = "{_escape_toml_string(dp)}"\n')
    passwords = data.get("passwords", {})
    if passwords:
        lines.append("\n[passwords]\n")
        for key, value in passwords.items():
            lines.append(f'"{_escape_toml_string(key)}" = "{_escape_toml_string(value)}"\n')
    return "".join(lines)


def _load_secrets(config_dir: Path) -> dict:
    """Load secrets.toml, migrating from old files on first use. Returns {} on error."""
    path = config_dir / _SECRETS_FILE
    if path.exists():
        try:
            return tomllib.loads(path.read_text())
        except Exception:
            return {}
    return _migrate_old_password_files(config_dir)


def _save_secrets(data: dict, config_dir: Path) -> None:
    """Write *data* to secrets.toml with 600 permissions."""
    _write_secure(config_dir / _SECRETS_FILE, _serialize_secrets(data))


def _migrate_old_password_files(config_dir: Path) -> dict:
    """One-time migration: read default_password from settings.toml and passwords
    from passwords.toml, combine, write to secrets.toml, and return the merged dict.
    """
    data: dict = {}

    # Migrate default_password from the old settings.toml
    settings_path = config_dir / "settings.toml"
    if settings_path.exists():
        try:
            old = tomllib.loads(settings_path.read_text())
            dp = old.get("default_password")
            if dp:
                data["default_password"] = str(dp)
        except Exception:
            pass

    # Migrate per-repeater passwords from the old passwords.toml
    pw_path = config_dir / "passwords.toml"
    if pw_path.exists():
        try:
            old = tomllib.loads(pw_path.read_text())
            pws = {k: v for k, v in old.get("passwords", {}).items() if isinstance(v, str)}
            if pws:
                data["passwords"] = pws
        except Exception:
            pass

    if data:
        _save_secrets(data, config_dir)

    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_default_password(config_dir: Path | None = None) -> str | None:
    """Return default_password from secrets.toml, or None if unset."""
    if config_dir is None:
        config_dir = _default_config_dir()
    data = _load_secrets(config_dir)
    value = data.get("default_password")
    return str(value) if value else None


def save_default_password(password: str, config_dir: Path | None = None) -> None:
    """Persist default_password to secrets.toml with 600 permissions.

    WARNING: The password is stored in plaintext.
    """
    if config_dir is None:
        config_dir = _default_config_dir()
    data = _load_secrets(config_dir)
    data["default_password"] = password
    _save_secrets(data, config_dir)


def load_repeater_passwords(config_dir: Path | None = None) -> dict[str, str]:
    """Return per-repeater passwords keyed by node public_key. Returns {} on any error."""
    if config_dir is None:
        config_dir = _default_config_dir()
    data = _load_secrets(config_dir)
    return {k: v for k, v in data.get("passwords", {}).items() if isinstance(v, str)}


def save_repeater_password(
    node_key: str,
    password: str,
    config_dir: Path | None = None,
) -> None:
    """Persist a per-repeater password to secrets.toml with 600 permissions.

    WARNING: Passwords are stored in plaintext.
    """
    if config_dir is None:
        config_dir = _default_config_dir()
    data = _load_secrets(config_dir)
    data.setdefault("passwords", {})[node_key] = password
    _save_secrets(data, config_dir)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def get_prefilled_password(
    contact: dict,
    config_dir: Path | None = None,
) -> str | None:
    """Return the best available pre-fill password for a contact.

    Precedence: per-repeater saved password > default_password > None.
    """
    if config_dir is None:
        config_dir = _default_config_dir()
    node_key = contact.get("public_key", "")
    data = _load_secrets(config_dir)
    if node_key:
        pws = {k: v for k, v in data.get("passwords", {}).items() if isinstance(v, str)}
        if node_key in pws:
            return pws[node_key]
    value = data.get("default_password")
    return str(value) if value else None
