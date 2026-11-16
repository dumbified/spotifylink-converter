"""Tests for checking Meta's webhook signature."""

import pytest

from musiclink.whatsapp.signature import compute_signature, is_valid_signature

SECRET = "test-app-secret-not-a-real-one"
BODY = b'{"object":"whatsapp_business_account"}'


def test_known_value():
    # Worked out independently with:  echo -n 'hello' | openssl dgst -sha256 -hmac 'key'
    assert compute_signature("key", b"hello") == (
        "sha256=9307b3b915efb5171ff14d8cb55fbcc798c6c0ef1456d66ded1a6aa723a58b7b"
    )


def test_correct_signature_is_accepted():
    assert is_valid_signature(SECRET, BODY, compute_signature(SECRET, BODY))


def test_upper_case_hex_is_accepted():
    header = "sha256=" + compute_signature(SECRET, BODY).removeprefix("sha256=").upper()
    assert is_valid_signature(SECRET, BODY, header)


def test_changed_body_is_rejected():
    header = compute_signature(SECRET, BODY)
    assert not is_valid_signature(SECRET, BODY + b" ", header)


def test_wrong_secret_is_rejected():
    header = compute_signature("some-other-secret", BODY)
    assert not is_valid_signature(SECRET, BODY, header)


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "sha256=",
        "sha256=abc123",
        "sha1=" + "a" * 40,  # the older, weaker header format
        "a" * 64,  # right length, missing prefix
        "sha256=" + "0" * 64,
    ],
)
def test_missing_or_malformed_header_is_rejected(header):
    assert not is_valid_signature(SECRET, BODY, header)
