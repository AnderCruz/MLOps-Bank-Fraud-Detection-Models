"""Synthetic tests for evidence classification and evaluation-design reports."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.evidence_readiness import (
    MODEL_FAMILIES,
    _evaluation_design,
    _operational_register,
    build_report,
    classify_evidence,
    write_report,
)


def report_inputs() -> dict:
    models = {}
    evaluation_models = {}
    common_models = {}
    native_models = {}
    metadata = {}
    artifact_hashes = {}
    metadata_hashes = {}
    tracking = {}
    thresholds = {}
    for family in MODEL_FAMILIES:
        artifact_hash = f"artifact-{family}"
        metadata_hash = f"metadata-{family}"
        import_run = family == "xgboost"
        model_path = f"models/{family}.bin"
        metadata_path = f"models/{family}.json"
        models[family] = {
            "canonical_artifact": {
                "path": model_path,
                "sha256_expected": artifact_hash,
            },
            "metadata": {
                "path": metadata_path,
                "sha256_expected": metadata_hash,
                "preprocessing": "scaled",
            },
            "lineage": {
                "record_type": "artifact_import" if import_run else "training_run",
                "training_run_id": None if import_run else f"training-{family}",
                "artifact_import_run_id": f"import-{family}" if import_run else None,
                "pipeline_run_id": None if import_run else f"pipeline-{family}",
                "provenance_limitation": "training history unknown" if import_run else None,
            },
            "score_type": "anomaly_score" if family == "autoencoder" else "fraud_probability",
        }
        evaluation_models[family] = {
            "artifact_path": model_path,
            "artifact_sha256": artifact_hash,
            "metadata_path": metadata_path,
            "metadata_sha256": metadata_hash,
        }
        common_models[family] = {
            "metrics": {"average_precision": 0.5, "roc_auc": 0.6},
            "row_count": 10,
            "target_class_counts": {"0": 8, "1": 2},
        }
        native_models[family] = common_models[family]
        metadata[family] = {
            "model_name": family,
            "features": ["V1", "Amount"],
            "configuration": {"synthetic": True},
            "provenance": {"git": {"commit": "metadata-only", "branch": "metadata-only"}},
        }
        artifact_hashes[family] = artifact_hash
        metadata_hashes[family] = metadata_hash
        tracking[family] = {
            "available": True,
            "record_type_tag": "artifact_import" if import_run else None,
            "training_run_recovered_tag": "false" if import_run else None,
            "pipeline_run_id_tag": None if import_run else f"pipeline-{family}",
            "git_commit_tag": None,
            "git_branch_tag": None,
            "status": "FINISHED",
            "metric_values": {},
            "artifact_paths": [model_path, metadata_path]
            + (["artifact_import_manifest.json"] if import_run else []),
        }
        thresholds[family] = {"value": None, "metric": "average_precision"}
    return {
        "inventory": {"inventory_id": "synthetic-inventory", "models": models},
        "evaluation": {
            "evaluation_id": "synthetic-evaluation",
            "created_at_utc": "2026-01-01T00:00:00Z",
            "evaluation_split": {"identifier": "validation"},
            "holdout_disclosure": "Prior test use; not blind.",
            "models": evaluation_models,
            "common_cohort_results": {"models": common_models},
            "native_cohort_results": {"models": native_models},
        },
        "policy": {"policy_id": "synthetic-policy", "effective_status": "incomplete", "quality_thresholds": thresholds},
        "analysis_sources": {
            "paired_ap_uncertainty": {"path": "synthetic/uncertainty.json", "sha256": "x"},
            "temporal_stability": {"path": "synthetic/stability.json", "sha256": "y"},
        },
        "metadata_by_model": metadata,
        "artifact_hashes": artifact_hashes,
        "metadata_hashes": metadata_hashes,
        "tracking_records": tracking,
        "registry": {"inspection": "read_only", "registered_model_count": 0, "registered_model_names": []},
        "report_id": "synthetic-report",
        "created_at_utc": "2026-01-02T00:00:00Z",
    }


def build_synthetic_report() -> dict:
    values = report_inputs()
    return build_report(**values)


class EvidenceReadinessTests(unittest.TestCase):
    def test_evidence_classification_distinguishes_empirical_derived_and_missing(self) -> None:
        self.assertEqual(classify_evidence("training_run"), "EMPIRICAL_TRAINING_EVIDENCE")
        self.assertEqual(classify_evidence("validation_evaluation"), "EMPIRICAL_VALIDATION_EVIDENCE")
        self.assertEqual(classify_evidence("derived_analysis"), "DERIVED_ANALYSIS")
        self.assertEqual(classify_evidence("missing"), "MISSING")
        self.assertEqual(classify_evidence("unknown"), "UNVERIFIED")

    def test_synthetic_fixture_is_never_classified_as_empirical(self) -> None:
        self.assertEqual(classify_evidence("training_run", is_synthetic=True), "SYNTHETIC_TEST_EVIDENCE")

    def test_metadata_git_values_do_not_substitute_for_mlflow_tags(self) -> None:
        report = build_synthetic_report()
        git = report["evidence_provenance_audit"]["models"]["random_forest"]["lineage"]["git_provenance"]
        self.assertIsNone(git["mlflow_commit_tag"])
        self.assertEqual(git["status"], "UNVERIFIED")
        self.assertFalse(git["metadata_git_fields_are_independent_evidence"])

    def test_imported_training_history_is_explicitly_unverified(self) -> None:
        report = build_synthetic_report()
        model = report["evidence_provenance_audit"]["models"]["xgboost"]
        self.assertEqual(model["lineage"]["tracking_record_classification"], "VERIFIED_ARTIFACT_IMPORT_EVENT")
        self.assertEqual(model["lineage"]["training_provenance_classification"], "UNVERIFIED")
        self.assertFalse(model["lineage"]["original_training_recovered"])

    def test_historical_reference_metric_is_not_attributed_to_current_artifact(self) -> None:
        report = build_synthetic_report()
        for model in report["evidence_provenance_audit"]["models"].values():
            self.assertEqual(
                model["historical_metric_provenance"][
                    "historical_reference_ap_attribution_to_canonical_artifact"
                ],
                "NOT_ESTABLISHED",
            )

    def test_operational_requirements_remain_unresolved_without_evidence(self) -> None:
        register = _operational_register()
        rows = register["decision_questions"]
        self.assertTrue(rows)
        self.assertTrue(all(row["status"] == "UNKNOWN_NOT_DOCUMENTED" for row in rows))
        self.assertTrue(any(row["blocks_numeric_threshold_definition"] for row in rows))
        self.assertTrue(all(row["blocks_production_approval"] for row in rows))
        self.assertEqual(register["documented_operational_requirements"], [])
        self.assertEqual(register["measured_operational_evidence"], [])
        self.assertEqual(len(register["unknown_requirement_ids"]), len(rows))

    def test_calibration_and_independent_confirmation_are_distinct(self) -> None:
        protocol = _evaluation_design()["protocol"]
        self.assertIn("calibration cohort", protocol["threshold_calibration"])
        self.assertIn("separate", protocol["independent_confirmation"])
        self.assertIn("not used", protocol["independent_confirmation"])
        self.assertIn("threshold", protocol["threshold_calibration"])

    def test_calibration_does_not_use_test_data(self) -> None:
        protocol = _evaluation_design()["protocol"]
        self.assertNotIn("test split", protocol["threshold_calibration"].lower())
        self.assertIn("independent", protocol["independent_confirmation"].lower())

    def test_undefined_policy_thresholds_remain_null(self) -> None:
        report = build_synthetic_report()
        self.assertTrue(report["threshold_readiness"]["all_numeric_thresholds_remain_undefined"])
        self.assertEqual(report["threshold_readiness"]["decision"], "NO_THRESHOLD_DEFINITION_OR_PRODUCTION_APPROVAL")

    def test_reports_cover_all_model_families_and_preserve_score_semantics(self) -> None:
        report = build_synthetic_report()
        self.assertEqual(set(report["evidence_provenance_audit"]["models"]), set(MODEL_FAMILIES))
        autoencoder = report["evidence_provenance_audit"]["models"]["autoencoder"]
        self.assertEqual(autoencoder["score_type"], "anomaly_score")
        self.assertIn("not a probability", autoencoder["validation_evidence"]["metric_semantics"])
        self.assertFalse(autoencoder["validation_evidence"]["independent_confirmation"])

    def test_report_schema_has_stable_top_level_sections(self) -> None:
        report = build_synthetic_report()
        self.assertEqual(report["schema_version"], "1.0.0")
        for key in (
            "evidence_provenance_audit", "historical_evaluation_independence",
            "operational_requirements_register", "independent_evaluation_design",
            "evidence_acquisition_plan", "threshold_readiness", "known_limitations",
        ):
            self.assertIn(key, report)

    def test_report_writer_refuses_to_overwrite_an_existing_report(self) -> None:
        report = build_synthetic_report()
        with TemporaryDirectory() as directory:
            output = write_report(report, Path(directory))
            original = output.read_bytes()
            with self.assertRaises(FileExistsError):
                write_report(report, Path(directory))
            self.assertEqual(output.read_bytes(), original)

    def test_report_serialization_is_valid_json_without_non_finite_values(self) -> None:
        report = build_synthetic_report()
        serialized = json.dumps(report, sort_keys=True, allow_nan=False)
        self.assertEqual(json.loads(serialized)["report_id"], "synthetic-report")

    def test_m5_threshold_status_is_preserved_for_every_family(self) -> None:
        report = build_synthetic_report()
        readiness = report["threshold_readiness"]["models"]
        self.assertEqual(set(readiness), set(MODEL_FAMILIES))
        self.assertTrue(all(value["threshold_calibration"] == "INSUFFICIENT_EVIDENCE" for value in readiness.values()))


if __name__ == "__main__":
    unittest.main()
