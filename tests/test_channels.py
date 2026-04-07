"""Tests for src/lma/channels.py — channel key loading and GroupText decryption."""

from __future__ import annotations

import hashlib
import hmac
import struct
import textwrap
from pathlib import Path

from Crypto.Cipher import AES

from meshcore_tools.channels import (
    PUBLIC_CHANNEL_KEY,
    build_channel_lookup,
    load_channels,
    persist_new_channels,
    try_decrypt,
    _channel_hash_byte,
    _derive_hashtag_key,
    _parse_decrypted_payload,
    _verify_mac,
)


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def test_public_channel_key_is_16_bytes():
    assert len(PUBLIC_CHANNEL_KEY) == 16
    assert PUBLIC_CHANNEL_KEY == bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72")


def test_derive_hashtag_key_wardriving():
    """Verify that derived key matches get_channels output for #wardriving."""
    key = _derive_hashtag_key("wardriving")
    assert key == bytes.fromhex("e3c26491e9cd321e3a6be50d57d54acf")


def test_derive_hashtag_key_chaosstuff():
    key = _derive_hashtag_key("chaosstuff")
    assert key == bytes.fromhex("b53025e867806e0b5e241adc0d47358b")


def test_derive_hashtag_key_emergency():
    key = _derive_hashtag_key("emergency")
    assert key == bytes.fromhex("e1ad578d25108e344808f30dfdaaf926")


def test_derive_hashtag_key_testing():
    key = _derive_hashtag_key("testing")
    assert key == bytes.fromhex("cde5e82cf515647dcb547a79a4f065d1")


def test_channel_hash_byte():
    h = _channel_hash_byte(PUBLIC_CHANNEL_KEY)
    assert h == hashlib.sha256(PUBLIC_CHANNEL_KEY).digest()[0]
    assert isinstance(h, int)
    assert 0 <= h <= 255


# ---------------------------------------------------------------------------
# load_channels parsing
# ---------------------------------------------------------------------------

def _write_tmp(tmp_path: Path, content: str) -> str:
    f = tmp_path / "channels.txt"
    f.write_text(textwrap.dedent(content))
    return str(f)


def test_load_channels_get_channels_format(tmp_path):
    path = _write_tmp(tmp_path, """\
        0: Public [8b3387e9c5cdea6ac9e5edbaa115cd72]
        1: #wardriving [e3c26491e9cd321e3a6be50d57d54acf]
        2: #chaosstuff [b53025e867806e0b5e241adc0d47358b]
    """)
    channels = load_channels(path)
    assert len(channels) == 3
    assert channels[0] == ("Public", PUBLIC_CHANNEL_KEY)
    assert channels[1] == ("#wardriving", bytes.fromhex("e3c26491e9cd321e3a6be50d57d54acf"))
    assert channels[2] == ("#chaosstuff", bytes.fromhex("b53025e867806e0b5e241adc0d47358b"))


def test_load_channels_bare_hashtag(tmp_path):
    path = _write_tmp(tmp_path, "#wardriving\n")
    channels = load_channels(path)
    assert len(channels) == 1
    label, key = channels[0]
    assert label == "#wardriving"
    assert key == _derive_hashtag_key("wardriving")


def test_load_channels_comments_and_blanks(tmp_path):
    path = _write_tmp(tmp_path, """\
        # This is a comment
        # another comment

        0: Public [8b3387e9c5cdea6ac9e5edbaa115cd72]
    """)
    channels = load_channels(path)
    assert len(channels) == 1


def test_load_channels_public_case_insensitive(tmp_path):
    path = _write_tmp(tmp_path, "0: PUBLIC [8b3387e9c5cdea6ac9e5edbaa115cd72]\n")
    channels = load_channels(path)
    assert channels[0][1] == PUBLIC_CHANNEL_KEY


def test_load_channels_missing_file():
    channels = load_channels("/nonexistent/path/channels.txt")
    assert channels == []


def test_load_channels_mixed(tmp_path):
    path = _write_tmp(tmp_path, """\
        # comment
        0: Public [8b3387e9c5cdea6ac9e5edbaa115cd72]
        #myhashtag
        1: #wardriving [e3c26491e9cd321e3a6be50d57d54acf]
    """)
    channels = load_channels(path)
    assert len(channels) == 3
    labels = [c[0] for c in channels]
    assert "Public" in labels
    assert "#myhashtag" in labels
    assert "#wardriving" in labels


# ---------------------------------------------------------------------------
# build_channel_lookup
# ---------------------------------------------------------------------------

def test_build_channel_lookup_groups_by_hash_byte():
    key = PUBLIC_CHANNEL_KEY
    h = _channel_hash_byte(key)
    lookup = build_channel_lookup([("Public", key)])
    assert h in lookup
    assert lookup[h][0] == ("Public", key)


# ---------------------------------------------------------------------------
# MAC verification
# ---------------------------------------------------------------------------

def test_verify_mac_correct():
    key = PUBLIC_CHANNEL_KEY
    ciphertext = b"\x01\x02\x03\x04" * 4  # 16 bytes
    mac = hmac.new(key, ciphertext, hashlib.sha256).digest()[:2]
    assert _verify_mac(ciphertext, key, mac)


def test_verify_mac_wrong():
    key = PUBLIC_CHANNEL_KEY
    ciphertext = b"\x01\x02\x03\x04" * 4
    assert not _verify_mac(ciphertext, key, b"\x00\x00")


# ---------------------------------------------------------------------------
# _parse_decrypted_payload
# ---------------------------------------------------------------------------

def test_parse_decrypted_payload_normal():
    timestamp = 1700000000
    flags = 0x00
    text = "alice: Hello everyone!"
    payload = struct.pack("<I", timestamp) + bytes([flags]) + text.encode()
    result = _parse_decrypted_payload(payload)
    assert result is not None
    assert result["sender"] == "alice"
    assert result["message"] == "Hello everyone!"
    assert result["timestamp"] == timestamp


def test_parse_decrypted_payload_no_colon():
    payload = struct.pack("<I", 0) + b"\x00" + b"just a message"
    result = _parse_decrypted_payload(payload)
    assert result is not None
    assert result["sender"] == ""
    assert result["message"] == "just a message"


def test_parse_decrypted_payload_too_short():
    assert _parse_decrypted_payload(b"\x00\x01\x02\x03") is None


def test_parse_decrypted_payload_strips_null_padding():
    payload = struct.pack("<I", 0) + b"\x00" + b"bob: hi\x00\x00\x00"
    result = _parse_decrypted_payload(payload)
    assert result is not None
    assert result["message"] == "hi"


# ---------------------------------------------------------------------------
# Round-trip: encrypt then try_decrypt
# ---------------------------------------------------------------------------

def _make_group_text_payload(key: bytes, sender: str, message: str) -> bytes:
    """Build a valid GRP_TXT payload (channel_hash + mac + ciphertext)."""
    ch_hash = bytes([_channel_hash_byte(key)])
    timestamp = struct.pack("<I", 1700000000)
    flags = b"\x00"
    plaintext = timestamp + flags + f"{sender}: {message}".encode()
    # Pad to 16-byte boundary
    pad_len = 16 - (len(plaintext) % 16)
    plaintext += bytes([pad_len]) * pad_len
    ciphertext = AES.new(key, AES.MODE_ECB).encrypt(plaintext)
    mac = hmac.new(key, ciphertext, hashlib.sha256).digest()[:2]
    return ch_hash + mac + ciphertext


def test_try_decrypt_public_channel():
    key = PUBLIC_CHANNEL_KEY
    payload = _make_group_text_payload(key, "gw-charly", "Test message")
    ch_byte = payload[0]
    mac = payload[1:3]
    ciphertext = payload[3:]
    lookup = build_channel_lookup([("Public", key)])
    result = try_decrypt(ch_byte, mac, ciphertext, lookup)
    assert result is not None
    assert result["sender"] == "gw-charly"
    assert result["message"] == "Test message"
    assert result["channel"] == "Public"


def test_try_decrypt_hashtag_channel():
    key = _derive_hashtag_key("luxembourg")
    payload = _make_group_text_payload(key, "rpt-sennberg", "Hello LUX")
    ch_byte = payload[0]
    mac = payload[1:3]
    ciphertext = payload[3:]
    lookup = build_channel_lookup([("#luxembourg", key)])
    result = try_decrypt(ch_byte, mac, ciphertext, lookup)
    assert result is not None
    assert result["sender"] == "rpt-sennberg"
    assert result["channel"] == "#luxembourg"


def test_try_decrypt_wrong_key_returns_none():
    key = PUBLIC_CHANNEL_KEY
    wrong_key = bytes.fromhex("aabbccddeeff00112233445566778899")
    payload = _make_group_text_payload(key, "alice", "secret")
    ch_byte = payload[0]
    mac = payload[1:3]
    ciphertext = payload[3:]
    # Build lookup with same hash byte but wrong key (force collision)
    lookup = {ch_byte: [("wrong", wrong_key)]}
    result = try_decrypt(ch_byte, mac, ciphertext, lookup)
    assert result is None


def test_try_decrypt_unknown_channel_returns_none():
    key = PUBLIC_CHANNEL_KEY
    payload = _make_group_text_payload(key, "alice", "secret")
    ch_byte = payload[0]
    mac = payload[1:3]
    ciphertext = payload[3:]
    result = try_decrypt(ch_byte, mac, ciphertext, lookup={})
    assert result is None


# ---------------------------------------------------------------------------
# persist_new_channels
# ---------------------------------------------------------------------------

_WARDRIVING_KEY = "e3c26491e9cd321e3a6be50d57d54acf"
_CHAOS_KEY = "b53025e867806e0b5e241adc0d47358b"


def test_persist_new_channels_appends_new_entry(tmp_path):
    path = str(tmp_path / "channels.txt")
    new_ch = [{"idx": 0, "name": "#wardriving", "key_hex": _WARDRIVING_KEY}]
    added = persist_new_channels(path, new_ch)
    assert len(added) == 1
    assert added[0] == ("#wardriving", bytes.fromhex(_WARDRIVING_KEY))
    content = (tmp_path / "channels.txt").read_text()
    assert f"#wardriving [{_WARDRIVING_KEY}]" in content


def test_persist_new_channels_no_duplicate_by_name(tmp_path):
    path = _write_tmp(tmp_path, f"0: #wardriving [{_WARDRIVING_KEY}]\n")
    new_ch = [{"idx": 0, "name": "#wardriving", "key_hex": _WARDRIVING_KEY}]
    added = persist_new_channels(path, new_ch)
    assert added == []


def test_persist_new_channels_no_duplicate_by_key(tmp_path):
    path = _write_tmp(tmp_path, f"0: MyChannel [{_WARDRIVING_KEY}]\n")
    new_ch = [{"idx": 0, "name": "#wardriving", "key_hex": _WARDRIVING_KEY}]
    added = persist_new_channels(path, new_ch)
    assert added == []


def test_persist_new_channels_skips_missing_key(tmp_path):
    path = str(tmp_path / "channels.txt")
    new_ch = [{"idx": 0, "name": "NoKey"}]
    added = persist_new_channels(path, new_ch)
    assert added == []
    assert not (tmp_path / "channels.txt").exists()


def test_persist_new_channels_file_created_when_missing(tmp_path):
    path = str(tmp_path / "newdir" / "channels.txt")
    (tmp_path / "newdir").mkdir()
    new_ch = [{"idx": 0, "name": "#wardriving", "key_hex": _WARDRIVING_KEY}]
    added = persist_new_channels(path, new_ch)
    assert len(added) == 1
    content = (tmp_path / "newdir" / "channels.txt").read_text()
    assert _WARDRIVING_KEY in content


def test_persist_new_channels_appends_multiple(tmp_path):
    path = str(tmp_path / "channels.txt")
    new_ch = [
        {"idx": 0, "name": "#wardriving", "key_hex": _WARDRIVING_KEY},
        {"idx": 1, "name": "#chaosstuff", "key_hex": _CHAOS_KEY},
    ]
    added = persist_new_channels(path, new_ch)
    assert len(added) == 2
    content = (tmp_path / "channels.txt").read_text()
    assert _WARDRIVING_KEY in content
    assert _CHAOS_KEY in content


def test_persist_new_channels_index_continues_after_existing(tmp_path):
    path = _write_tmp(tmp_path, f"0: Public [8b3387e9c5cdea6ac9e5edbaa115cd72]\n")
    new_ch = [{"idx": 1, "name": "#wardriving", "key_hex": _WARDRIVING_KEY}]
    persist_new_channels(path, new_ch)
    lines = [line for line in (tmp_path / "channels.txt").read_text().splitlines() if line.strip()]
    # New entry should start at index 1
    assert any(line.startswith("1:") for line in lines)


def test_persist_new_channels_reloadable(tmp_path):
    path = str(tmp_path / "channels.txt")
    new_ch = [{"idx": 0, "name": "#wardriving", "key_hex": _WARDRIVING_KEY}]
    persist_new_channels(path, new_ch)
    reloaded = load_channels(path)
    assert len(reloaded) == 1
    assert reloaded[0] == ("#wardriving", bytes.fromhex(_WARDRIVING_KEY))


def test_persist_new_channels_invalid_key_hex_skipped(tmp_path):
    path = str(tmp_path / "channels.txt")
    new_ch = [{"idx": 0, "name": "#bad", "key_hex": "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"}]
    added = persist_new_channels(path, new_ch)
    assert added == []


def test_persist_new_channels_key_as_bytes(tmp_path):
    """key_hex must be a hex string; bytes values in the dict are handled by companion."""
    path = str(tmp_path / "channels.txt")
    # key_hex should be a string — bytes value is not accepted by persist_new_channels
    new_ch = [{"idx": 0, "name": "#wardriving", "key_hex": None}]
    added = persist_new_channels(path, new_ch)
    assert added == []
