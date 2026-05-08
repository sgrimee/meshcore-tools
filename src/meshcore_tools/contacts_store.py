"""Contact persistence in contacts.toml.

Stores adv_name and type keyed by public_key. Path and location data are
ephemeral and re-learned from live mesh advertisements after import.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from meshcore_tools.config import _default_config_dir

_CONTACTS_FILE = "contacts.toml"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _write_contacts(contacts: dict[str, dict], config_dir: Path) -> None:
    """Write contacts.toml atomically. contacts is {pubkey: {adv_name, type}}."""
    lines = [
        "# meshcore-tools contacts\n",
        "\n",
        "[contacts]\n",
    ]
    for pubkey, entry in contacts.items():
        adv_name = _escape(entry.get("adv_name", ""))
        ctype = int(entry.get("type", 0))
        lines.append(f'"{_escape(pubkey)}" = {{ adv_name = "{adv_name}", type = {ctype} }}\n')

    path = config_dir / _CONTACTS_FILE
    tmp = path.with_suffix(".toml.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("".join(lines))
    os.replace(tmp, path)


def load_contacts(config_dir: Path | None = None) -> dict[str, dict]:
    """Return contacts keyed by public_key. Returns {} if file missing or corrupt."""
    if config_dir is None:
        config_dir = _default_config_dir()
    path = config_dir / _CONTACTS_FILE
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text())
        return dict(data.get("contacts", {}))
    except Exception:
        return {}


def persist_contact(contact: dict, config_dir: Path | None = None) -> bool:
    """Upsert a contact by public_key. Returns True if newly added, False if already existed."""
    pubkey = contact.get("public_key", "")
    if not pubkey:
        return False
    if config_dir is None:
        config_dir = _default_config_dir()
    contacts = load_contacts(config_dir)
    is_new = pubkey not in contacts
    contacts[pubkey] = {
        "adv_name": contact.get("adv_name", ""),
        "type": contact.get("type", 0),
    }
    _write_contacts(contacts, config_dir)
    return is_new
