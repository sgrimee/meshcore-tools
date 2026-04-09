"""Password storage for repeater logins.

Passwords are stored in plaintext on disk. Files are created with 600
permissions (owner read/write only) to limit exposure.

- ~/.config/meshcore-tools/secrets.toml — default_password + per-repeater passwords
"""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path

from meshcore_tools.config import _default_config_dir

_SECRETS_FILE = "secrets.toml"


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


def _load_secrets(config_dir: Path) -> dict:
    """Load secrets.toml; return empty dict if missing or corrupt."""
    path = config_dir / _SECRETS_FILE
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except Exception:
        return {}


def _write_secrets(data: dict, config_dir: Path) -> None:
    """Serialize and write secrets.toml with 0o600 permissions.

    Top-level scalar keys are written first, then the [passwords] table.
    """
    lines = [
        "# meshcore-tools secrets\n",
        "# WARNING: Passwords are stored in plaintext. Keep this file private.\n",
        "\n",
    ]
    for key, value in data.items():
        if key == "passwords":
            continue
        escaped = _escape_toml_string(str(value))
        lines.append(f'{key} = "{escaped}"\n')
    passwords = data.get("passwords", {})
    if passwords:
        lines.append("\n[passwords]\n")
        for key, value in passwords.items():
            lines.append(
                f'"{_escape_toml_string(key)}" = "{_escape_toml_string(value)}"\n'
            )
    path = config_dir / _SECRETS_FILE
    _write_secure(path, "".join(lines))


# ---------------------------------------------------------------------------
# secrets.toml — default_password
# ---------------------------------------------------------------------------


def load_default_password(config_dir: Path | None = None) -> str | None:
    """Return default_password from secrets.toml, or None if unset."""
    if config_dir is None:
        config_dir = _default_config_dir()
    data = _load_secrets(config_dir)
    value = data.get("default_password")
    return str(value) if value else None


def save_default_password(
    password: str, config_dir: Path | None = None
) -> None:
    """Persist default_password to secrets.toml with 600 permissions.

    WARNING: The password is stored in plaintext.
    """
    if config_dir is None:
        config_dir = _default_config_dir()
    data = _load_secrets(config_dir)
    data["default_password"] = password
    _write_secrets(data, config_dir)


# ---------------------------------------------------------------------------
# secrets.toml — per-repeater passwords
# ---------------------------------------------------------------------------


def load_repeater_passwords(
    config_dir: Path | None = None,
) -> dict[str, str]:
    """Return per-repeater passwords keyed by node public_key. Returns {} on any error."""
    if config_dir is None:
        config_dir = _default_config_dir()
    data = _load_secrets(config_dir)
    return {
        k: v
        for k, v in data.get("passwords", {}).items()
        if isinstance(v, str)
    }


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
    _write_secrets(data, config_dir)


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
    if node_key:
        passwords = load_repeater_passwords(config_dir)
        if node_key in passwords:
            return passwords[node_key]
    return load_default_password(config_dir)
