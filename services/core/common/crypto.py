"""Field encryption for bank account numbers and ERP credentials (docs/12-security-privacy.md).

- ``encrypt`` / ``decrypt``: AES-256-GCM with a random nonce; the stored text is
  ``v1:<base64(nonce + ciphertext)>``. The org id is bound as associated data, so a value
  copied into another tenant's row fails to decrypt.
- ``blind_index``: HMAC-SHA256 of a normalised value, for exact-match lookups (is this the
  vendor's bank account?) without decrypting anything.
- ``mask``: what people see, e.g. ``PK36 **** **** 1234``.

The key is FIELD_ENCRYPTION_KEY (base64, 32 bytes). Two sub-keys are derived from it, one
for encryption and one for the index, so neither use weakens the other.
"""

import base64
import hashlib
import hmac
import os
import re
from functools import cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

VERSION = "v1"
NONCE_BYTES = 12


class DecryptionError(Exception):
    pass


@cache
def _keys(raw: str) -> tuple[bytes, bytes]:
    try:
        master = base64.b64decode(raw, validate=True)
    except ValueError as exc:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be base64") from exc
    if len(master) != 32:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must decode to 32 bytes")
    enc = hmac.new(master, b"invoiceflow:encrypt", hashlib.sha256).digest()
    idx = hmac.new(master, b"invoiceflow:index", hashlib.sha256).digest()
    return enc, idx


def _key(which: int) -> bytes:
    if not settings.FIELD_ENCRYPTION_KEY:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is not set")
    return _keys(settings.FIELD_ENCRYPTION_KEY)[which]


def encrypt(plaintext: str, *, org_id: str) -> str:
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(_key(0)).encrypt(nonce, plaintext.encode(), org_id.encode())
    return f"{VERSION}:{base64.b64encode(nonce + sealed).decode()}"


def decrypt(token: str, *, org_id: str) -> str:
    version, _, payload = token.partition(":")
    if version != VERSION:
        raise DecryptionError(f"unknown format {version!r}")
    try:
        blob = base64.b64decode(payload, validate=True)
        plain = AESGCM(_key(0)).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], org_id.encode())
    except Exception as exc:  # noqa: BLE001 - any failure means the value can't be trusted
        raise DecryptionError("value could not be decrypted") from exc
    return plain.decode()


def normalize_account(value: str) -> str:
    """Bank account / IBAN in a comparable form: upper case, no spaces, dashes or dots."""
    return re.sub(r"[\s\-.]", "", value).upper()


def blind_index(value: str, *, org_id: str) -> str:
    message = f"{org_id}:{normalize_account(value)}".encode()
    return hmac.new(_key(1), message, hashlib.sha256).hexdigest()


def mask(value: str) -> str:
    """Keep the country/check prefix of an IBAN and the last 4 characters."""
    clean = normalize_account(value)
    if len(clean) <= 4:
        return "*" * len(clean)
    head = clean[:4] if clean[:2].isalpha() else ""
    return f"{head} **** **** {clean[-4:]}".strip()
