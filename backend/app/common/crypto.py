"""Symmetric encryption for secrets stored at rest (e.g. connector tokens).

Values are encrypted with Fernet (AES-128-CBC + HMAC). The key is derived
deterministically from ``settings.secret_key`` so no separate key management
is required; rotating ``secret_key`` invalidates existing ciphertext, which
then falls back to legacy-plaintext handling on decrypt.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    """Build a Fernet using a key derived from the app secret key.

    Fernet requires a 32-byte url-safe base64-encoded key. We hash the
    configured secret with SHA-256 to get exactly 32 bytes regardless of the
    secret's length, then base64-encode it.
    """
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_value(value: str | None) -> str | None:
    """Encrypt a plaintext string. Returns None unchanged."""
    if value is None:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(value: str | None) -> str | None:
    """Decrypt a Fernet token produced by :func:`encrypt_value`.

    Returns None unchanged. If the value is not valid ciphertext (e.g. a
    legacy plaintext token written before encryption existed, or a value
    encrypted under a since-rotated secret key), it is returned as-is so
    existing data sources keep working.
    """
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning(
            "decrypt_value received a non-ciphertext value; "
            "treating as legacy plaintext"
        )
        return value
