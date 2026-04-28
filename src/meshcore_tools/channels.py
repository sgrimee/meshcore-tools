"""Channel key lookup and GroupText/GroupData decryption.

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

from Crypto.Cipher import AES  # pycryptodome

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PUBLIC_CHANNEL_KEY = bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72")
PUBLIC_CHANNEL_LABEL = "Public"

# Hashtag channel keys are always deterministically derivable from their names,
# so these are tried for every GroupText packet without any secrets.toml entry.
BUILTIN_CHANNELS: list[tuple[str, bytes]] = [
    (PUBLIC_CHANNEL_LABEL, PUBLIC_CHANNEL_KEY),
    ("#wardriving", hashlib.sha256(b"#wardriving").digest()[:16]),
]

_WARDRIVING_RE = re.compile(r"^@\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_wardriving_coords(message: str) -> tuple[float, float] | None:
    """Parse '@ lat, lon' from a #wardriving message. Returns (lat, lon) or None."""
    m = _WARDRIVING_RE.match(message.strip())
    if not m:
        return None
    try:
        lat, lon = float(m.group(1)), float(m.group(2))
    except ValueError:
        return None
    if (lat, lon) == (0.0, 0.0):
        return None
    return lat, lon


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
