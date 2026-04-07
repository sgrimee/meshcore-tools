"""Channel key management and GroupText/GroupData decryption.

Supports three channel types:
  - Public channel  : fixed well-known 16-byte key
  - Hashtag channels: key = SHA256("#name")[:16]  (derived automatically)
  - Named channels  : explicit 16-byte key supplied by the user

The channels file is compatible with the output of 'get_channels' in meshcore-cli:
  0: Public [8b3387e9c5cdea6ac9e5edbaa115cd72]
  1: #wardriving [e3c26491e9cd321e3a6be50d57d54acf]
  #myhashtagchannel          <- bare hashtag, key derived automatically

Decryption:
  GroupText/GroupData payloads are AES-128-ECB encrypted.
  Decrypted plaintext: [uint32 LE timestamp][1-byte flags]["sender_name: message"]
  The 2-byte MAC is HMAC-SHA256(ciphertext, channel_key)[:2].
"""

from __future__ import annotations

import hashlib
import hmac
import re
import struct
import sys

from Crypto.Cipher import AES  # pycryptodome

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PUBLIC_CHANNEL_KEY = bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72")
PUBLIC_CHANNEL_LABEL = "Public"

# Pattern: optional "N: " prefix, then name, then [32hexchars]
_GET_CHANNELS_RE = re.compile(
    r"^(?:\d+:\s+)?(.+?)\s+\[([0-9a-fA-F]{32})\]\s*$"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_channels(path: str) -> list[tuple[str, bytes]]:
    """Parse a channels file and return [(label, key_bytes), ...].

    Accepts 'get_channels' output pasted verbatim, bare hashtag names,
    and lines starting with '# ' or just '#' (treated as comments).
    """
    channels: list[tuple[str, bytes]] = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return channels

    bad_lines: list[int] = []
    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        # "# " (hash-space) = comment; "#" alone = comment
        if line == "#" or line.startswith("# "):
            continue

        # get_channels format: [N: ] Name [32hexchars]
        m = _GET_CHANNELS_RE.match(line)
        if m:
            name, key_hex = m.group(1).strip(), m.group(2)
            if name.lower() == "public":
                channels.append((PUBLIC_CHANNEL_LABEL, PUBLIC_CHANNEL_KEY))
            else:
                channels.append((name, bytes.fromhex(key_hex)))
            continue

        # Bare hashtag: "#word" with no space after "#"
        if re.match(r"^#\S+$", line):
            tag = line[1:]  # strip leading #
            channels.append((line, _derive_hashtag_key(tag)))
            continue

        bad_lines.append(lineno)

    if bad_lines:
        line_list = ", ".join(str(n) for n in bad_lines)
        print(
            f"Warning: {path!r}: {len(bad_lines)} unrecognised line(s) skipped"
            f" (lines {line_list}).\n"
            f"  Expected format: 'Name [32hexchars]', '#hashtag', or '# comment'.",
            file=sys.stderr,
        )

    return channels


def persist_new_channels(path: str, new_channels: list[dict]) -> list[tuple[str, bytes]]:
    """Append channel entries from *new_channels* that are not already in *path*.

    Each item in *new_channels* is a dict with at least ``name`` (str) and
    optionally ``key_hex`` (32-char hex string representing the 16-byte AES key).
    Entries without ``key_hex`` are skipped — they cannot be used for decryption.

    Only appends entries whose name or key are not already present in the file.
    Returns a list of newly appended ``(name, key_bytes)`` pairs (empty if none added).
    """
    existing = load_channels(path)
    existing_names = {label.lower() for label, _ in existing}
    existing_keys = {key for _, key in existing}

    to_append: list[tuple[str, bytes]] = []
    for ch in new_channels:
        key_hex = ch.get("key_hex") or ""
        if not key_hex or len(key_hex) != 32:
            continue
        try:
            key_bytes = bytes.fromhex(key_hex)
        except ValueError:
            continue
        name = ch.get("name") or ""
        if not name:
            continue
        if name.lower() in existing_names or key_bytes in existing_keys:
            continue
        to_append.append((name, key_bytes))
        existing_names.add(name.lower())
        existing_keys.add(key_bytes)

    if to_append:
        # Determine the next index to use for new entries
        existing_indexed = _count_indexed_entries(path)
        try:
            with open(path, "a", encoding="utf-8") as f:
                for offset, (name, key_bytes) in enumerate(to_append):
                    idx = existing_indexed + offset
                    f.write(f"{idx}: {name} [{key_bytes.hex()}]\n")
        except OSError as exc:
            import sys
            print(f"Warning: could not write to {path!r}: {exc}", file=sys.stderr)

    return to_append


def _count_indexed_entries(path: str) -> int:
    """Count how many 'N: Name [hex]' lines exist in *path* to determine next index."""
    count = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if _GET_CHANNELS_RE.match(line.strip()):
                    count += 1
    except OSError:
        pass
    return count


def build_channel_lookup(
    channels: list[tuple[str, bytes]],
) -> dict[int, list[tuple[str, bytes]]]:
    """Build a map of channel_hash_byte → [(label, key), ...].

    Multiple channels can share the same hash byte (collision); all are tried
    during decryption and the first whose MAC verifies is accepted.
    """
    lookup: dict[int, list[tuple[str, bytes]]] = {}
    for label, key in channels:
        h = _channel_hash_byte(key)
        lookup.setdefault(h, []).append((label, key))
    return lookup


def try_decrypt(
    channel_hash_byte: int,
    cipher_mac: bytes,
    ciphertext: bytes,
    lookup: dict[int, list[tuple[str, bytes]]],
) -> dict | None:
    """Attempt decryption for all channels matching channel_hash_byte.

    Returns the first result whose MAC verifies:
        {"channel": label, "sender": str, "message": str, "timestamp": int}
    Returns None if no channel matches or all MAC checks fail.
    """
    candidates = lookup.get(channel_hash_byte, [])
    for label, key in candidates:
        if not _verify_mac(ciphertext, key, cipher_mac):
            continue
        plaintext = _aes_ecb_decrypt(ciphertext, key)
        if plaintext is None:
            continue
        parsed = _parse_decrypted_payload(plaintext)
        if parsed is None:
            continue
        parsed["channel"] = label
        return parsed
    return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _derive_hashtag_key(name: str) -> bytes:
    """Derive AES key for a hashtag channel: SHA256("#name")[:16]."""
    return hashlib.sha256(f"#{name}".encode()).digest()[:16]


def _channel_hash_byte(key: bytes) -> int:
    """First byte of SHA256(channel_key) — stored in plaintext in the packet."""
    return hashlib.sha256(key).digest()[0]


def _verify_mac(ciphertext: bytes, key: bytes, expected: bytes) -> bool:
    """Check that HMAC-SHA256(ciphertext, key)[:2] == expected."""
    mac = hmac.new(key, ciphertext, hashlib.sha256).digest()[:2]
    return hmac.compare_digest(mac, expected)


def _aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes | None:
    """AES-128-ECB decrypt and strip null/PKCS7 padding. Returns None on error."""
    if len(ciphertext) == 0 or len(ciphertext) % 16 != 0:
        return None
    try:
        cipher = AES.new(key, AES.MODE_ECB)
        plaintext = cipher.decrypt(ciphertext)
        # Strip PKCS7 padding if valid, otherwise strip null bytes
        last = plaintext[-1]
        if 1 <= last <= 16 and plaintext[-last:] == bytes([last]) * last:
            return plaintext[:-last]
        return plaintext.rstrip(b"\x00")
    except Exception:
        return None


def _parse_decrypted_payload(plaintext: bytes) -> dict | None:
    """Extract timestamp, sender and message from decrypted GroupText payload.

    Format: [uint32 LE timestamp][1-byte flags]["sender_name: message text"]
    """
    if len(plaintext) < 6:  # 4 + 1 + at least 1 char
        return None
    try:
        timestamp = struct.unpack_from("<I", plaintext, 0)[0]
        # flags byte at offset 4 — reserved for future use, ignored for display
        text = plaintext[5:].decode("utf-8", errors="replace").rstrip("\x00")
        if ": " in text:
            sender, _, message = text.partition(": ")
        else:
            sender = ""
            message = text
        return {"sender": sender, "message": message, "timestamp": timestamp}
    except Exception:
        return None
