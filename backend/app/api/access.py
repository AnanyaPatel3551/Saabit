"""Per-upload access keys: each upload's secret is returned once; only its hash is stored.

The browser sends the key back in the X-Dataset-Key header. A missing or wrong key is
answered exactly like an unknown id (404), so a guessed id reveals nothing. The shared
sample is public and needs no key. The key itself is never logged or stored.
"""

import hashlib
import hmac
import secrets

from app.core.storage import KEY_HASH_FIELD

__all__ = ["KEY_HASH_FIELD", "KEY_HEADER", "hash_key", "key_matches", "new_key"]

KEY_HEADER = "X-Dataset-Key"
KEY_BYTES = 32


def hash_key(key: str) -> str:
    """SHA-256 of the key, as hex."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_key() -> tuple[str, str]:
    """A fresh secret for one upload and the hash to store in its metadata."""
    key = secrets.token_urlsafe(KEY_BYTES)
    return key, hash_key(key)


def key_matches(key: str | None, stored_hash: object) -> bool:
    """True only when a key was sent and its hash equals the stored one (constant time)."""
    if not key or not isinstance(stored_hash, str) or not stored_hash:
        return False
    return hmac.compare_digest(hash_key(key), stored_hash)
