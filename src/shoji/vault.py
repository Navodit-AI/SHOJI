"""Encrypted store for placeholder mappings, keyed by conversation.

Lets a conversation keep its placeholders when a client trims old messages, and lets the
Stage 5 playground show originals. Nothing sensitive is stored in plaintext:

- values are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) under ``SHOJI_VAULT_KEY``;
- "does this value already have a placeholder?" is answered by a keyed HMAC of the
  normalised value (``value_key``), so it needs no decryption;
- conversation ids are stored as keyed HMACs too, since a client may put anything in them.

Placeholder names and entity types are stored as they are: they say what kind of data a
conversation held, not what it was. The schema uses only types that exist in Postgres too.

Generate a key with ``python -m shoji.vault``.
"""

import hashlib
import hmac
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from shoji.redact.mapping import Mapping, value_key

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vault_meta (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vault_conversations (
    conversation_hmac TEXT PRIMARY KEY,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS vault_entries (
    conversation_hmac TEXT NOT NULL
        REFERENCES vault_conversations (conversation_hmac) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    placeholder TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    value_hmac TEXT NOT NULL,
    value_ciphertext TEXT NOT NULL,
    PRIMARY KEY (conversation_hmac, placeholder),
    UNIQUE (conversation_hmac, entity_type, value_hmac)
);
CREATE INDEX IF NOT EXISTS vault_conversations_updated ON vault_conversations (updated_at);
"""

# Encrypted on first use; failing to decrypt it later means the key changed.
_KEY_CHECK = b"shoji-vault-key-check"


class VaultError(Exception):
    pass


class Vault:
    """A SQLite-backed vault. Safe to share between threads (calls are serialised)."""

    def __init__(
        self,
        path: str | Path,
        key: str,
        ttl_hours: float = 24.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise VaultError(
                "SHOJI_VAULT_KEY is not a valid key; generate one with `python -m shoji.vault`"
            ) from exc
        # A separate key for HMACs, derived so one setting covers both.
        self._hmac_key = hashlib.sha256(b"shoji vault lookup\x00" + key.encode()).digest()
        self._ttl_seconds = ttl_hours * 3600
        self._clock = clock
        self._lock = threading.Lock()

        if str(path) != ":memory:" and not Path(path).exists():
            # Create the file readable by the owner only, before SQLite writes anything.
            os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self._check_key()

    def _check_key(self) -> None:
        row = self._db.execute("SELECT value FROM vault_meta WHERE name = 'key_check'").fetchone()
        if row is None:
            token = self._fernet.encrypt(_KEY_CHECK).decode()
            self._db.execute(
                "INSERT INTO vault_meta (name, value) VALUES ('key_check', ?)", (token,)
            )
            return
        try:
            ok = self._fernet.decrypt(row[0].encode()) == _KEY_CHECK
        except InvalidToken:
            ok = False
        if not ok:
            raise VaultError("SHOJI_VAULT_KEY does not match the key this vault was created with")

    def _hmac(self, *parts: str) -> str:
        message = "\x00".join(parts).encode()
        return hmac.new(self._hmac_key, message, hashlib.sha256).hexdigest()

    def _now(self) -> int:
        return int(self._clock())

    def load(self, conversation_id: str) -> Mapping:
        """The conversation's mapping, or an empty one if it is unknown or expired."""
        conv = self._hmac("conversation", conversation_id)
        mapping = Mapping()
        with self._lock:
            row = self._db.execute(
                "SELECT updated_at FROM vault_conversations WHERE conversation_hmac = ?", (conv,)
            ).fetchone()
            if row is None:
                return mapping
            if self._now() - row[0] > self._ttl_seconds:
                self._db.execute(
                    "DELETE FROM vault_conversations WHERE conversation_hmac = ?", (conv,)
                )
                return mapping
            rows = self._db.execute(
                "SELECT placeholder, entity_type, value_ciphertext FROM vault_entries "
                "WHERE conversation_hmac = ? ORDER BY seq",
                (conv,),
            ).fetchall()
        for placeholder, entity_type, ciphertext in rows:
            try:
                value = self._fernet.decrypt(ciphertext.encode()).decode()
            except InvalidToken as exc:
                raise VaultError("a vault entry could not be decrypted") from exc
            mapping.add_existing(placeholder, entity_type, value)
        return mapping

    def save(self, conversation_id: str, mapping: Mapping) -> None:
        """Store any placeholders not stored yet and refresh the conversation's expiry."""
        conv = self._hmac("conversation", conversation_id)
        now = self._now()
        entries = []
        for seq, (placeholder, value) in enumerate(mapping.items()):
            entity_type = mapping.type_of(placeholder)
            assert entity_type is not None
            entries.append(
                (
                    conv,
                    seq,
                    placeholder,
                    entity_type,
                    self._hmac("value", entity_type, value_key(entity_type, value)),
                    self._fernet.encrypt(value.encode()).decode(),
                )
            )
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute(
                    "INSERT INTO vault_conversations (conversation_hmac, created_at, updated_at) "
                    "VALUES (?, ?, ?) ON CONFLICT (conversation_hmac) "
                    "DO UPDATE SET updated_at = excluded.updated_at",
                    (conv, now, now),
                )
                self._db.executemany(
                    "INSERT INTO vault_entries (conversation_hmac, seq, placeholder, entity_type, "
                    "value_hmac, value_ciphertext) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT DO NOTHING",
                    entries,
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def delete(self, conversation_id: str) -> bool:
        conv = self._hmac("conversation", conversation_id)
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM vault_conversations WHERE conversation_hmac = ?", (conv,)
            )
        return cur.rowcount > 0

    def expire(self) -> int:
        """Delete conversations not saved to for longer than the TTL; return how many."""
        cutoff = self._now() - self._ttl_seconds
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM vault_conversations WHERE updated_at < ?", (cutoff,)
            )
        return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()


def open_vault(key: str, path: str | Path, ttl_hours: float) -> Vault | None:
    """The configured vault, or None (with one warning) when no key is set."""
    if not key:
        logger.warning(
            "SHOJI_VAULT_KEY is not set: placeholder mappings are not stored, so each request "
            "is redacted from its own message history only"
        )
        return None
    vault = Vault(path, key, ttl_hours)
    removed = vault.expire()
    if removed:
        logger.info("Vault: removed %d expired conversations", removed)
    return vault


if __name__ == "__main__":
    print(Fernet.generate_key().decode())
