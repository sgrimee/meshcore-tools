"""Tests for passwords.py — default password and per-repeater password storage."""

from __future__ import annotations

import stat


from meshcore_tools.passwords import (
    get_prefilled_password,
    load_default_password,
    load_repeater_passwords,
    save_default_password,
    save_repeater_password,
)


# ---------------------------------------------------------------------------
# default password (secrets.toml)
# ---------------------------------------------------------------------------


def test_load_default_password_missing_file(tmp_path):
    assert load_default_password(config_dir=tmp_path) is None


def test_save_and_load_default_password(tmp_path):
    save_default_password("s3cr3t", config_dir=tmp_path)
    assert load_default_password(config_dir=tmp_path) == "s3cr3t"


def test_save_default_password_creates_file(tmp_path):
    save_default_password("pw", config_dir=tmp_path)
    assert (tmp_path / "secrets.toml").exists()


def test_save_default_password_600_permissions(tmp_path):
    save_default_password("pw", config_dir=tmp_path)
    mode = (tmp_path / "secrets.toml").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_save_default_password_preserves_repeater_passwords(tmp_path):
    # Write a repeater password first, then save default_password — both should coexist.
    save_repeater_password("key1", "pw1", config_dir=tmp_path)
    save_default_password("default", config_dir=tmp_path)
    import tomllib
    data = tomllib.loads((tmp_path / "secrets.toml").read_text())
    assert data["default_password"] == "default"
    assert data["passwords"]["key1"] == "pw1"


def test_save_default_password_overwrites_existing(tmp_path):
    save_default_password("first", config_dir=tmp_path)
    save_default_password("second", config_dir=tmp_path)
    assert load_default_password(config_dir=tmp_path) == "second"


def test_load_default_password_invalid_toml(tmp_path):
    (tmp_path / "secrets.toml").write_text("not valid toml ][")
    assert load_default_password(config_dir=tmp_path) is None


def test_load_default_password_empty_field(tmp_path):
    (tmp_path / "secrets.toml").write_text('default_password = ""\n')
    assert load_default_password(config_dir=tmp_path) is None


def test_save_default_password_special_chars(tmp_path):
    pw = 'p"a\\ss'
    save_default_password(pw, config_dir=tmp_path)
    assert load_default_password(config_dir=tmp_path) == pw


# ---------------------------------------------------------------------------
# per-repeater passwords (secrets.toml [passwords] table)
# ---------------------------------------------------------------------------


def test_load_repeater_passwords_missing_file(tmp_path):
    assert load_repeater_passwords(config_dir=tmp_path) == {}


def test_save_and_load_repeater_password(tmp_path):
    save_repeater_password("abc123", "mypassword", config_dir=tmp_path)
    passwords = load_repeater_passwords(config_dir=tmp_path)
    assert passwords["abc123"] == "mypassword"


def test_save_repeater_password_creates_file(tmp_path):
    save_repeater_password("key1", "pw", config_dir=tmp_path)
    assert (tmp_path / "secrets.toml").exists()


def test_save_repeater_password_600_permissions(tmp_path):
    save_repeater_password("key1", "pw", config_dir=tmp_path)
    mode = (tmp_path / "secrets.toml").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_save_repeater_password_accumulates(tmp_path):
    save_repeater_password("key1", "pw1", config_dir=tmp_path)
    save_repeater_password("key2", "pw2", config_dir=tmp_path)
    passwords = load_repeater_passwords(config_dir=tmp_path)
    assert passwords["key1"] == "pw1"
    assert passwords["key2"] == "pw2"


def test_save_repeater_password_overwrites(tmp_path):
    save_repeater_password("key1", "old", config_dir=tmp_path)
    save_repeater_password("key1", "new", config_dir=tmp_path)
    passwords = load_repeater_passwords(config_dir=tmp_path)
    assert passwords["key1"] == "new"


def test_save_repeater_password_special_chars(tmp_path):
    pw = 'p"a\\ss!'
    save_repeater_password("key1", pw, config_dir=tmp_path)
    assert load_repeater_passwords(config_dir=tmp_path)["key1"] == pw


def test_load_repeater_passwords_invalid_toml(tmp_path):
    (tmp_path / "secrets.toml").write_text("not valid ][")
    assert load_repeater_passwords(config_dir=tmp_path) == {}


# ---------------------------------------------------------------------------
# default and repeater passwords coexist in secrets.toml
# ---------------------------------------------------------------------------


def test_default_and_repeater_coexist(tmp_path):
    save_default_password("default_pw", config_dir=tmp_path)
    save_repeater_password("key1", "specific_pw", config_dir=tmp_path)
    assert load_default_password(config_dir=tmp_path) == "default_pw"
    assert load_repeater_passwords(config_dir=tmp_path)["key1"] == "specific_pw"


def test_single_file_always_600(tmp_path):
    """Both default and repeater passwords go to secrets.toml, always with 600 perms."""
    save_default_password("pw", config_dir=tmp_path)
    save_repeater_password("k", "p", config_dir=tmp_path)
    mode = (tmp_path / "secrets.toml").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600
    assert not (tmp_path / "passwords.toml").exists()
    assert not (tmp_path / "settings.toml").exists()


# ---------------------------------------------------------------------------
# get_prefilled_password
# ---------------------------------------------------------------------------


def test_get_prefilled_no_config(tmp_path):
    contact = {"public_key": "abc123"}
    assert get_prefilled_password(contact, config_dir=tmp_path) is None


def test_get_prefilled_default_only(tmp_path):
    save_default_password("default_pw", config_dir=tmp_path)
    contact = {"public_key": "abc123"}
    assert get_prefilled_password(contact, config_dir=tmp_path) == "default_pw"


def test_get_prefilled_per_repeater_takes_precedence(tmp_path):
    save_default_password("default_pw", config_dir=tmp_path)
    save_repeater_password("abc123", "specific_pw", config_dir=tmp_path)
    contact = {"public_key": "abc123"}
    assert get_prefilled_password(contact, config_dir=tmp_path) == "specific_pw"


def test_get_prefilled_other_repeater_uses_default(tmp_path):
    save_default_password("default_pw", config_dir=tmp_path)
    save_repeater_password("other_key", "other_pw", config_dir=tmp_path)
    contact = {"public_key": "abc123"}
    assert get_prefilled_password(contact, config_dir=tmp_path) == "default_pw"


def test_get_prefilled_no_public_key(tmp_path):
    save_default_password("default_pw", config_dir=tmp_path)
    contact: dict = {}  # no public_key
    assert get_prefilled_password(contact, config_dir=tmp_path) == "default_pw"


def test_get_prefilled_empty_public_key_uses_default(tmp_path):
    save_default_password("default_pw", config_dir=tmp_path)
    contact = {"public_key": ""}
    assert get_prefilled_password(contact, config_dir=tmp_path) == "default_pw"


def test_save_default_password_with_corrupt_existing_secrets(tmp_path):
    """save_default_password should succeed even if existing secrets.toml is invalid TOML."""
    secrets = tmp_path / "secrets.toml"
    secrets.write_text("not valid toml ][")
    secrets.chmod(0o600)
    # Should not raise
    save_default_password("newpass", config_dir=tmp_path)
    assert load_default_password(config_dir=tmp_path) == "newpass"


# ---------------------------------------------------------------------------
# Migration from old files (settings.toml + passwords.toml → secrets.toml)
# ---------------------------------------------------------------------------


def test_migrate_default_password_from_settings_toml(tmp_path):
    """default_password in settings.toml is migrated to secrets.toml on first load."""
    (tmp_path / "settings.toml").write_text('default_password = "migrated_pw"\n')
    assert load_default_password(config_dir=tmp_path) == "migrated_pw"
    assert (tmp_path / "secrets.toml").exists()


def test_migrate_repeater_passwords_from_passwords_toml(tmp_path):
    """Passwords in passwords.toml are migrated to secrets.toml on first load."""
    (tmp_path / "passwords.toml").write_text('[passwords]\n"key1" = "pw1"\n')
    (tmp_path / "passwords.toml").chmod(0o600)
    passwords = load_repeater_passwords(config_dir=tmp_path)
    assert passwords["key1"] == "pw1"
    assert (tmp_path / "secrets.toml").exists()


def test_migration_writes_600_permissions(tmp_path):
    (tmp_path / "settings.toml").write_text('default_password = "pw"\n')
    load_default_password(config_dir=tmp_path)
    mode = (tmp_path / "secrets.toml").stat().st_mode
    assert stat.S_IMODE(mode) == 0o600
