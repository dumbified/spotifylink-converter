"""Tests for settings."""

import pytest
from pydantic import ValidationError

from musiclink.config import Settings, parse_phone_numbers

VALID = {
    "whatsapp_verify_token": "test-verify-token-0123456789",
    "whatsapp_app_secret": "test-app-secret-0123456789",
    "whatsapp_access_token": "test-access-token-0123456789",
    "whatsapp_phone_number_id": "123456789012345",
    "allowed_senders": "6591234567",
}


def make(**changes) -> Settings:
    # _env_file=None: ignore any real .env on this machine while testing.
    return Settings(_env_file=None, **{**VALID, **changes})


def test_valid_settings_and_defaults():
    settings = make()
    assert settings.itunes_country == "us"
    assert settings.graph_api_version == "v24.0"
    assert settings.allowed_sender_set == {"6591234567"}
    # By default the server is only reachable from this computer.
    assert settings.bind_host == "127.0.0.1"
    assert settings.port == 8000


def test_secrets_are_hidden_when_printed():
    text = repr(make())
    assert "test-app-secret" not in text
    assert "test-access-token" not in text
    assert "test-verify-token" not in text


def test_phone_numbers_are_tidied():
    assert parse_phone_numbers("+65 9123 4567, 60-12-345 6789,,") == {"6591234567", "60123456789"}


@pytest.mark.parametrize(
    "changes",
    [
        {"whatsapp_verify_token": "short"},
        {"whatsapp_app_secret": ""},
        {"whatsapp_phone_number_id": "not-a-number"},
        {"allowed_senders": "nobody at all"},
        {"itunes_country": "usa"},
        {"graph_api_version": "24"},
        {"graph_api_version": "v24.0/../../x"},
        {"bind_host": "example.com"},
        {"port": 0},
        {"port": 70000},
    ],
)
def test_bad_values_are_refused(changes):
    with pytest.raises(ValidationError):
        make(**changes)


def test_hosting_values_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setenv("BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("LOG_FILE", "")
    settings = make()
    assert (settings.bind_host, settings.port, settings.log_file) == ("0.0.0.0", 10000, "")


def test_missing_values_are_refused(monkeypatch):
    for name in VALID:
        monkeypatch.delenv(name.upper(), raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
