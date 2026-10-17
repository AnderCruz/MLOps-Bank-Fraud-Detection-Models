"""Focused MLflow Registry tests using temporary stores and synthetic artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from src import model_registry


class MlflowRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.previous_tracking_uri = mlflow.get_tracking_uri()
        database_path = self.root / "registry-test.db"
        mlflow.set_tracking_uri(f"sqlite:///{database_path.as_posix()}")
        mlflow.set_experiment("Bank-Fraud-Registry-Tests")
        self.client = MlflowClient()

    def tearDown(self) -> None:
        if mlflow.active_run() is not None:
            mlflow.end_run()
        mlflow.set_tracking_uri(self.previous_tracking_uri)
        self.temporary_directory.cleanup()

    def _start_run(self, pipeline_run_id: str = "pipeline-run-123") -> str:
        run = mlflow.start_run()
        mlflow.set_tags({
            "project": "Bank-Fraud-Detection",
            "pipeline_run_id": pipeline_run_id,
            "model_count": "1",
            "git_commit": "commit-123",
            "git_branch": "feature/registry-test",
        })
        return run.info.run_id

    def _log_synthetic_model(self, model_name: str = "random_forest",
                             pipeline_run_id: str = "pipeline-run-123",
                             git_commit: str | None = "commit-123",
                             git_branch: str | None = "feature/registry-test",
                             metadata_override: dict | None = None
                             ) -> tuple[str, dict[str, Path], bytes]:
        run_id = self._start_run(pipeline_run_id)
        suffix = (
            "_state_dict.pt"
            if model_name in {"mlp", "autoencoder", "lstm", "gru"}
            else ".joblib"
        )
        model_directory = self.root / "synthetic-models" / model_name
        model_directory.mkdir(parents=True, exist_ok=True)
        artifact_path = model_directory / f"{model_name}{suffix}"
        artifact_bytes = b"synthetic model artifact; not a trained model"
        artifact_path.write_bytes(artifact_bytes)
        metadata_path = model_directory / f"{model_name}_metadata.json"
        metadata = metadata_override or {
            "model_name": model_name,
            "configuration": {"activation": "synthetic"},
            "random_seed": 42,
            "features": ["V1", "Amount"],
            "training_dataset": ["synthetic-train.parquet"],
            "validation_dataset": ["synthetic-validation.parquet"],
            "validation_metric": "Average Precision (AP)",
            "reproduced_validation_metric": 0.75,
            "provenance": {
                "git": {"commit": git_commit, "branch": git_branch},
                "run": {"run_id": pipeline_run_id},
            },
        }
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        mlflow.log_artifact(str(artifact_path), artifact_path=f"models/{model_name}")
        mlflow.log_artifact(str(metadata_path), artifact_path=f"models/{model_name}")
        return run_id, {
            "model_name": model_name,
            "artifact_path": artifact_path,
            "metadata_path": metadata_path,
        }, artifact_bytes

    def test_model_family_names_are_stable_and_unknown_names_are_rejected(self) -> None:
        self.assertEqual(
            model_registry.REGISTERED_MODEL_NAMES,
            {
                "random_forest": "bank-fraud-random-forest",
                "xgboost": "bank-fraud-xgboost",
                "logistic_regression": "bank-fraud-logistic-regression",
                "lightgbm": "bank-fraud-lightgbm",
                "mlp": "bank-fraud-mlp",
                "autoencoder": "bank-fraud-autoencoder",
                "lstm": "bank-fraud-lstm",
                "gru": "bank-fraud-gru",
            },
        )
        with self.assertRaisesRegex(ValueError, "Unknown model family"):
            model_registry.registered_model_name("not_a_model")

    def test_registers_existing_joblib_artifact_with_run_lineage_and_tags(self) -> None:
        source_run_id, record, original_bytes = self._log_synthetic_model()
        summary = model_registry.register_logged_models(
            [record], "pipeline-run-123", client=self.client
        )

        self.assertEqual(summary["registration_status"], "READY")
        self.assertEqual(len(summary["models"]), 1)
        registered = summary["models"][0]
        self.assertEqual(registered["model_name"], "random_forest")
        self.assertEqual(
            registered["registered_model_name"], "bank-fraud-random-forest"
        )
        self.assertEqual(registered["source_run_id"], source_run_id)
        self.assertEqual(registered["pipeline_run_id"], "pipeline-run-123")
        self.assertTrue(registered["source_artifact_uri"].endswith(
            "/models/random_forest/random_forest.joblib"
        ))
        self.assertTrue(registered["metadata_artifact_uri"].endswith(
            "/models/random_forest/random_forest_metadata.json"
        ))

        model_version = self.client.get_model_version(
            registered["registered_model_name"], registered["model_version"]
        )
        self.assertEqual(model_version.run_id, source_run_id)
        self.assertEqual(model_version.status, "READY")
        self.assertTrue(
            model_version.source.endswith(
                "/models/random_forest/random_forest.joblib"
            )
        )
        self.assertEqual(model_version.tags["project"], "Bank-Fraud-Detection")
        self.assertEqual(model_version.tags["model_name"], "random_forest")
        self.assertEqual(model_version.tags["pipeline_run_id"], "pipeline-run-123")
        self.assertEqual(model_version.tags["source_run_id"], source_run_id)
        self.assertEqual(model_version.tags["git_commit"], "commit-123")
        self.assertEqual(model_version.tags["git_branch"], "feature/registry-test")
        self.assertEqual(model_version.tags["validation_metric"], "Average Precision (AP)")
        self.assertEqual(model_version.tags["validation_score"], "0.75")
        self.assertFalse(any("test" in key.lower() for key in model_version.tags))
        self.assertEqual(model_version.current_stage, "None")
        registered_model = self.client.get_registered_model("bank-fraud-random-forest")
        self.assertEqual(registered_model.aliases, {})

        self.assertEqual(record["artifact_path"].read_bytes(), original_bytes)
        self.assertTrue(record["artifact_path"].name.endswith(".joblib"))
        run = self.client.get_run(source_run_id)
        summary_artifacts = self.client.list_artifacts(
            source_run_id, "registry"
        )
        self.assertEqual([item.path for item in summary_artifacts], [
            model_registry.REGISTRATION_SUMMARY_ARTIFACT
        ])
        summary_path = self.client.download_artifacts(
            source_run_id, model_registry.REGISTRATION_SUMMARY_ARTIFACT
        )
        persisted_summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        self.assertEqual(persisted_summary, summary)
        self.assertEqual(
            run.data.tags["pipeline_run_id"], registered["pipeline_run_id"]
        )

    def test_reuses_existing_registered_model_and_same_run_version(self) -> None:
        run_id, record, _ = self._log_synthetic_model()
        registered_name = model_registry.registered_model_name("random_forest")
        self.client.create_registered_model(registered_name)

        first = model_registry.register_model_artifact(
            "random_forest", record["artifact_path"], record["metadata_path"],
            "pipeline-run-123", client=self.client,
        )
        second = model_registry.register_model_artifact(
            "random_forest", record["artifact_path"], record["metadata_path"],
            "pipeline-run-123", client=self.client,
        )

        self.assertEqual(first["model_version"], second["model_version"])
        versions = self.client.search_model_versions(
            filter_string=f"name='{registered_name}'"
        )
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].run_id, run_id)

    def test_pytorch_artifact_format_and_autoencoder_score_type_are_preserved(self) -> None:
        run_id, record, artifact_bytes = self._log_synthetic_model("autoencoder")
        metadata = json.loads(record["metadata_path"].read_text(encoding="utf-8"))
        metadata["validation_metric"] = (
            "Average Precision (AP) from per-row reconstruction MSE"
        )
        metadata["configuration"]["best_validation_reconstruction_mse"] = 0.125
        record["metadata_path"].write_text(json.dumps(metadata), encoding="utf-8")
        # Replace the logged metadata bytes with the exact metadata to register.
        mlflow.log_artifact(
            str(record["metadata_path"]), artifact_path="models/autoencoder"
        )

        result = model_registry.register_model_artifact(
            "autoencoder", record["artifact_path"], record["metadata_path"],
            "pipeline-run-123", client=self.client,
        )
        version = self.client.get_model_version(
            result["registered_model_name"], result["model_version"]
        )
        self.assertEqual(version.tags["score_type"], "reconstruction_error_anomaly_score")
        self.assertEqual(version.tags["validation_reconstruction_mse"], "0.125")
        self.assertEqual(version.run_id, run_id)
        self.assertTrue(record["artifact_path"].name.endswith("_state_dict.pt"))
        self.assertEqual(record["artifact_path"].read_bytes(), artifact_bytes)

    def test_missing_artifact_metadata_and_malformed_metadata_fail_clearly(self) -> None:
        self._start_run()
        directory = self.root / "invalid"
        directory.mkdir()
        artifact_path = directory / "random_forest.joblib"
        artifact_path.write_bytes(b"synthetic")
        metadata_path = directory / "random_forest_metadata.json"

        with self.assertRaisesRegex(FileNotFoundError, "Model artifact"):
            model_registry.register_model_artifact(
                "random_forest", directory / "missing.joblib", metadata_path,
                "pipeline-run-123", client=self.client,
            )
        with self.assertRaisesRegex(FileNotFoundError, "metadata"):
            model_registry.register_model_artifact(
                "random_forest", artifact_path, metadata_path,
                "pipeline-run-123", client=self.client,
            )

        metadata_path.write_text("{bad json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "malformed"):
            model_registry.register_model_artifact(
                "random_forest", artifact_path, metadata_path,
                "pipeline-run-123", client=self.client,
            )
        valid_metadata = {
            "model_name": "random_forest",
            "provenance": {
                "git": {"commit": "commit-123", "branch": "feature/registry-test"},
                "run": {"run_id": "pipeline-run-123"},
            },
        }
        metadata_path.write_text(json.dumps(valid_metadata), encoding="utf-8")
        with self.assertRaisesRegex(FileNotFoundError, "source MLflow run"):
            model_registry.register_model_artifact(
                "random_forest", artifact_path, metadata_path,
                "pipeline-run-123", client=self.client,
            )
        self.assertEqual(self.client.search_registered_models(), [])

    def test_missing_git_provenance_is_recorded_as_unknown(self) -> None:
        run_id, record, _ = self._log_synthetic_model(
            git_commit=None, git_branch=None
        )
        mlflow.set_tags({"git_commit": "unknown", "git_branch": "unknown"})

        result = model_registry.register_model_artifact(
            "random_forest", record["artifact_path"], record["metadata_path"],
            "pipeline-run-123", client=self.client,
        )
        version = self.client.get_model_version(
            result["registered_model_name"], result["model_version"]
        )
        self.assertEqual(version.run_id, run_id)
        self.assertEqual(version.tags["git_commit"], "unknown")
        self.assertEqual(version.tags["git_branch"], "unknown")

    def test_unavailable_validation_evidence_is_not_invented(self) -> None:
        metadata = {
            "model_name": "random_forest",
            "provenance": {
                "git": {"commit": "commit-123", "branch": "feature/registry-test"},
                "run": {"run_id": "pipeline-run-123"},
            },
        }
        _, record, _ = self._log_synthetic_model(metadata_override=metadata)
        result = model_registry.register_model_artifact(
            "random_forest", record["artifact_path"], record["metadata_path"],
            "pipeline-run-123", client=self.client,
        )
        version = self.client.get_model_version(
            result["registered_model_name"], result["model_version"]
        )
        self.assertEqual(version.tags["validation_metric"], "not_available")
        self.assertEqual(version.tags["validation_score"], "not_available")
        self.assertIsNone(result["validation_metric"])
        self.assertIsNone(result["validation_score"])

    def test_registration_requires_an_active_run(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "active MLflow run"):
            model_registry.register_model_artifact(
                "random_forest", Path("missing.joblib"), Path("missing.json"),
                "pipeline-run-123", client=self.client,
            )

    def test_only_selected_artifacts_are_registered_and_summary_is_machine_readable(
        self,
    ) -> None:
        _, selected_record, _ = self._log_synthetic_model()
        summary = model_registry.register_logged_models(
            [selected_record], "pipeline-run-123", client=self.client
        )
        self.assertEqual(
            [record["model_name"] for record in summary["models"]],
            ["random_forest"],
        )
        self.assertEqual(summary["schema_version"], 1)
        self.assertEqual(
            summary["registration_status"], "READY"
        )
        self.assertIsNotNone(self.client.get_registered_model("bank-fraud-random-forest"))
        with self.assertRaises(MlflowException):
            self.client.get_registered_model("bank-fraud-mlp")

    def test_partial_failure_is_reported_without_rolling_back_success(self) -> None:
        self._start_run()
        records = [
            {"model_name": "random_forest", "artifact_path": "rf", "metadata_path": "rf.json"},
            {"model_name": "mlp", "artifact_path": "mlp", "metadata_path": "mlp.json"},
        ]
        successful = {
            "model_name": "random_forest",
            "registered_model_name": "bank-fraud-random-forest",
            "model_version": "1",
            "source_run_id": "source-run",
            "source_artifact_uri": "runs:/source-run/models/random_forest/random_forest.joblib",
            "metadata_artifact_uri": "runs:/source-run/models/random_forest/random_forest_metadata.json",
            "pipeline_run_id": "pipeline-run-123",
            "registration_status": "READY",
            "validation_metric": "Average Precision (AP)",
            "validation_score": 0.75,
        }
        with patch.object(
            model_registry,
            "register_model_artifact",
            side_effect=[successful, RuntimeError("synthetic registry failure")],
        ):
            with self.assertRaises(model_registry.ModelRegistryRegistrationError) as caught:
                model_registry.register_logged_models(
                    records, "pipeline-run-123", client=self.client
                )

        summary = caught.exception.summary
        self.assertEqual(summary["registration_status"], "PARTIAL_FAILURE")
        self.assertEqual(summary["models"][0]["registration_status"], "READY")
        self.assertEqual(summary["models"][1]["registration_status"], "FAILED")
        logged_summary = self.client.list_artifacts(
            self.client.get_run(summary["source_run_id"]).info.run_id, "registry"
        )
        self.assertEqual(len(logged_summary), 1)

    def test_version_wait_handles_ready_failed_and_pending_states(self) -> None:
        pending = Mock(status="PENDING_REGISTRATION", status_message=None)
        ready = Mock(status="READY")
        client = Mock()
        client.get_model_version.side_effect = [pending, ready]
        with patch.object(model_registry.time, "monotonic", side_effect=[0.0, 0.1]):
            result = model_registry._wait_for_terminal_version(
                client, "bank-fraud-random-forest", "1", 10, 0.01
            )
        self.assertIs(result, ready)
        client.get_model_version.assert_called_with("bank-fraud-random-forest", "1")

        failed = Mock(status="FAILED", status_message="source unavailable")
        client.get_model_version.side_effect = [failed]
        with self.assertRaisesRegex(RuntimeError, "source unavailable"):
            model_registry._wait_for_terminal_version(
                client, "bank-fraud-random-forest", "1", 10, 0.01
            )

        pending = Mock(status="PENDING_REGISTRATION", status_message=None)
        client.get_model_version.side_effect = [pending]
        with self.assertRaisesRegex(
            model_registry.ModelVersionStateError, "remained pending"
        ) as caught:
            model_registry._wait_for_terminal_version(
                client, "bank-fraud-random-forest", "1", 0, 0.01
            )
        self.assertEqual(caught.exception.registration_status, "PENDING_REGISTRATION")


if __name__ == "__main__":
    unittest.main()
