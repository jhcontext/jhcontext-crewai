"""SQLite-backed PII vault for local development without AWS.

Vendored from jhcontext-sdk v0.3.2 (jhcontext/server/storage/pii_vault.py).
Implements the same PIIVault protocol as DynamoDBPIIVault.

Stores PII tokens in a SEPARATE database file from envelopes, enabling:
- Independent encryption of PII data
- GDPR Art. 17 erasure without touching the envelope DB
- Access control at the storage level

Only loaded when JHCONTEXT_LOCAL=1 is set — Lambda deployments never import this.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


_DEFAULT_DIR = os.path.expanduser("~/.jhcontext-aws")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pii_tokens (
    token_id TEXT PRIMARY KEY,
    context_id TEXT NOT NULL,
    field_path TEXT NOT NULL,
    original_value TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pii_context ON pii_tokens(context_id);
"""


class SQLitePIIVault:
    """SQLite-backed PII vault.

    Uses a separate database file (``pii_vault.db``) from the main
    envelope store so PII can be managed, encrypted, or deleted
    independently of audit artifacts.
    """

    def __init__(self, db_path: str | None = None) -> None:
        base = Path(db_path).parent if db_path else Path(_DEFAULT_DIR)
        base.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path or str(base / "pii_vault.db")
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def store(self, token_id: str, context_id: str, original_value: str, field_path: str) -> None:
        """Store a PII token mapping."""
        self._conn.execute(
            """INSERT OR REPLACE INTO pii_tokens
               (token_id, context_id, field_path, original_value, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                token_id,
                context_id,
                field_path,
                original_value,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def retrieve(self, token_id: str) -> str | None:
        """Retrieve the original PII value for a token."""
        row = self._conn.execute(
            "SELECT original_value FROM pii_tokens WHERE token_id = ?",
            (token_id,),
        ).fetchone()
        return row["original_value"] if row else None

    def retrieve_by_context(self, context_id: str) -> list[dict[str, str]]:
        """Retrieve all PII tokens for a given context_id."""
        rows = self._conn.execute(
            "SELECT token_id, field_path, original_value, created_at FROM pii_tokens WHERE context_id = ?",
            (context_id,),
        ).fetchall()
        return [
            {
                "token_id": row["token_id"],
                "field_path": row["field_path"],
                "original_value": row["original_value"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def purge_by_context(self, context_id: str) -> int:
        """Delete all PII tokens for a context (GDPR Art. 17 erasure).

        Returns the number of tokens deleted.
        """
        cursor = self._conn.execute(
            "DELETE FROM pii_tokens WHERE context_id = ?",
            (context_id,),
        )
        self._conn.commit()
        return cursor.rowcount

    def purge_expired(self, before_iso: str) -> int:
        """Delete all PII tokens created before the given ISO timestamp.

        Returns the number of tokens deleted.
        """
        cursor = self._conn.execute(
            "DELETE FROM pii_tokens WHERE created_at < ?",
            (before_iso,),
        )
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._conn.close()
