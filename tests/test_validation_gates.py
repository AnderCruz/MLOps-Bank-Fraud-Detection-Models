"""Synthetic unit tests for Validation Gates policy and report behavior."""

from __future__ import annotations

import json
from pathlib import Path
import copy
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

from src import validation_gates as gates
from src.inference import EXPECTED_FEATURES


def test_policy(threshold: float | None = 0.5) -> gates.ValidationPolicy:
    return gates.ValidationPolicy(
        policy_id="synthetic-policy", version="test",
        require_quality_threshold=True, require_source_record=True,
        require_registry_registration=False,
        quality_thresholds={"random_forest": {
            "metric": "average_precision", "operator": "minimum", "value": threshold,
        }},
    )


class ValidationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.artifact = self.root / "random_forest.joblib"
        self.artifact.write_bytes(b"synthetic artifact")
        self.metadata = self.root / "random_forest_metadata.json"
        self.metadata.write_text(json.dumps({
            "model_name": "random_forest", "random_seed": 42,
            "features": list(EXPECTED_FEATURES), "training_dataset": ["train.parquet"],
            "validation_dataset": ["validation.parquet"],
            "validation_metric": "Average Precision (AP)",
            "reproduced_validation_metric": 0.75, "configuration": {},
            "provenance": {"run": {"run_id": "pipeline-1"}},
        }), encoding="utf-8")
        self.candidate = gates.CandidateEvidence(
            model_family="random_forest", artifact_path=self.artifact,
            metadata_path=self.metadata, artifact_uri="models/random_forest.joblib",
            metadata_uri="models/random_forest_metadata.json", artifact_sha256=None,
            metadata_sha256=None, training_run_id="training-1",
            artifact_import_run_id=None, pipeline_run_id="pipeline-1",
            source_run_status="FINISHED", lineage_verified=True,
            metrics=(gates.MetricEvidence(
                "average_precision", 0.75, "synthetic-validation-record",
                "average precision over continuous fraud probabilities",
            ),), artifact_load_verified=True,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assess(self, candidate=None, policy=None):
        return gates.assess_candidate(
            candidate or self.candidate, policy or test_policy(),
            artifact_validator=lambda _: (True, "synthetic strict loader check"),
        )

    def test_valid_candidate_passes_configured_gates_deterministically(self) -> None:
        first = self.assess()
        second = self.assess()
        self.assertEqual(first["decision"], "PASS")
        self.assertEqual(first["gates"], second["gates"])
        self.assertEqual(first["decision"], second["decision"])
        self.assertFalse(first["production_approval"])
        self.assertEqual(first["lineage"]["training_run_id"], "training-1")
        normalized_first = copy.deepcopy(first)
        normalized_second = copy.deepcopy(second)
        for normalized in (normalized_first, normalized_second):
            normalized.pop("report_id")
            normalized.pop("validated_at_utc")
        self.assertEqual(
            json.dumps(normalized_first, sort_keys=True),
            json.dumps(normalized_second, sort_keys=True),
        )

    def test_undefined_quality_threshold_is_insufficient_evidence(self) -> None:
        report = self.assess(policy=test_policy(None))
        self.assertEqual(report["decision"], "INSUFFICIENT_EVIDENCE")
        quality = next(g for g in report["gates"] if g["name"] == "quality_threshold")
        self.assertEqual(quality["status"], "INSUFFICIENT_EVIDENCE")
        self.assertIsNone(quality["threshold"])

    def test_missing_artifact_metadata_and_malformed_metadata_fail(self) -> None:
        missing_artifact = self.assess(gates.CandidateEvidence(**{
            **self.candidate.__dict__, "artifact_path": self.root / "missing.joblib",
        }))
        self.assertEqual(missing_artifact["decision"], "FAIL")
        missing_metadata = self.assess(gates.CandidateEvidence(**{
            **self.candidate.__dict__, "metadata_path": self.root / "missing.json",
        }))
        self.assertEqual(missing_metadata["decision"], "FAIL")
        self.metadata.write_text("{bad json", encoding="utf-8")
        malformed = self.assess()
        self.assertEqual(malformed["decision"], "FAIL")

    def test_metadata_identity_feature_order_and_hash_mismatches_fail(self) -> None:
        data = json.loads(self.metadata.read_text(encoding="utf-8"))
        data["model_name"] = "xgboost"
        self.metadata.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.assess()["decision"], "FAIL")
        data["model_name"] = "random_forest"
        data["features"] = list(reversed(EXPECTED_FEATURES))
        self.metadata.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.assess()["decision"], "FAIL")
        data["features"] = list(EXPECTED_FEATURES)
        self.metadata.write_text(json.dumps(data), encoding="utf-8")
        wrong_hash = gates.CandidateEvidence(**{
            **self.candidate.__dict__, "artifact_sha256": "0" * 64,
        })
        self.assertEqual(self.assess(wrong_hash)["decision"], "FAIL")

    def test_missing_or_unverified_artifact_compatibility_is_not_pass(self) -> None:
        candidate = gates.CandidateEvidence(**{
            **self.candidate.__dict__, "artifact_load_verified": None,
        })
        report = gates.assess_candidate(candidate, test_policy())
        self.assertEqual(report["decision"], "INSUFFICIENT_EVIDENCE")

    def test_unknown_model_family_is_rejected(self) -> None:
        candidate = gates.CandidateEvidence(**{
            **self.candidate.__dict__, "model_family": "not-a-model",
        })
        with self.assertRaisesRegex(ValueError, "Unknown model family"):
            self.assess(candidate)

    def test_missing_source_lineage_is_insufficient_and_mismatch_fails(self) -> None:
        missing = gates.CandidateEvidence(**{
            **self.candidate.__dict__, "training_run_id": None,
            "source_run_status": None, "lineage_verified": None,
        })
        self.assertEqual(self.assess(missing)["decision"], "INSUFFICIENT_EVIDENCE")
        mismatch = gates.CandidateEvidence(**{
            **self.candidate.__dict__, "lineage_verified": False,
        })
        self.assertEqual(self.assess(mismatch)["decision"], "FAIL")

    def test_import_record_is_not_reported_as_training_run(self) -> None:
        imported = gates.CandidateEvidence(**{
            **self.candidate.__dict__, "training_run_id": None,
            "artifact_import_run_id": "import-record-1",
        })
        report = self.assess(imported)
        self.assertEqual(report["lineage"]["training_run_id"], None)
        self.assertEqual(report["lineage"]["artifact_import_run_id"], "import-record-1")
        lineage = next(g for g in report["gates"] if g["name"] == "provenance_lineage")
        self.assertEqual(lineage["record_type"], "artifact_import")

    def test_optional_git_and_unregistered_candidate_are_explicitly_not_applicable(self) -> None:
        report = self.assess()
        statuses = {gate["name"]: gate["status"] for gate in report["gates"]}
        self.assertEqual(statuses["git_provenance"], "NOT_APPLICABLE")
        self.assertEqual(statuses["registry_lineage"], "NOT_APPLICABLE")

    def test_conflicting_optional_git_provenance_fails_explicitly(self) -> None:
        candidate = gates.CandidateEvidence(**{
            **self.candidate.__dict__, "git_commit": "commit-from-run",
            "metadata_git_commit": "different-commit",
        })
        report = self.assess(candidate)
        git_gate = next(g for g in report["gates"] if g["name"] == "git_provenance")
        self.assertEqual(git_gate["status"], "FAIL")

    def test_registry_lineage_is_checked_only_when_supplied(self) -> None:
        candidate = gates.CandidateEvidence(**{
            **self.candidate.__dict__, "registered_model_name": "bank-fraud-random-forest",
            "registered_model_version": "2", "registry_lineage_verified": False,
        })
        report = self.assess(candidate)
        self.assertEqual(report["decision"], "FAIL")
        registry_gate = next(g for g in report["gates"] if g["name"] == "registry_lineage")
        self.assertEqual(registry_gate["status"], "FAIL")

    def test_registry_verifier_checks_registered_source_and_tags(self) -> None:
        candidate = gates.CandidateEvidence(**{
            **self.candidate.__dict__,
            "registered_model_name": "bank-fraud-random-forest",
            "registered_model_version": "3",
        })
        artifact_uri = "runs:/training-1/models/random_forest/random_forest.joblib"
        metadata_uri = "runs:/training-1/models/random_forest/random_forest_metadata.json"
        version = SimpleNamespace(
            run_id="training-1", source=artifact_uri,
            tags={
                "source_run_id": "training-1", "pipeline_run_id": "pipeline-1",
                "source_artifact_uri": artifact_uri, "metadata_artifact_uri": metadata_uri,
                "model_name": "random_forest", "registered_model_name": "bank-fraud-random-forest",
            },
        )

        class FakeClient:
            def get_model_version(self, name, version_number):
                self.request = (name, version_number)
                return version

        client = FakeClient()
        self.assertEqual(gates.verify_registry_lineage(candidate, client), (
            True, "Registered version source run, model, and artifact metadata tags match",
        ))
        self.assertEqual(client.request, ("bank-fraud-random-forest", "3"))

    def test_metric_validation_and_autoencoder_metric_semantics(self) -> None:
        missing_metric = gates.CandidateEvidence(**{
            **self.candidate.__dict__, "metrics": (),
        })
        self.assertEqual(self.assess(missing_metric)["decision"], "INSUFFICIENT_EVIDENCE")
        for invalid in (None, "bad", float("nan"), float("inf"), -0.1, 1.1):
            with self.subTest(value=invalid):
                candidate = gates.CandidateEvidence(**{
                    **self.candidate.__dict__,
                    "metrics": (gates.MetricEvidence("average_precision", invalid, "source", "AP"),),
                })
                report = self.assess(candidate)
                self.assertEqual(report["decision"], "FAIL")
        auto = gates.CandidateEvidence(**{
            **self.candidate.__dict__, "model_family": "autoencoder",
            "artifact_path": self.root / "autoencoder_state_dict.pt",
            "metadata_path": self.root / "autoencoder_metadata.json",
            "artifact_uri": "models/autoencoder_state_dict.pt",
            "metadata_uri": "models/autoencoder_metadata.json",
            "training_run_id": "ae-training", "pipeline_run_id": "pipeline-ae",
            "metrics": (gates.MetricEvidence(
                "validation_reconstruction_mse", 0.2, "metadata.configuration",
                "reconstruction MSE; anomaly model checkpoint metric",
            ),),
        })
        auto.artifact_path.write_bytes(b"synthetic state dict")
        auto.metadata_path.write_text(json.dumps({
            "model_name": "autoencoder", "random_seed": 42,
            "features": list(EXPECTED_FEATURES), "training_dataset": ["train"],
            "validation_dataset": ["validation"], "validation_metric": "reconstruction MSE",
            "reproduced_validation_metric": 0.2, "configuration": {},
            "provenance": {"run": {"run_id": "pipeline-ae"}},
        }), encoding="utf-8")
        report = gates.assess_candidate(
            auto, gates.ValidationPolicy(
                "ae-policy", "1", True, True, False,
                {"autoencoder": {"metric": "validation_reconstruction_mse", "operator": "maximum", "value": 0.3}},
            ), artifact_validator=lambda _: (True, "synthetic strict autoencoder load"),
        )
        self.assertEqual(report["decision"], "PASS")
        self.assertEqual(report["metrics"][0]["name"], "validation_reconstruction_mse")
        self.assertNotIn("fraud_probability", report["metrics"][0]["interpretation"])

    def test_report_excludes_test_metrics_and_distinguishes_registration_from_approval(self) -> None:
        candidate = gates.CandidateEvidence(**{
            **self.candidate.__dict__,
            "metrics": self.candidate.metrics + (gates.MetricEvidence(
                "test_ap", 0.99, "test-evaluation", "prohibited test metric",
            ),),
        })
        report = self.assess(candidate)
        serialized = json.dumps(report).lower()
        self.assertNotIn("test_ap", serialized)
        self.assertNotIn("test_roc_auc", serialized)
        self.assertEqual(report["decision"], "FAIL")
        self.assertFalse(report["production_approval"])
        self.assertEqual(report["schema_version"], gates.SCHEMA_VERSION)

    def test_policy_rejects_unsupported_fields_and_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps({
                "schema_version": gates.SCHEMA_VERSION, "policy_id": "bad", "version": "1",
                "require_quality_threshold": True, "require_source_record": True,
                "require_registry_registration": False, "quality_thresholds": {
                    "random_forest": {"metric": "roc_auc", "operator": "minimum", "value": 0.9},
                },
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "metric/operator"):
                gates.load_policy(path)

    def test_repository_policy_has_no_invented_quality_cutoffs(self) -> None:
        policy = gates.load_policy(Path("configs/validation_policy_v1.json"))
        self.assertTrue(policy.require_quality_threshold)
        self.assertEqual(set(policy.quality_thresholds), set(gates.MODEL_FAMILIES))
        self.assertTrue(all(item["value"] is None for item in policy.quality_thresholds.values()))

    def test_report_write_is_unique_and_write_failure_is_explicit(self) -> None:
        report = self.assess()
        with TemporaryDirectory() as directory:
            output = gates.write_report(report, Path(directory))
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads(output.read_text())["decision"], "PASS")
            with self.assertRaises(gates.ValidationInfrastructureError):
                gates.write_report(report, Path(directory))
            blocker = Path(directory) / "not-a-directory"
            blocker.write_text("blocking file", encoding="utf-8")
            with self.assertRaises(gates.ValidationInfrastructureError):
                gates.write_report(report, blocker / "child")


if __name__ == "__main__":
    unittest.main()
