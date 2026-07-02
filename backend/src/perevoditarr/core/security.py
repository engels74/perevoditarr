"""Root-secret handling: HKDF subkeys and secrets-at-rest encryption (FR-A5).

One root secret (PEREVODITARR_SECRET_KEY) feeds independent HKDF subkeys for
JWT signing and for the Fernet box that encrypts instance credentials and
auth-provider configs. Encrypted values are never logged and never returned
in plaintext after write.
"""

import base64
import secrets

import structlog
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from perevoditarr.core.settings import AppSettings

_SECRETS_INFO = b"perevoditarr.secrets-at-rest"
_JWT_INFO = b"perevoditarr.jwt-signing"

_ephemeral_secret: str | None = None


def resolve_secret_key(settings: AppSettings) -> str:
    """Return the root secret.

    prod requires PEREVODITARR_SECRET_KEY (enforced fail-fast in settings);
    dev falls back to a process-lifetime ephemeral key, so sessions and
    encrypted secrets deliberately do not survive a restart.
    """
    global _ephemeral_secret
    if settings.secret_key is not None:
        return settings.secret_key
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(48)
        structlog.get_logger().warning(
            "PEREVODITARR_SECRET_KEY not set - using an ephemeral dev key; "
            "sessions and encrypted secrets will not survive a restart"
        )
    return _ephemeral_secret


def derive_key(secret: str, info: bytes, *, length: int = 32) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info)
    return hkdf.derive(secret.encode("utf-8"))


def jwt_signing_secret(secret: str) -> str:
    return derive_key(secret, _JWT_INFO).hex()


class SecretBoxError(Exception):
    """Decryption failed: wrong key, tampered blob, or expired TTL."""


class SecretBox:
    def __init__(self, secret: str) -> None:
        key = base64.urlsafe_b64encode(derive_key(secret, _SECRETS_INFO))
        self._fernet: Fernet = Fernet(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, blob: bytes, *, ttl: int | None = None) -> bytes:
        try:
            return self._fernet.decrypt(blob, ttl=ttl)
        except InvalidToken as error:
            raise SecretBoxError("cannot decrypt secret blob") from error

    def encrypt_text(self, value: str) -> bytes:
        return self.encrypt(value.encode("utf-8"))

    def decrypt_text(self, blob: bytes, *, ttl: int | None = None) -> str:
        return self.decrypt(blob, ttl=ttl).decode("utf-8")
