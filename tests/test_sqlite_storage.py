"""Tests for the vendored SQLite storage backend."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Add api/ to sys.path so chalicelib imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from chalicelib.storage.sqlite import SQLiteStorage
from chalicelib.storage.sqlite_pii_vault import SQLitePIIVault
from jhcontext import EnvelopeBuilder, RiskLevel, PROVGraph
from jhcontext.models import Decision


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def storage(tmp_dir):
    s = SQLiteStorage(db_path=str(tmp_dir / "data.db"), artifacts_dir=str(tmp_dir / "artifacts"))
    yield s
    s.close()


@pytest.fixture
def pii_vault(tmp_dir):
    v = SQLitePIIVault(db_path=str(tmp_dir / "pii_vault.db"))
    yield v
    v.close()


# ── SQLiteStorage tests ─────────────────────────────────────────


class TestSQLiteStorage:
    def test_save_and_get_envelope(self, storage):
        env = (
            EnvelopeBuilder()
            .set_producer("did:test:agent")
            .set_scope("test_scope")
            .set_risk_level(RiskLevel.HIGH)
            .build()
        )
        ctx_id = storage.save_envelope(env)
        assert ctx_id == env.context_id

        retrieved = storage.get_envelope(ctx_id)
        assert retrieved is not None
        assert retrieved.context_id == env.context_id
        assert retrieved.scope == "test_scope"
        assert retrieved.compliance.risk_level == RiskLevel.HIGH

    def test_get_nonexistent_envelope(self, storage):
        assert storage.get_envelope("ctx-nonexistent") is None

    def test_list_envelopes(self, storage):
        for scope in ("healthcare", "education", "healthcare"):
            env = (
                EnvelopeBuilder()
                .set_producer("did:test:agent")
                .set_scope(scope)
                .set_risk_level(RiskLevel.HIGH)
                .build()
            )
            storage.save_envelope(env)

        all_envs = storage.list_envelopes()
        assert len(all_envs) == 3

        healthcare = storage.list_envelopes(scope="healthcare")
        assert len(healthcare) == 2

        education = storage.list_envelopes(scope="education")
        assert len(education) == 1

    def test_list_envelopes_filter_by_risk(self, storage):
        for risk in (RiskLevel.HIGH, RiskLevel.LOW, RiskLevel.HIGH):
            env = (
                EnvelopeBuilder()
                .set_producer("did:test:agent")
                .set_scope("test")
                .set_risk_level(risk)
                .build()
            )
            storage.save_envelope(env)

        high = storage.list_envelopes(risk_level="high")
        assert len(high) == 2

    def test_save_and_get_prov_graph(self, storage):
        prov = PROVGraph(context_id="ctx-test")
        prov.add_agent("agent-1", "Test Agent", role="tester")
        prov.add_entity("art-1", "Test Artifact", artifact_type="token_sequence")
        prov.add_activity("act-1", "test_activity")
        prov.was_generated_by("art-1", "act-1")
        prov.was_associated_with("act-1", "agent-1")

        turtle = prov.serialize("turtle")
        storage.save_prov_graph("ctx-test", turtle, "sha256:abc")

        retrieved = storage.get_prov_graph("ctx-test")
        assert retrieved is not None
        assert "prov:Entity" in retrieved or "Entity" in retrieved

    def test_get_nonexistent_prov(self, storage):
        assert storage.get_prov_graph("ctx-nonexistent") is None

    def test_save_and_get_decision(self, storage):
        decision = Decision(
            decision_id="dec-001",
            context_id="ctx-test",
            passed_artifact_id="art-1",
            outcome={"recommendation": "approve", "confidence": 0.92},
            agent_id="did:test:decision-agent",
            created_at="2026-03-24T10:00:00Z",
        )
        dec_id = storage.save_decision(decision)
        assert dec_id == "dec-001"

        retrieved = storage.get_decision("dec-001")
        assert retrieved is not None
        assert retrieved.context_id == "ctx-test"
        assert retrieved.outcome["confidence"] == 0.92
        assert retrieved.agent_id == "did:test:decision-agent"

    def test_get_nonexistent_decision(self, storage):
        assert storage.get_decision("dec-nonexistent") is None

    def test_save_and_get_artifact(self, storage):
        from jhcontext.models import Artifact, ArtifactType

        content = b"test artifact content"
        metadata = Artifact(
            artifact_id="art-test-001",
            type=ArtifactType.TOKEN_SEQUENCE,
            content_hash="sha256:testbytes",
            storage_ref="",
            model=None,
            deterministic=False,
            timestamp="2026-03-24T10:00:00Z",
        )
        path = storage.save_artifact("art-test-001", content, metadata)
        assert Path(path).exists()

        result = storage.get_artifact("art-test-001")
        assert result is not None
        retrieved_content, retrieved_meta = result
        assert retrieved_content == content
        assert retrieved_meta.artifact_id == "art-test-001"
        assert retrieved_meta.content_hash == "sha256:testbytes"

    def test_get_nonexistent_artifact(self, storage):
        assert storage.get_artifact("art-nonexistent") is None

    def test_envelope_overwrite(self, storage):
        """INSERT OR REPLACE should update existing envelope."""
        env1 = (
            EnvelopeBuilder()
            .set_producer("did:test:v1")
            .set_scope("test")
            .set_risk_level(RiskLevel.LOW)
            .build()
        )
        ctx_id = env1.context_id

        # Manually create env2 with same context_id
        env2 = (
            EnvelopeBuilder()
            .set_producer("did:test:v2")
            .set_scope("test_updated")
            .set_risk_level(RiskLevel.HIGH)
            .build()
        )
        # Override context_id to match env1
        env2.context_id = ctx_id

        storage.save_envelope(env1)
        storage.save_envelope(env2)

        retrieved = storage.get_envelope(ctx_id)
        assert retrieved.scope == "test_updated"


# ── SQLitePIIVault tests ────────────────────────────────────────


class TestSQLitePIIVault:
    def test_store_and_retrieve(self, pii_vault):
        pii_vault.store("tok-001", "ctx-test", "john@example.com", "email")
        result = pii_vault.retrieve("tok-001")
        assert result == "john@example.com"

    def test_retrieve_nonexistent(self, pii_vault):
        assert pii_vault.retrieve("tok-nonexistent") is None

    def test_retrieve_by_context(self, pii_vault):
        pii_vault.store("tok-001", "ctx-a", "john@example.com", "email")
        pii_vault.store("tok-002", "ctx-a", "John Doe", "name")
        pii_vault.store("tok-003", "ctx-b", "jane@example.com", "email")

        tokens_a = pii_vault.retrieve_by_context("ctx-a")
        assert len(tokens_a) == 2
        assert {t["token_id"] for t in tokens_a} == {"tok-001", "tok-002"}

        tokens_b = pii_vault.retrieve_by_context("ctx-b")
        assert len(tokens_b) == 1

    def test_purge_by_context(self, pii_vault):
        pii_vault.store("tok-001", "ctx-a", "john@example.com", "email")
        pii_vault.store("tok-002", "ctx-a", "John Doe", "name")
        pii_vault.store("tok-003", "ctx-b", "jane@example.com", "email")

        deleted = pii_vault.purge_by_context("ctx-a")
        assert deleted == 2

        assert pii_vault.retrieve("tok-001") is None
        assert pii_vault.retrieve("tok-002") is None
        assert pii_vault.retrieve("tok-003") == "jane@example.com"

    def test_purge_expired(self, pii_vault):
        pii_vault.store("tok-001", "ctx-a", "old@example.com", "email")
        # Manually backdate the token
        pii_vault._conn.execute(
            "UPDATE pii_tokens SET created_at = '2020-01-01T00:00:00Z' WHERE token_id = 'tok-001'"
        )
        pii_vault._conn.commit()

        pii_vault.store("tok-002", "ctx-a", "new@example.com", "email")

        deleted = pii_vault.purge_expired("2025-01-01T00:00:00Z")
        assert deleted == 1
        assert pii_vault.retrieve("tok-001") is None
        assert pii_vault.retrieve("tok-002") == "new@example.com"
