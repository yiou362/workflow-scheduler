from cryptography.fernet import Fernet
import pytest

from promptops.config import Settings
from promptops.security import SecretBox, SecretError, get_secret_box, load_key
from promptops.logging import redact_mapping, redact_text


def test_roundtrip_and_wrong_key(tmp_path):
    box = SecretBox(Fernet.generate_key())
    ciphertext = box.encrypt("s3cret")
    assert ciphertext != "s3cret"
    assert box.decrypt(ciphertext) == "s3cret"

    other = SecretBox(Fernet.generate_key())
    with pytest.raises(SecretError):
        other.decrypt(ciphertext)


def test_empty_password_is_none(tmp_path):
    box = SecretBox(Fernet.generate_key())
    assert box.encrypt("") is None
    assert box.decrypt(None) is None


def test_key_file_generated_and_reused(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", auto_migrate=False)
    key = load_key(settings)
    assert (tmp_path / "data" / "secret.key").exists()
    assert load_key(settings) == key
    box = get_secret_box(settings)
    assert box.decrypt(box.encrypt("x")) == "x"


def test_invalid_key_is_explicit():
    with pytest.raises(SecretError):
        SecretBox(b"not-a-key")


def test_redaction():
    assert redact_text("Authorization: Basic abc123") == "Authorization: Basic ***"
    assert redact_text("password=hunter2") == "password=***"
    assert redact_text("https://user:pass@example.com") == "https://***:***@example.com"
    mapping = redact_mapping({"password": "x", "nested": {"secret": "y", "ok": 1}})
    assert mapping == {"password": "***", "nested": {"secret": "***", "ok": 1}}
