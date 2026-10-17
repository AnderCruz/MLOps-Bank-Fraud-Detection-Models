"""Synthetic tests for M5 evidence inventory and acceptance-policy behavior."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src import inference, validation_gates as gates
from src import validation_policy_analysis as analysis


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_policy_v1_compatibility_and_v2_undefined_thresholds() -> None:
    old = gates.load_policy(Path("configs/validation_policy_v1.json"))
    current = gates.load_policy(Path("configs/validation_policy_v2.json"))
    assert old.schema_version == "1.0.0"
    assert current.schema_version == "2.0.0"
    assert current.effective_status == "incomplete"
    assert all(item["value"] is None for item in current.quality_thresholds.values())
    assert set(current.threshold_details) == set(gates.MODEL_FAMILIES)
    assert all(item["source"] is None and item["rationale"] for item in current.threshold_details.values())


def test_policy_v2_rejects_unsupported_and_malformed_threshold_configuration(tmp_path: Path) -> None:
    raw = json.loads(Path("configs/validation_policy_v2.json").read_text())
    raw["effective_status"] = "active"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="effective_status"):
        gates.load_policy(path)
    raw = json.loads(Path("configs/validation_policy_v2.json").read_text())
    raw["quality_thresholds"]["random_forest"]["metric"] = "roc_auc"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="metric/operator"):
        gates.load_policy(path)
    raw = json.loads(Path("configs/validation_policy_v2.json").read_text())
    raw["quality_thresholds"]["random_forest"]["value"] = 0.7
    raw["threshold_details"]["random_forest"] = {
        "source": "approved synthetic acceptance requirement",
        "rationale": "Synthetic-only schema validation example.",
        "calibration_evidence_reference": "synthetic-policy-test",
        "calibration_timestamp": "2026-01-01T00:00:00Z",
        "calibration_method": "synthetic fixture; not an empirical project threshold",
        "undefined_reason": None,
    }
    path.write_text(json.dumps(raw))
    policy = gates.load_policy(path)
    assert policy.quality_thresholds["random_forest"]["value"] == 0.7


def test_v2_null_mandatory_threshold_is_insufficient_and_keeps_rationale(tmp_path: Path) -> None:
    artifact = tmp_path / "rf.joblib"
    artifact.write_bytes(b"synthetic model bytes")
    metadata = tmp_path / "rf_metadata.json"
    metadata.write_text(json.dumps({
        "model_name": "random_forest", "random_seed": 42,
        "features": list(inference.EXPECTED_FEATURES), "training_dataset": ["synthetic-train"],
        "validation_dataset": ["synthetic-validation"], "validation_metric": "AP",
        "reproduced_validation_metric": 0.7, "configuration": {},
        "provenance": {"run": {"run_id": "pipeline-1"}},
    }))
    candidate = gates.CandidateEvidence(
        "random_forest", artifact, metadata, "models/rf.joblib", "models/rf_metadata.json",
        None, None, "training-1", None, "pipeline-1", "FINISHED", True,
        (gates.MetricEvidence("average_precision", 0.7, "synthetic-report", "synthetic AP"),),
        artifact_load_verified=True,
    )
    report = gates.assess_candidate(
        candidate, gates.load_policy(Path("configs/validation_policy_v2.json")),
        artifact_validator=lambda _: (True, "synthetic compatibility"),
    )
    quality = next(gate for gate in report["gates"] if gate["name"] == "quality_threshold")
    assert report["decision"] == "INSUFFICIENT_EVIDENCE"
    assert quality["threshold"] is None
    assert quality["threshold_source"] is None
    assert quality["threshold_rationale"]
    assert quality["undefined_reason"] == "insufficient_supporting_acceptance_evidence"
    assert report["policy"]["effective_status"] == "incomplete"
    effectiveness = next(g for g in report["gates"] if g["name"] == "policy_effectiveness")
    assert effectiveness["status"] == "INSUFFICIENT_EVIDENCE"
    raw_policy = json.loads(Path("configs/validation_policy_v2.json").read_text())
    raw_policy["quality_thresholds"]["random_forest"]["value"] = 0.6
    raw_policy["threshold_details"]["random_forest"] = {
        "source": "synthetic approved criterion", "rationale": "Synthetic fixture only.",
        "calibration_evidence_reference": "synthetic", "calibration_timestamp": "2026-01-01T00:00:00Z",
        "calibration_method": "synthetic fixture", "undefined_reason": None,
    }
    partial_policy_path = tmp_path / "partial-policy.json"
    partial_policy_path.write_text(json.dumps(raw_policy))
    partial_policy = gates.load_policy(partial_policy_path)
    partial_report = gates.assess_candidate(
        candidate, partial_policy, artifact_validator=lambda _: (True, "synthetic compatibility")
    )
    assert partial_report["decision"] == "INSUFFICIENT_EVIDENCE"
    assert next(g for g in partial_report["gates"] if g["name"] == "policy_effectiveness")["status"] == "INSUFFICIENT_EVIDENCE"


def test_explicit_supported_threshold_is_representable_by_existing_engine(tmp_path: Path) -> None:
    artifact = tmp_path / "rf.joblib"
    artifact.write_bytes(b"synthetic model bytes")
    metadata = tmp_path / "rf_metadata.json"
    metadata.write_text(json.dumps({
        "model_name": "random_forest", "random_seed": 42,
        "features": list(inference.EXPECTED_FEATURES), "training_dataset": ["synthetic-train"],
        "validation_dataset": ["synthetic-validation"], "validation_metric": "AP",
        "reproduced_validation_metric": 0.8, "configuration": {},
        "provenance": {"run": {"run_id": "pipeline-1"}},
    }))
    candidate = gates.CandidateEvidence(
        "random_forest", artifact, metadata, "models/rf.joblib", "models/rf_metadata.json",
        None, None, "training-1", None, "pipeline-1", "FINISHED", True,
        (gates.MetricEvidence("average_precision", 0.8, "synthetic-validation-protocol", "AP"),),
        artifact_load_verified=True,
    )
    policy = gates.ValidationPolicy(
        "synthetic-policy", "test", True, True, False,
        {"random_forest": {"metric": "average_precision", "operator": "minimum", "value": 0.75}},
    )
    report = gates.assess_candidate(
        candidate, policy, artifact_validator=lambda _: (True, "synthetic compatibility")
    )
    assert report["decision"] == "PASS"
    assert next(gate for gate in report["gates"] if gate["name"] == "quality_threshold")["threshold"] == 0.75
    assert report["production_approval"] is False


def test_missing_malformed_and_nonfinite_metrics_do_not_become_zero(tmp_path: Path) -> None:
    artifact = tmp_path / "rf.joblib"
    artifact.write_bytes(b"synthetic model bytes")
    metadata = tmp_path / "rf_metadata.json"
    metadata.write_text(json.dumps({
        "model_name": "random_forest", "random_seed": 42,
        "features": list(inference.EXPECTED_FEATURES), "training_dataset": ["synthetic-train"],
        "validation_dataset": ["synthetic-validation"], "validation_metric": "AP",
        "reproduced_validation_metric": 0.8, "configuration": {},
        "provenance": {"run": {"run_id": "pipeline-1"}},
    }))
    base = gates.CandidateEvidence(
        "random_forest", artifact, metadata, "models/rf.joblib", "models/rf_metadata.json",
        None, None, "training-1", None, "pipeline-1", "FINISHED", True, (),
        artifact_load_verified=True,
    )
    policy = gates.load_policy(Path("configs/validation_policy_v2.json"))
    missing = gates.assess_candidate(base, policy, artifact_validator=lambda _: (True, "ok"))
    assert missing["decision"] == "INSUFFICIENT_EVIDENCE"
    assert not missing["metrics"]
    for value in (float("nan"), float("inf"), "bad", None):
        candidate = gates.CandidateEvidence(**{
            **base.__dict__,
            "metrics": (gates.MetricEvidence("average_precision", value, "synthetic", "AP"),),
        })
        report = gates.assess_candidate(candidate, policy, artifact_validator=lambda _: (True, "ok"))
        metric_gate = next(g for g in report["gates"] if g["name"] == "validation_metric")
        assert metric_gate["status"] == "FAIL"
        assert metric_gate["value"] is None


def test_autoencoder_requires_reconstruction_mse_not_ap(tmp_path: Path) -> None:
    artifact = tmp_path / "autoencoder_state_dict.pt"
    artifact.write_bytes(b"synthetic state bytes")
    metadata = tmp_path / "autoencoder_metadata.json"
    metadata.write_text(json.dumps({
        "model_name": "autoencoder", "random_seed": 42,
        "features": list(inference.EXPECTED_FEATURES), "training_dataset": ["synthetic-train"],
        "validation_dataset": ["synthetic-validation"], "validation_metric": "validation reconstruction MSE",
        "reproduced_validation_metric": 0.3, "configuration": {},
        "provenance": {"run": {"run_id": "pipeline-ae"}},
    }))
    candidate = gates.CandidateEvidence(
        "autoencoder", artifact, metadata, "models/autoencoder_state_dict.pt",
        "models/autoencoder_metadata.json", None, None, "training-ae", None,
        "pipeline-ae", "FINISHED", True,
        (gates.MetricEvidence("average_precision", 0.3, "synthetic", "anomaly AP"),),
        artifact_load_verified=True,
    )
    report = gates.assess_candidate(
        candidate, gates.load_policy(Path("configs/validation_policy_v2.json")),
        artifact_validator=lambda _: (True, "synthetic compatibility"),
    )
    metric_gate = next(g for g in report["gates"] if g["name"] == "validation_metric")
    assert metric_gate["status"] == "INSUFFICIENT_EVIDENCE"
    assert metric_gate["metric"] == "validation_reconstruction_mse"


class _FakeClient:
    tracking_uri = "sqlite:///synthetic.db"

    def __init__(
        self,
        run_tags: dict[str, dict[str, str]],
        artifact_paths: dict[str, list[str]] | None = None,
        run_metrics: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.run_tags = run_tags
        self.artifact_paths = artifact_paths or {}
        self.run_metrics = run_metrics or {}
        self.read_calls: list[str] = []
        self.write_calls: list[str] = []

    def get_run(self, run_id: str):
        self.read_calls.append(run_id)
        return SimpleNamespace(
            info=SimpleNamespace(status="FINISHED"),
            data=SimpleNamespace(tags=self.run_tags[run_id], metrics=self.run_metrics.get(run_id, {})),
        )

    def list_artifacts(self, run_id: str, path: str = ""):
        self.read_calls.append(f"list:{run_id}:{path}")
        paths = self.artifact_paths.get(run_id, ["model.joblib"])
        return [SimpleNamespace(path=item, is_dir=False) for item in paths]

    def search_registered_models(self):
        self.read_calls.append("registry:list")
        return []


def test_evidence_inventory_uses_synthetic_fixtures_without_misclassifying_them(tmp_path: Path) -> None:
    root = tmp_path
    evaluation_id = "synthetic-evaluation"
    reports = root / "reports"
    gates_dir = reports / "validation_gates"
    gates_dir.mkdir(parents=True)
    model_specs = {}
    run_tags = {}
    evaluation_models = {family: {} for family in gates.MODEL_FAMILIES}
    common = {}
    native = {}
    for index, family in enumerate(gates.MODEL_FAMILIES):
        model_dir = root / "models" / family
        model_dir.mkdir(parents=True)
        artifact_suffix = ".joblib" if family in {"random_forest", "xgboost", "logistic_regression", "lightgbm"} else "_state_dict.pt"
        artifact = model_dir / f"{family}{artifact_suffix}"
        artifact.write_bytes(f"synthetic artifact {family}".encode())
        metadata = model_dir / f"{family}_metadata.json"
        pipeline_id = f"pipeline-{family}"
        source_id = f"source-{family}"
        score_type = "anomaly_score" if family == "autoencoder" else "fraud_probability"
        metadata.write_text(json.dumps({
            "model_name": family, "random_seed": 42,
            "features": list(inference.EXPECTED_FEATURES),
            "training_dataset": ["synthetic-train"], "validation_dataset": ["synthetic-validation"],
            "validation_metric": "validation reconstruction MSE" if family == "autoencoder" else "Average Precision (AP)",
            "reproduced_validation_metric": 0.2 if family == "autoencoder" else 0.7,
            "configuration": {"best_validation_reconstruction_mse": 0.2} if family == "autoencoder" else {},
            "provenance": {"run": {"run_id": pipeline_id}, "git": {"commit": None, "branch": None}},
        }))
        metadata_hash = _hash(metadata)
        artifact_hash = _hash(artifact)
        is_import = family == "xgboost"
        model_specs[family] = inference.ModelSpec(
            str(artifact.relative_to(root)), str(metadata.relative_to(root)), artifact_hash,
            metadata_hash, "scaled", "SyntheticModel", score_type, pipeline_id,
            training_run_id=None if is_import else source_id,
            artifact_import_run_id=source_id if is_import else None,
        )
        run_tags[source_id] = {
            "pipeline_run_id": pipeline_id if not is_import else None,
            "record_type": "artifact_import" if is_import else "training_run",
            "project": "Bank-Fraud-Detection",
            **({"training_run_recovered": "false"} if is_import else {}),
        }
        expected = "validation_reconstruction_mse" if family == "autoencoder" else "average_precision"
        metric_value = 0.2 if family == "autoencoder" else 0.7
        gate = {
            "model_family": family, "decision": "INSUFFICIENT_EVIDENCE",
            "validation_evaluation": {"evaluation_id": evaluation_id},
            "metrics": [{"name": expected, "value": metric_value, "source": "synthetic-gate-source", "interpretation": "synthetic evidence"}],
            "gates": [
                {"name": "artifact_compatibility", "status": "PASS"},
                {"name": "provenance_lineage", "status": "PASS"},
            ],
        }
        (gates_dir / f"{family}.json").write_text(json.dumps(gate))
        metric_record = {"metrics": {"average_precision": 0.2 if family == "autoencoder" else 0.7,
                                      "roc_auc": 0.6},
                         "row_count": 100, "target_class_counts": {"0": 90, "1": 10}}
        common[family] = metric_record
        native[family] = metric_record

    evaluation_path = reports / "validation_evaluation.json"
    evaluation_path.write_text(json.dumps({
        "record_type": "validation_evaluation", "evaluation_id": evaluation_id,
        "created_at_utc": "synthetic", "models": evaluation_models,
        "common_cohort_results": {"models": common}, "native_cohort_results": {"models": native},
        "evaluation_split": {"identifier": "synthetic-validation", "features_path": "validation-features.parquet", "labels_path": "validation-labels.parquet"},
        "holdout_disclosure": "Synthetic fixture only.", "metric_definitions": {}, "metric_implementation_versions": {},
    }))
    uncertainty_path = reports / "uncertainty.json"
    uncertainty_path.write_text(json.dumps({"record_type": "synthetic_uncertainty", "analysis_id": "u1", "results": [], "limitations": ["synthetic"]}))
    temporal_path = reports / "temporal.json"
    temporal_path.write_text(json.dumps({"record_type": "synthetic_temporal", "analysis_id": "t1", "limitations": ["synthetic"]}))
    score_manifest = reports / "validation_analysis" / evaluation_id / "run" / "analysis_manifest.json"
    score_manifest.parent.mkdir(parents=True)
    score_manifest.write_text("{}")
    policy_path = root / "policy.json"
    policy_path.write_text(Path("configs/validation_policy_v2.json").read_text())
    imported_run = "source-xgboost"
    artifact_paths = {}
    run_metrics = {}
    for family, spec in model_specs.items():
        source_id = spec.training_run_id or spec.artifact_import_run_id
        if family == "xgboost":
            artifact_paths[source_id] = [
                "imported/xgboost/artifact_import_manifest.json",
                "imported/xgboost/xgboost.joblib",
                "imported/xgboost/xgboost_metadata.json",
            ]
        else:
            artifact_paths[source_id] = [
                f"models/{family}/{Path(spec.artifact_path).name}",
                f"models/{family}/{Path(spec.metadata_path).name}",
            ]
        run_metrics[source_id] = {} if family == "xgboost" else {f"{family}_validation_ap": 0.7}
        if family == "autoencoder":
            run_metrics[source_id]["autoencoder_validation_reconstruction_mse"] = 0.2
    client = _FakeClient(run_tags, artifact_paths, run_metrics)
    output_root = reports / "analysis"

    with patch.object(analysis, "ROOT", root), patch.object(inference, "CANONICAL_MODELS", model_specs):
        inventory, policy_report, output_directory = analysis.build_reports(
            evaluation_path=evaluation_path, policy_path=policy_path,
            gate_directory=gates_dir, uncertainty_path=uncertainty_path,
            temporal_path=temporal_path, output_root=output_root, client=client,
            registry_state={"status": "available", "registered_model_count": 0},
            created_at_utc="synthetic-time", inventory_id="synthetic-inventory",
        )
    assert len(inventory["models"]) == 8
    assert all(item["evidence_classification"] == "synthetic_or_unverified_fixture" for item in inventory["models"].values())
    assert inventory["models"]["xgboost"]["lineage"]["record_type"] == "artifact_import"
    assert inventory["models"]["xgboost"]["lineage"]["training_run_id"] is None
    assert all(item["lineage"]["source_record_identity_verified"] for item in inventory["models"].values())
    assert inventory["models"]["random_forest"]["lineage"]["source_record"]["recorded_metrics"]["random_forest_validation_ap"] == 0.7
    assert inventory["models"]["xgboost"]["lineage"]["source_record"]["recorded_metrics"] == {}
    assert all(item["decision"] == "INSUFFICIENT_EVIDENCE" for item in policy_report["candidates"].values()), {
        family: item["decision_reasons"] for family, item in policy_report["candidates"].items()
    }
    assert all(item["value"] is None for item in policy_report["thresholds"].values())
    assert inventory["non_empirical_evidence"]["synthetic_test_fixtures"][0]["not_empirical_model_evidence"] is True
    assert client.write_calls == []
    assert (output_directory / "evidence_inventory.json").is_file()
    assert (output_directory / "policy_analysis.json").is_file()
    second_root = reports / "analysis-second"
    with patch.object(analysis, "ROOT", root), patch.object(inference, "CANONICAL_MODELS", model_specs):
        second_inventory, second_analysis, second_directory = analysis.build_reports(
            evaluation_path=evaluation_path, policy_path=policy_path,
            gate_directory=gates_dir, uncertainty_path=uncertainty_path,
            temporal_path=temporal_path, output_root=second_root, client=client,
            registry_state={"status": "available", "registered_model_count": 0},
            created_at_utc="synthetic-time", inventory_id="synthetic-inventory",
        )
    assert (output_directory / "evidence_inventory.json").read_bytes() == (second_directory / "evidence_inventory.json").read_bytes()
    assert (output_directory / "policy_analysis.json").read_bytes() == (second_directory / "policy_analysis.json").read_bytes()
    with pytest.raises(gates.ValidationInfrastructureError, match="Refusing to overwrite"):
        with patch.object(analysis, "ROOT", root), patch.object(inference, "CANONICAL_MODELS", model_specs):
            analysis.build_reports(
                evaluation_path=evaluation_path, policy_path=policy_path,
                gate_directory=gates_dir, uncertainty_path=uncertainty_path,
                temporal_path=temporal_path, output_root=output_root, client=client,
                registry_state={"status": "available", "registered_model_count": 0},
                created_at_utc="synthetic-time", inventory_id="synthetic-inventory",
            )


def test_failed_integrity_takes_precedence_over_missing_threshold(tmp_path: Path) -> None:
    policy = gates.load_policy(Path("configs/validation_policy_v2.json"))
    candidate = gates.CandidateEvidence(
        "random_forest", tmp_path / "missing.joblib", tmp_path / "missing.json",
        "models/missing.joblib", "models/missing_metadata.json", None, None,
        "training-1", None, "pipeline-1", "FINISHED", True,
        (gates.MetricEvidence("average_precision", 0.7, "synthetic", "AP"),),
        artifact_load_verified=True,
    )
    report = gates.assess_candidate(candidate, policy, artifact_validator=lambda _: (True, "ok"))
    assert report["decision"] == "FAIL"
    assert report["failure_reasons"]
    assert any(gate["status"] == "INSUFFICIENT_EVIDENCE" for gate in report["gates"])
