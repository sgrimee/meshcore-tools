"""Password storage for repeater logins.

Passwords are stored in plaintext on disk. Files are created with 600
permissions (owner read/write only) to limit exposure.

- ~/.config/meshcore-tools/settings.toml  — default_password field
- ~/.config/meshcore-tools/passwords.toml — per-repeater passwords table
"""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path

_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "meshcore-tools"
_SETTINGS_FILE = "settings.toml"
_PASSWORDS_FILE = "passwords.toml"


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


# ---------------------------------------------------------------------------
# settings.toml — default_password
# ---------------------------------------------------------------------------


def load_default_password(config_dir: Path = _DEFAULT_CONFIG_DIR) -> str | None:
    """Return default_password from settings.toml, or None if unset."""
    path = config_dir / _SETTINGS_FILE
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text())
        value = data.get("default_password")
        return str(value) if value else None
    except Exception:
        return None


def save_default_password(
    password: str, config_dir: Path = _DEFAULT_CONFIG_DIR
) -> None:
    """Persist default_password to settings.toml with 600 permissions.

    WARNING: The password is stored in plaintext.
    """
    path = config_dir / _SETTINGS_FILE
    existing: dict = {}
    if path.exists():
        try:
            existing = tomllib.loads(path.read_text())
        except Exception:
            pass
    existing["default_password"] = password
    lines = [
        "# meshcore-tools settings\n",
        "# WARNING: This file may contain plaintext passwords. Keep it private.\n",
        "\n",
    ]
    for key, value in existing.items():
        escaped = _escape_toml_string(str(value))
        lines.append(f'{key} = "{escaped}"\n')
    _write_secure(path, "".join(lines))


# ---------------------------------------------------------------------------
# passwords.toml — per-repeater passwords
# ---------------------------------------------------------------------------


def load_repeater_passwords(
    config_dir: Path = _DEFAULT_CONFIG_DIR,
) -> dict[str, str]:
    """Return per-repeater passwords keyed by node public_key. Returns {} on any error."""
    path = config_dir / _PASSWORDS_FILE
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text())
        return {
            k: v
            for k, v in data.get("passwords", {}).items()
            if isinstance(v, str)
        }
    except Exception:
        return {}


def save_repeater_password(
    node_key: str,
    password: str,
    config_dir: Path = _DEFAULT_CONFIG_DIR,
) -> None:
    """Persist a per-repeater password to passwords.toml with 600 permissions.

    WARNING: Passwords are stored in plaintext.
    """
    passwords = load_repeater_passwords(config_dir)
    passwords[node_key] = password
    path = config_dir / _PASSWORDS_FILE
    lines = [
        "# meshcore-tools repeater passwords\n",
        "# WARNING: Passwords are stored in plaintext. Protect this file.\n",
        "\n",
        "[passwords]\n",
    ]
    for key, value in passwords.items():
        lines.append(f'"{_escape_toml_string(key)}" = "{_escape_toml_string(value)}"\n')
    _write_secure(path, "".join(lines))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def get_prefilled_password(
    contact: dict,
    config_dir: Path = _DEFAULT_CONFIG_DIR,
) -> str | None:
    """Return the best available pre-fill password for a contact.

    Precedence: per-repeater saved password > default_password > None.
    """
    node_key = contact.get("public_key", "")
    if node_key:
        passwords = load_repeater_passwords(config_dir)
        if node_key in passwords:
            return passwords[node_key]
    return load_default_password(config_dir)
