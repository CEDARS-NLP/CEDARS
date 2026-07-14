"""Tests for symmetric encryption of secrets at rest (app.common.crypto)."""

import pytest

from app.common.crypto import decrypt_value, encrypt_value


class TestCrypto:
    def test_round_trip(self):
        plaintext = "dapi0123456789abcdef"
        token = encrypt_value(plaintext)
        assert token != plaintext  # actually encrypted, not stored verbatim
        assert decrypt_value(token) == plaintext

    def test_ciphertext_is_not_deterministic(self):
        # Fernet embeds a random IV, so two encryptions differ.
        assert encrypt_value("secret") != encrypt_value("secret")

    def test_decrypt_legacy_plaintext_passthrough(self):
        # Rows written before encryption existed hold raw tokens. Decrypting
        # a value that isn't valid ciphertext must return it unchanged so
        # existing data sources keep working.
        assert decrypt_value("plain-legacy-token") == "plain-legacy-token"

    def test_empty_string_round_trip(self):
        assert decrypt_value(encrypt_value("")) == ""

    def test_none_passthrough(self):
        assert encrypt_value(None) is None
        assert decrypt_value(None) is None
