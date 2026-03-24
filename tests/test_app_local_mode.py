"""Tests for api/app.py local mode switching."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Add api/ to sys.path so chalicelib imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))


try:
    import chalice  # noqa: F401
    _HAS_CHALICE = True
except ImportError:
    _HAS_CHALICE = False


class TestLocalModeSwitching:
    """Verify that JHCONTEXT_LOCAL env var controls storage backend selection."""

    @pytest.mark.skipif(not _HAS_CHALICE, reason="chalice not installed")
    def test_local_mode_uses_sqlite(self, tmp_path):
        """When JHCONTEXT_LOCAL=1, get_storage() returns SQLiteStorage."""
        with mock.patch.dict(os.environ, {
            "JHCONTEXT_LOCAL": "1",
            "JHCONTEXT_DATA_DIR": str(tmp_path),
        }):
            import app as app_module
            # Reset singletons
            app_module._storage = None
            app_module._pii_vault = None
            app_module._LOCAL_MODE = True

            storage = app_module.get_storage()
            from chalicelib.storage.sqlite import SQLiteStorage
            assert isinstance(storage, SQLiteStorage)

            vault = app_module.get_pii_vault()
            from chalicelib.storage.sqlite_pii_vault import SQLitePIIVault
            assert isinstance(vault, SQLitePIIVault)

            # Cleanup
            storage.close()
            vault.close()
            app_module._storage = None
            app_module._pii_vault = None

    def test_default_mode_is_not_local(self):
        """Without JHCONTEXT_LOCAL, _LOCAL_MODE should be False."""
        with mock.patch.dict(os.environ, {}, clear=True):
            val = os.environ.get("JHCONTEXT_LOCAL", "").lower() in ("1", "true", "yes")
            assert val is False


class TestSQLiteStorageRoundTrip:
    """End-to-end test: create envelope via SQLite, retrieve it, verify fields."""

    def test_full_roundtrip(self, tmp_path):
        from chalicelib.storage.sqlite import SQLiteStorage
        from jhcontext import EnvelopeBuilder, RiskLevel, PROVGraph
        from jhcontext.models import Decision

        storage = SQLiteStorage(
            db_path=str(tmp_path / "data.db"),
            artifacts_dir=str(tmp_path / "artifacts"),
        )

        # 1. Create and save envelope
        env = (
            EnvelopeBuilder()
            .set_producer("did:test:roundtrip")
            .set_scope("healthcare_test")
            .set_risk_level(RiskLevel.HIGH)
            .set_human_oversight(True)
            .sign("did:test:roundtrip")
            .build()
        )
        ctx_id = storage.save_envelope(env)

        # 2. Create and save PROV graph
        prov = PROVGraph(context_id=ctx_id)
        prov.add_agent("did:test:sensor", "Sensor Agent", role="sensor")
        prov.add_entity("art-sensor", "Sensor output", artifact_type="token_sequence")
        prov.add_activity("act-sensor", "data_collection")
        prov.was_generated_by("art-sensor", "act-sensor")
        prov.was_associated_with("act-sensor", "did:test:sensor")

        turtle = prov.serialize("turtle")
        storage.save_prov_graph(ctx_id, turtle, prov.digest())

        # 3. Save a decision
        decision = Decision(
            decision_id="dec-test-001",
            context_id=ctx_id,
            passed_artifact_id="art-sensor",
            outcome={"recommendation": "continue_treatment", "confidence": 0.87},
            agent_id="did:test:decision-agent",
            created_at="2026-03-24T10:00:00Z",
        )
        storage.save_decision(decision)

        # 4. Retrieve everything and verify
        retrieved_env = storage.get_envelope(ctx_id)
        assert retrieved_env is not None
        assert retrieved_env.scope == "healthcare_test"
        assert retrieved_env.compliance.risk_level == RiskLevel.HIGH
        assert retrieved_env.proof.content_hash is not None

        retrieved_prov = storage.get_prov_graph(ctx_id)
        assert retrieved_prov is not None
        assert "prov:" in retrieved_prov

        retrieved_dec = storage.get_decision("dec-test-001")
        assert retrieved_dec is not None
        assert retrieved_dec.outcome["confidence"] == 0.87

        # 5. List with filters
        envs = storage.list_envelopes(scope="healthcare_test")
        assert len(envs) == 1

        envs_wrong = storage.list_envelopes(scope="nonexistent")
        assert len(envs_wrong) == 0

        storage.close()
