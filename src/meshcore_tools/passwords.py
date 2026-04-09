"""Password and channel key storage.

Secrets are stored in plaintext on disk. Files are created with 600
permissions (owner read/write only) to limit exposure.

- ~/.config/meshcore-tools/secrets.toml — default_password, per-repeater passwords,
  and channel keys for GroupText/GroupData decryption
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

    Top-level scalar keys are written first, then [passwords], then [channels].
    """
    lines = [
        "# meshcore-tools secrets\n",
        "# WARNING: Secrets are stored in plaintext. Keep this file private.\n",
        "\n",
    ]
    for key, value in data.items():
        if key in ("passwords", "channels"):
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
    channels = data.get("channels", {})
    if channels:
        lines.append("\n[channels]\n")
        for name, key_hex in channels.items():
            lines.append(
                f'"{_escape_toml_string(name)}" = "{_escape_toml_string(key_hex)}"\n'
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


# ---------------------------------------------------------------------------
# secrets.toml — channel keys
# ---------------------------------------------------------------------------


def load_channels_from_secrets(
    config_dir: Path | None = None,
) -> list[tuple[str, bytes]]:
    """Return channel keys from secrets.toml as [(name, key_bytes), ...].

    Entries with a 32-char hex key are decoded directly. Entries whose name
    starts with '#' and have an empty key have their key derived automatically
    via SHA256("#name")[:16]. Malformed entries are skipped with a warning.
    """
    from meshcore_tools.channels import PUBLIC_CHANNEL_KEY, PUBLIC_CHANNEL_LABEL, _derive_hashtag_key
    import sys

    if config_dir is None:
        config_dir = _default_config_dir()
    data = _load_secrets(config_dir)
    raw = data.get("channels", {})
    result: list[tuple[str, bytes]] = []
    for name, key_hex in raw.items():
        if not isinstance(name, str):
            continue
        if name.lower() == "public":
            result.append((PUBLIC_CHANNEL_LABEL, PUBLIC_CHANNEL_KEY))
            continue
        if not key_hex and name.startswith("#"):
            result.append((name, _derive_hashtag_key(name[1:])))
            continue
        if not isinstance(key_hex, str) or len(key_hex) != 32:
            print(
                f"Warning: secrets.toml [channels]: skipping {name!r}"
                " — expected a 32-char hex key.",
                file=sys.stderr,
            )
            continue
        try:
            result.append((name, bytes.fromhex(key_hex)))
        except ValueError:
            print(
                f"Warning: secrets.toml [channels]: skipping {name!r}"
                " — invalid hex key.",
                file=sys.stderr,
            )
    return result


def persist_channel_to_secrets(
    name: str,
    key_bytes: bytes,
    config_dir: Path | None = None,
) -> bool:
    """Add a channel key to secrets.toml if not already present.

    Returns True if the channel was newly added, False if it already existed.
    Deduplicates by both name and key bytes.
    """
    if config_dir is None:
        config_dir = _default_config_dir()
    data = _load_secrets(config_dir)
    channels = data.setdefault("channels", {})
    existing_keys = {bytes.fromhex(v) for v in channels.values() if isinstance(v, str) and len(v) == 32}
    if name in channels or key_bytes in existing_keys:
        return False
    channels[name] = key_bytes.hex()
    _write_secrets(data, config_dir)
    return True
