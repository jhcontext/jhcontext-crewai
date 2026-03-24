"""SQLite storage backend for local development without AWS.

Vendored from jhcontext-sdk v0.3.2 (jhcontext/server/storage/sqlite.py).
Implements the same StorageBackend protocol as DynamoDBStorage.

Only loaded when JHCONTEXT_LOCAL=1 is set — Lambda deployments never import this.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from jhcontext.models import Artifact, Decision, Envelope


_DEFAULT_DIR = os.path.expanduser("~/.jhcontext-aws")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS envelopes (
    context_id TEXT PRIMARY KEY,
    envelope_json TEXT NOT NULL,
    content_hash TEXT,
    signature TEXT,
    signer TEXT,
    risk_level TEXT,
    scope TEXT,
    ttl TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    context_id TEXT,
    artifact_type TEXT,
    content_hash TEXT,
    storage_path TEXT,
    model TEXT,
    deterministic INTEGER DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (context_id) REFERENCES envelopes(context_id)
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    context_id TEXT,
    passed_artifact_id TEXT,
    outcome TEXT,
    agent_id TEXT,
    created_at TEXT,
    FOREIGN KEY (context_id) REFERENCES envelopes(context_id)
);

CREATE TABLE IF NOT EXISTS prov_graphs (
    context_id TEXT PRIMARY KEY,
    graph_turtle TEXT NOT NULL,
    graph_digest TEXT,
    created_at TEXT,
    FOREIGN KEY (context_id) REFERENCES envelopes(context_id)
);
"""


class SQLiteStorage:
    """SQLite-based storage backend. Zero-config, single file."""

    def __init__(self, db_path: str | None = None, artifacts_dir: str | None = None) -> None:
        base = Path(db_path).parent if db_path else Path(_DEFAULT_DIR)
        base.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path or str(base / "data.db")
        self.artifacts_dir = Path(artifacts_dir or str(base / "artifacts"))
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def save_envelope(self, envelope: Envelope) -> str:
        self._conn.execute(
            """INSERT OR REPLACE INTO envelopes
               (context_id, envelope_json, content_hash, signature, signer,
                risk_level, scope, ttl, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                envelope.context_id,
                json.dumps(envelope.to_jsonld()),
                envelope.proof.content_hash,
                envelope.proof.signature,
                envelope.proof.signer,
                envelope.compliance.risk_level.value,
                envelope.scope,
                envelope.ttl,
                envelope.status.value,
                envelope.created_at,
            ),
        )
        self._conn.commit()
        return envelope.context_id

    def get_envelope(self, context_id: str) -> Envelope | None:
        row = self._conn.execute(
            "SELECT envelope_json FROM envelopes WHERE context_id = ?",
            (context_id,),
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["envelope_json"])
        data.pop("@context", None)
        data.pop("@type", None)
        return Envelope.model_validate(data)

    def list_envelopes(self, **filters: Any) -> list[Envelope]:
        query = "SELECT envelope_json FROM envelopes WHERE 1=1"
        params: list[Any] = []
        if "scope" in filters:
            query += " AND scope = ?"
            params.append(filters["scope"])
        if "risk_level" in filters:
            query += " AND risk_level = ?"
            params.append(filters["risk_level"])
        if "status" in filters:
            query += " AND status = ?"
            params.append(filters["status"])
        query += " ORDER BY created_at DESC"

        rows = self._conn.execute(query, params).fetchall()
        envelopes = []
        for row in rows:
            data = json.loads(row["envelope_json"])
            data.pop("@context", None)
            data.pop("@type", None)
            envelopes.append(Envelope.model_validate(data))
        return envelopes

    def save_artifact(self, artifact_id: str, content: bytes, metadata: Artifact) -> str:
        filename = f"{metadata.content_hash or artifact_id}"
        path = self.artifacts_dir / filename
        path.write_bytes(content)

        self._conn.execute(
            """INSERT OR REPLACE INTO artifacts
               (artifact_id, context_id, artifact_type, content_hash,
                storage_path, model, deterministic, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id,
                metadata.metadata.get("context_id"),
                metadata.type.value,
                metadata.content_hash,
                str(path),
                metadata.model,
                1 if metadata.deterministic else 0,
                metadata.timestamp,
            ),
        )
        self._conn.commit()
        return str(path)

    def get_artifact(self, artifact_id: str) -> tuple[bytes, Artifact] | None:
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if not row:
            return None
        path = Path(row["storage_path"])
        content = path.read_bytes() if path.exists() else b""
        artifact = Artifact(
            artifact_id=row["artifact_id"],
            type=row["artifact_type"],
            content_hash=row["content_hash"],
            storage_ref=row["storage_path"],
            model=row["model"],
            deterministic=bool(row["deterministic"]),
            timestamp=row["created_at"] or "",
        )
        return content, artifact

    def save_prov_graph(self, context_id: str, graph_turtle: str, digest: str) -> str:
        from datetime import datetime, timezone

        prov_path = self.artifacts_dir / f"{context_id}.ttl"
        prov_path.write_text(graph_turtle, encoding="utf-8")

        self._conn.execute(
            """INSERT OR REPLACE INTO prov_graphs
               (context_id, graph_turtle, graph_digest, created_at)
               VALUES (?, ?, ?, ?)""",
            (context_id, graph_turtle, digest, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()
        return str(prov_path)

    def get_prov_graph(self, context_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT graph_turtle FROM prov_graphs WHERE context_id = ?",
            (context_id,),
        ).fetchone()
        return row["graph_turtle"] if row else None

    def save_decision(self, decision: Decision) -> str:
        self._conn.execute(
            """INSERT OR REPLACE INTO decisions
               (decision_id, context_id, passed_artifact_id, outcome,
                agent_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                decision.decision_id,
                decision.context_id,
                decision.passed_artifact_id,
                json.dumps(decision.outcome),
                decision.agent_id,
                decision.created_at,
            ),
        )
        self._conn.commit()
        return decision.decision_id

    def get_decision(self, decision_id: str) -> Decision | None:
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        if not row:
            return None
        return Decision(
            decision_id=row["decision_id"],
            context_id=row["context_id"],
            passed_artifact_id=row["passed_artifact_id"],
            outcome=json.loads(row["outcome"]) if row["outcome"] else {},
            agent_id=row["agent_id"] or "",
            created_at=row["created_at"] or "",
        )

    def close(self) -> None:
        self._conn.close()
