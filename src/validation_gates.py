"""Deterministic evidence checks for model validation candidates.

Validation Gates report evidence and policy decisions. They do not approve,
promote, or deploy a model. The real-artifact adapter reuses ``src.inference``;
the decision engine itself accepts explicit evidence and is independently
testable without a tracking store or trained model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "1.0.0"
POLICY_SCHEMA_V2 = "2.0.0"
DECISIONS = {"PASS", "FAIL", "INSUFFICIENT_EVIDENCE"}
MODEL_FAMILIES = (
    "random_forest", "xgboost", "logistic_regression", "lightgbm",
    "mlp", "autoencoder", "lstm", "gru",
)
EXPECTED_FORMATS = {
    "random_forest": ".joblib", "xgboost": ".joblib",
    "logistic_regression": ".joblib", "lightgbm": ".joblib",
    "mlp": "_state_dict.pt", "autoencoder": "_state_dict.pt",
    "lstm": "_state_dict.pt", "gru": "_state_dict.pt",
}


class ValidationInfrastructureError(RuntimeError):
    """An external evidence service or report write failed."""


@dataclass(frozen=True)
class MetricEvidence:
    name: str
    value: Any
    source: str | None
    interpretation: str


@dataclass(frozen=True)
class CandidateEvidence:
    model_family: str
    artifact_path: Path
    metadata_path: Path
    artifact_uri: str
    metadata_uri: str
    artifact_sha256: str | None
    metadata_sha256: str | None
    training_run_id: str | None
    artifact_import_run_id: str | None
    pipeline_run_id: str | None
    source_run_status: str | None
    lineage_verified: bool | None
    metrics: tuple[MetricEvidence, ...] = ()
    registered_model_name: str | None = None
    registered_model_version: str | None = None
    registry_lineage_verified: bool | None = None
    git_commit: str | None = None
    git_branch: str | None = None
    metadata_git_commit: str | None = None
    metadata_git_branch: str | None = None
    artifact_load_verified: bool | None = None
    artifact_load_detail: str | None = None
    validation_evaluation_id: str | None = None
    validation_evaluation_sha256: str | None = None


@dataclass(frozen=True)
class ValidationPolicy:
    policy_id: str
    version: str
    require_quality_threshold: bool
    require_source_record: bool
    require_registry_registration: bool
    quality_thresholds: dict[str, dict[str, Any]] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    effective_status: str = "active"
    threshold_details: dict[str, dict[str, Any]] = field(default_factory=dict)


def load_policy(path: Path) -> ValidationPolicy:
    """Load a small versioned JSON policy and reject unsupported settings."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read validation policy {path}: {error}") from error
    required_v1 = {
        "schema_version", "policy_id", "version", "require_quality_threshold",
        "require_source_record", "require_registry_registration", "quality_thresholds",
    }
    if not isinstance(raw, dict):
        raise ValueError("Unsupported validation policy schema or fields")
    if raw.get("schema_version") == SCHEMA_VERSION:
        if set(raw) != required_v1:
            raise ValueError("Unsupported validation policy schema or fields")
        effective_status = "active"
        threshold_details: dict[str, dict[str, Any]] = {}
    elif raw.get("schema_version") == POLICY_SCHEMA_V2:
        required_v2 = required_v1 | {
            "effective_status", "applicable_model_families", "required_metrics",
            "threshold_details", "required_provenance", "mandatory_gates",
            "optional_gates", "undefined_threshold_decision", "decision_precedence",
            "missing_evidence_handling", "calibration_and_evaluation_separation",
        }
        if set(raw) != required_v2:
            raise ValueError("Unsupported validation policy v2 schema or fields")
        effective_status = raw["effective_status"]
        if effective_status not in {"incomplete", "active"}:
            raise ValueError("Policy v2 effective_status must be 'incomplete' or 'active'")
        if raw["applicable_model_families"] != list(MODEL_FAMILIES):
            raise ValueError("Policy v2 must enumerate all supported model families in canonical order")
        if raw["require_quality_threshold"] is not True:
            raise ValueError("Policy v2 requires mandatory quality thresholds")
        if raw["required_provenance"] != {
            "source_record": True, "artifact_metadata": True, "validation_evaluation": True,
        }:
            raise ValueError("Unsupported required provenance policy")
        if raw["mandatory_gates"] != [
            "artifact_integrity", "artifact_compatibility", "provenance_lineage",
            "validation_metric", "quality_threshold", "policy_effectiveness",
        ] or raw["optional_gates"] != ["git_provenance", "registry_lineage"]:
            raise ValueError("Unsupported mandatory or optional gate configuration")
        if raw["missing_evidence_handling"] != {
            "required_metric": "INSUFFICIENT_EVIDENCE",
            "required_lineage": "INSUFFICIENT_EVIDENCE",
            "undefined_threshold": "INSUFFICIENT_EVIDENCE",
            "malformed_metric": "FAIL",
        }:
            raise ValueError("Unsupported missing-evidence handling")
        if raw["calibration_and_evaluation_separation"] != {
            "calibration": "A threshold requires a cited acceptance objective and evidence source; reuse of validation data must be disclosed.",
            "candidate_evaluation": "Evaluate candidates against a fixed, versioned threshold without recalibrating it on the candidate evaluation observations.",
            "independent_confirmation": "Use a distinct, pre-specified evaluation cohort for independent confirmation; this project validation evidence is selection-conditioned.",
            "test_data": "Test-set evidence is excluded from calibration and acceptance-policy definition.",
        }:
            raise ValueError("Unsupported calibration/evaluation separation policy")
        if raw["undefined_threshold_decision"] != "INSUFFICIENT_EVIDENCE":
            raise ValueError("Undefined mandatory thresholds must produce INSUFFICIENT_EVIDENCE")
        if raw["decision_precedence"] != ["FAIL", "INSUFFICIENT_EVIDENCE", "PASS"]:
            raise ValueError("Unsupported decision precedence")
        for key in (
            "required_metrics", "required_provenance", "mandatory_gates", "optional_gates",
            "missing_evidence_handling", "calibration_and_evaluation_separation",
        ):
            if not isinstance(raw[key], (dict, list)):
                raise ValueError(f"Policy v2 field {key} has an invalid type")
        if raw["required_metrics"] != {
            family: ("validation_reconstruction_mse" if family == "autoencoder" else "average_precision")
            for family in MODEL_FAMILIES
        }:
            raise ValueError("Policy v2 required metrics do not match model metric semantics")
        threshold_details = raw["threshold_details"]
        if not isinstance(threshold_details, dict) or set(threshold_details) != set(MODEL_FAMILIES):
            raise ValueError("Policy v2 threshold_details must cover every model family")
        for family, detail in threshold_details.items():
            if not isinstance(detail, dict) or set(detail) != {
                "source", "rationale", "calibration_evidence_reference", "calibration_timestamp",
                "calibration_method", "undefined_reason",
            }:
                raise ValueError(f"Invalid threshold rationale fields for {family}")
            if not isinstance(detail["rationale"], str) or not detail["rationale"].strip():
                raise ValueError(f"Threshold rationale for {family} must be explicit")
    else:
        raise ValueError("Unsupported validation policy schema or fields")
    if not isinstance(raw["policy_id"], str) or not raw["policy_id"].strip():
        raise ValueError("policy_id must be a non-empty string")
    if not isinstance(raw["version"], str) or not raw["version"].strip():
        raise ValueError("policy version must be a non-empty string")
    for key in ("require_quality_threshold", "require_source_record", "require_registry_registration"):
        if not isinstance(raw[key], bool):
            raise ValueError(f"Policy field {key} must be boolean")
    thresholds = raw["quality_thresholds"]
    if not isinstance(thresholds, dict):
        raise ValueError("quality_thresholds must be an object")
    if raw["schema_version"] == POLICY_SCHEMA_V2 and set(thresholds) != set(MODEL_FAMILIES):
        raise ValueError("Policy v2 quality thresholds must cover every model family")
    for family, threshold in thresholds.items():
        if family not in MODEL_FAMILIES or not isinstance(threshold, dict):
            raise ValueError(f"Unsupported quality threshold entry: {family}")
        if set(threshold) != {"metric", "operator", "value"}:
            raise ValueError(f"Invalid threshold fields for {family}")
        expected_metric = "validation_reconstruction_mse" if family == "autoencoder" else "average_precision"
        expected_operator = "maximum" if family == "autoencoder" else "minimum"
        if threshold["metric"] != expected_metric or threshold["operator"] != expected_operator:
            raise ValueError(f"Unsupported metric/operator for {family}")
        value = threshold["value"]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError(f"Threshold for {family} must be finite numeric or null")
        if family != "autoencoder" and value is not None and not 0 <= value <= 1:
            raise ValueError(f"AP threshold for {family} must lie in [0, 1]")
        if family == "autoencoder" and value is not None and value < 0:
            raise ValueError("Autoencoder MSE threshold must be non-negative")
        if raw["schema_version"] == POLICY_SCHEMA_V2:
            detail = threshold_details[family]
            if value is None:
                if any(detail[key] is not None for key in (
                    "source", "calibration_evidence_reference", "calibration_timestamp", "calibration_method",
                )) or detail["undefined_reason"] != "insufficient_supporting_acceptance_evidence":
                    raise ValueError(f"Undefined threshold {family} requires an explicit unsupported-evidence rationale")
            elif (
                not detail["source"] or not detail["calibration_evidence_reference"]
                or not detail["calibration_timestamp"] or not detail["calibration_method"]
                or detail["undefined_reason"] is not None
            ):
                raise ValueError(f"Numeric threshold {family} requires source, calibration evidence, time, and method")
    if raw["schema_version"] == POLICY_SCHEMA_V2:
        has_undefined = any(entry["value"] is None for entry in thresholds.values())
        expected_status = "incomplete" if has_undefined else "active"
        if effective_status != expected_status:
            raise ValueError(f"Policy v2 effective_status must be {expected_status!r} for its configured thresholds")
    return ValidationPolicy(
        policy_id=raw["policy_id"], version=raw["version"],
        require_quality_threshold=raw["require_quality_threshold"],
        require_source_record=raw["require_source_record"],
        require_registry_registration=raw["require_registry_registration"],
        quality_thresholds=thresholds,
        schema_version=raw["schema_version"],
        effective_status=effective_status,
        threshold_details=threshold_details,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gate(name: str, status: str, reason: str, **evidence: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "reason": reason, **evidence}


def assess_candidate(
    candidate: CandidateEvidence,
    policy: ValidationPolicy,
    *,
    artifact_validator: Callable[[CandidateEvidence], tuple[bool, str]] | None = None,
) -> dict[str, Any]:
    """Evaluate explicit artifact, lineage, metric, and policy evidence."""
    if candidate.model_family not in MODEL_FAMILIES:
        raise ValueError(f"Unknown model family: {candidate.model_family}")
    if not policy.policy_id or not policy.version:
        raise ValueError("Validation policy requires a non-empty identifier and version")
    if any(not isinstance(value, bool) for value in (
        policy.require_quality_threshold, policy.require_source_record,
        policy.require_registry_registration,
    )):
        raise ValueError("Validation policy requirement flags must be boolean")
    if not isinstance(policy.quality_thresholds, dict):
        raise ValueError("Validation policy quality_thresholds must be an object")
    for family, entry in policy.quality_thresholds.items():
        if family not in MODEL_FAMILIES:
            raise ValueError(f"Unsupported policy model family: {family}")
        if not isinstance(entry, dict) or set(entry) != {"metric", "operator", "value"}:
            raise ValueError(f"Invalid policy threshold fields for {family}")
        expected_metric = "validation_reconstruction_mse" if family == "autoencoder" else "average_precision"
        expected_operator = "maximum" if family == "autoencoder" else "minimum"
        if entry.get("metric") != expected_metric or entry.get("operator") != expected_operator:
            raise ValueError(f"Unsupported policy threshold for {family}")
        value = entry.get("value")
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or (family != "autoencoder" and not 0 <= value <= 1)
            or (family == "autoencoder" and value < 0)
        ):
            raise ValueError(f"Invalid policy threshold value for {family}")

    gates: list[dict[str, Any]] = []
    missing: list[str] = []
    if policy.schema_version == POLICY_SCHEMA_V2 and policy.effective_status != "active":
        reason = "Versioned acceptance policy is incomplete and cannot produce a passing candidate decision"
        missing.append(reason)
        gates.append(_gate("policy_effectiveness", "INSUFFICIENT_EVIDENCE", reason, effective_status=policy.effective_status))
    metadata: dict[str, Any] | None = None
    artifact_ok = candidate.artifact_path.is_file()
    metadata_ok = candidate.metadata_path.is_file()
    integrity_reasons: list[str] = []
    if not artifact_ok:
        integrity_reasons.append("Model artifact is missing")
    if not metadata_ok:
        integrity_reasons.append("Model metadata JSON is missing")
    if integrity_reasons:
        gates.append(_gate("artifact_integrity", "FAIL", "; ".join(integrity_reasons)))
    else:
        try:
            metadata = json.loads(candidate.metadata_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("Metadata root must be an object")
        except (OSError, json.JSONDecodeError, ValueError) as error:
            gates.append(_gate("artifact_integrity", "FAIL", f"Metadata is malformed: {error}"))
        else:
            from src.inference import EXPECTED_FEATURES

            required_fields = (
                "model_name", "random_seed", "features", "training_dataset",
                "validation_dataset", "validation_metric", "reproduced_validation_metric",
                "configuration", "provenance",
            )
            absent = [key for key in required_fields if key not in metadata]
            invalid: list[str] = []
            if absent:
                invalid.append(f"Missing required metadata fields: {', '.join(absent)}")
            if metadata.get("model_name") != candidate.model_family:
                invalid.append("Metadata model family does not match candidate")
            if isinstance(metadata.get("random_seed"), bool) or not isinstance(metadata.get("random_seed"), int):
                invalid.append("Metadata random_seed must be an integer")
            if not isinstance(metadata.get("configuration"), dict):
                invalid.append("Metadata configuration must be an object")
            if not isinstance(metadata.get("provenance"), dict):
                invalid.append("Metadata provenance must be an object")
            for dataset_field in ("training_dataset", "validation_dataset"):
                if not isinstance(metadata.get(dataset_field), list) or not metadata[dataset_field]:
                    invalid.append(f"Metadata {dataset_field} must be a non-empty list")
            metadata_metric = metadata.get("validation_metric")
            metadata_score = metadata.get("reproduced_validation_metric")
            if not isinstance(metadata_metric, str) or not metadata_metric.strip():
                invalid.append("Metadata validation_metric must be a non-empty string")
            try:
                if isinstance(metadata_score, bool):
                    raise ValueError
                numeric_metadata_score = float(metadata_score)
                if not math.isfinite(numeric_metadata_score):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                invalid.append("Metadata reproduced_validation_metric must be finite numeric")
            features_value = metadata.get("features")
            if not isinstance(features_value, (list, tuple)) or tuple(features_value) != EXPECTED_FEATURES:
                invalid.append("Metadata feature order does not match canonical feature contract")
            if not candidate.artifact_path.name.endswith(EXPECTED_FORMATS[candidate.model_family]):
                invalid.append("Model artifact format does not match model family")
            if (
                not candidate.artifact_uri
                or Path(candidate.artifact_uri.rstrip("/")).name != candidate.artifact_path.name
                or not candidate.metadata_uri
                or Path(candidate.metadata_uri.rstrip("/")).name != candidate.metadata_path.name
            ):
                invalid.append("Artifact URI basenames do not match the local artifact and metadata files")
            if candidate.artifact_sha256 is not None and _sha256(candidate.artifact_path) != candidate.artifact_sha256:
                invalid.append("Model artifact SHA-256 mismatch")
            if candidate.metadata_sha256 is not None and _sha256(candidate.metadata_path) != candidate.metadata_sha256:
                invalid.append("Metadata SHA-256 mismatch")
            if candidate.pipeline_run_id is not None:
                provenance = metadata.get("provenance")
                run_provenance = provenance.get("run") if isinstance(provenance, dict) else None
                metadata_run = run_provenance.get("run_id") if isinstance(run_provenance, dict) else None
                if metadata_run != candidate.pipeline_run_id:
                    invalid.append("Metadata pipeline run identifier does not match candidate")
            if invalid:
                gates.append(_gate("artifact_integrity", "FAIL", "; ".join(invalid)))
            else:
                gates.append(_gate("artifact_integrity", "PASS", "Artifact and required metadata are present and consistent"))

    if artifact_validator is None:
        if candidate.artifact_load_verified is True:
            gates.append(_gate("artifact_compatibility", "PASS", candidate.artifact_load_detail or "Existing loader verified artifact compatibility"))
        else:
            missing.append("Artifact compatibility with the model-loading implementation was not verified")
            gates.append(_gate("artifact_compatibility", "INSUFFICIENT_EVIDENCE", missing[-1]))
    else:
        try:
            compatible, detail = artifact_validator(candidate)
        except Exception as error:
            gates.append(_gate("artifact_compatibility", "FAIL", f"Artifact validation failed: {error}"))
        else:
            gates.append(_gate("artifact_compatibility", "PASS" if compatible else "FAIL", detail))

    source_id = candidate.training_run_id or candidate.artifact_import_run_id
    if candidate.training_run_id and candidate.artifact_import_run_id:
        gates.append(_gate("provenance_lineage", "FAIL", "Candidate cannot be both a training run and an artifact import"))
    elif not source_id:
        reason = "Required source MLflow record identifier is missing" if policy.require_source_record else "No source MLflow record was supplied"
        if policy.require_source_record:
            missing.append(reason)
            status = "INSUFFICIENT_EVIDENCE"
        else:
            status = "NOT_APPLICABLE"
        gates.append(_gate("provenance_lineage", status, reason))
    elif candidate.source_run_status is None or candidate.lineage_verified is None or not candidate.pipeline_run_id:
        missing.append("Source MLflow record status or lineage verification is unavailable")
        gates.append(_gate("provenance_lineage", "INSUFFICIENT_EVIDENCE", missing[-1], source_record_id=source_id, record_type="artifact_import" if candidate.artifact_import_run_id else "training_run"))
    elif candidate.source_run_status != "FINISHED" or not candidate.lineage_verified:
        gates.append(_gate("provenance_lineage", "FAIL", "Source record is not FINISHED or its lineage does not match", source_record_id=source_id, record_type="artifact_import" if candidate.artifact_import_run_id else "training_run"))
    else:
        gates.append(_gate("provenance_lineage", "PASS", "Source record and pipeline lineage are verified", source_record_id=source_id, record_type="artifact_import" if candidate.artifact_import_run_id else "training_run"))

    git_conflict = any(
        source and metadata and source != metadata
        for source, metadata in (
            (candidate.git_commit, candidate.metadata_git_commit),
            (candidate.git_branch, candidate.metadata_git_branch),
        )
    )
    if git_conflict:
        gates.append(_gate("git_provenance", "FAIL", "MLflow and metadata Git provenance conflict"))
    else:
        git_status = "PASS" if candidate.git_commit and candidate.git_branch else "NOT_APPLICABLE"
        gates.append(_gate("git_provenance", git_status, "Git commit and branch are available" if git_status == "PASS" else "Optional Git provenance is unavailable"))

    if candidate.registered_model_name is None and candidate.registered_model_version is None:
        if policy.require_registry_registration:
            missing.append("Policy requires a Registered Model version, but none was supplied")
            gates.append(_gate("registry_lineage", "INSUFFICIENT_EVIDENCE", missing[-1]))
        else:
            gates.append(_gate("registry_lineage", "NOT_APPLICABLE", "Candidate validation does not require Registry registration"))
    elif not candidate.registered_model_name or not candidate.registered_model_version:
        gates.append(_gate("registry_lineage", "FAIL", "Registered Model name and version must be supplied together"))
    elif candidate.registry_lineage_verified is None:
        missing.append("Registered Model source-run linkage has not been verified")
        gates.append(_gate("registry_lineage", "INSUFFICIENT_EVIDENCE", missing[-1]))
    else:
        gates.append(_gate("registry_lineage", "PASS" if candidate.registry_lineage_verified else "FAIL", "Registry version source lineage verified" if candidate.registry_lineage_verified else "Registry version does not match candidate source lineage"))

    prohibited_metrics = [
        item for item in candidate.metrics
        if "test" in item.name.lower() or (item.source and "test" in item.source.lower())
    ]
    if prohibited_metrics:
        gates.append(_gate("data_evaluation_integrity", "FAIL", "Test-split metric evidence is not permitted in Validation Gates reports"))

    expected_metric = "validation_reconstruction_mse" if candidate.model_family == "autoencoder" else "average_precision"
    valid_metrics: list[dict[str, Any]] = []
    metric_evidence = next((item for item in candidate.metrics if item.name == expected_metric), None)
    if metric_evidence is None:
        missing.append(f"Required validation metric {expected_metric} is unavailable")
        gates.append(_gate("validation_metric", "INSUFFICIENT_EVIDENCE", missing[-1], metric=expected_metric))
    else:
        try:
            metric_value = float(metric_evidence.value)
            metric_valid = math.isfinite(metric_value) and (metric_value >= 0 if candidate.model_family == "autoencoder" else 0 <= metric_value <= 1)
        except (TypeError, ValueError, OverflowError):
            metric_valid = False
            metric_value = None
        if not metric_valid:
            gates.append(_gate("validation_metric", "FAIL", "Validation metric is malformed, non-finite, or outside its valid range", metric=expected_metric, value=None))
        else:
            valid_metrics.append({"name": expected_metric, "value": metric_value, "source": metric_evidence.source, "interpretation": metric_evidence.interpretation})
            gates.append(_gate("validation_metric", "PASS", "Required model-appropriate validation metric is present and finite", metric=expected_metric, value=metric_value, source=metric_evidence.source, interpretation=metric_evidence.interpretation))
            threshold_entry = policy.quality_thresholds.get(candidate.model_family)
            threshold = threshold_entry.get("value") if threshold_entry else None
            operator = threshold_entry.get("operator") if threshold_entry else ("maximum" if candidate.model_family == "autoencoder" else "minimum")
            threshold_metric = threshold_entry.get("metric") if threshold_entry else expected_metric
            if not policy.require_quality_threshold:
                gates.append(_gate("quality_threshold", "NOT_APPLICABLE", "Policy does not require a numerical quality threshold", metric=expected_metric, value=metric_value))
            elif threshold_metric != expected_metric:
                gates.append(_gate("quality_threshold", "FAIL", "Policy threshold metric does not match the model's required metric"))
            elif threshold is None:
                missing.append(f"Mandatory quality threshold for {candidate.model_family} is undefined in policy {policy.policy_id}")
                details = policy.threshold_details.get(candidate.model_family, {})
                gates.append(_gate(
                    "quality_threshold", "INSUFFICIENT_EVIDENCE", missing[-1],
                    metric=expected_metric, value=metric_value, threshold=None,
                    threshold_source=details.get("source"),
                    threshold_rationale=details.get("rationale"),
                    calibration_evidence_reference=details.get("calibration_evidence_reference"),
                    calibration_timestamp=details.get("calibration_timestamp"),
                    calibration_method=details.get("calibration_method"),
                    undefined_reason=details.get("undefined_reason"),
                ))
            else:
                passed = metric_value >= threshold if operator == "minimum" else metric_value <= threshold
                gates.append(_gate("quality_threshold", "PASS" if passed else "FAIL", "Configured threshold satisfied" if passed else "Configured threshold not satisfied", metric=expected_metric, value=metric_value, operator=operator, threshold=threshold))

    for item in candidate.metrics:
        if item.name != expected_metric and item not in prohibited_metrics:
            try:
                extra_value = float(item.value)
            except (TypeError, ValueError, OverflowError):
                extra_value = None
            valid_metrics.append({"name": item.name, "value": extra_value if extra_value is not None and math.isfinite(extra_value) else None, "source": item.source, "interpretation": item.interpretation})

    statuses = {item["status"] for item in gates if item["status"] != "NOT_APPLICABLE"}
    decision = "FAIL" if "FAIL" in statuses else "INSUFFICIENT_EVIDENCE" if "INSUFFICIENT_EVIDENCE" in statuses else "PASS"
    reasons = [item["reason"] for item in gates if item["status"] in {"FAIL", "INSUFFICIENT_EVIDENCE"}]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "model_validation_gates",
        "report_id": uuid.uuid4().hex,
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_family": candidate.model_family,
        "score_type": "anomaly_score" if candidate.model_family == "autoencoder" else "fraud_probability",
        "decision": decision,
        "production_approval": False,
        "policy": {
            "policy_id": policy.policy_id, "version": policy.version,
            "schema_version": policy.schema_version,
            "effective_status": policy.effective_status,
        },
        "lineage": {
            "training_run_id": candidate.training_run_id,
            "artifact_import_run_id": candidate.artifact_import_run_id,
            "pipeline_run_id": candidate.pipeline_run_id,
            "registered_model_name": candidate.registered_model_name,
            "registered_model_version": candidate.registered_model_version,
        },
        "artifacts": {
            "model_uri": candidate.artifact_uri,
            "metadata_uri": candidate.metadata_uri,
            "artifact_sha256": candidate.artifact_sha256,
            "metadata_sha256": candidate.metadata_sha256,
            "validation_evaluation_id": candidate.validation_evaluation_id,
            "validation_evaluation_sha256": candidate.validation_evaluation_sha256,
        },
        "metrics": valid_metrics,
        "gates": gates,
        "failure_reasons": [item["reason"] for item in gates if item["status"] == "FAIL"],
        "missing_evidence": sorted(set(missing)),
        "decision_reasons": reasons or ["All applicable configured gates passed"],
        "provenance": {
            "git_commit": candidate.git_commit,
            "git_branch": candidate.git_branch,
            "metadata_git_commit": candidate.metadata_git_commit,
            "metadata_git_branch": candidate.metadata_git_branch,
        },
        "validation_evaluation": {
            "evaluation_id": candidate.validation_evaluation_id,
            "report_sha256": candidate.validation_evaluation_sha256,
        },
        "limitations": ["Validation decision is not production approval or deployment authorization", "No test-set metrics are included"],
    }


def canonical_candidate(
    model_family: str,
    evaluation_report_path: Path,
) -> tuple[CandidateEvidence, Callable[[CandidateEvidence], tuple[bool, str]]]:
    """Load one canonical artifact and bind it to existing validation evidence."""
    from src import inference
    from mlflow.tracking import MlflowClient

    if model_family not in inference.CANONICAL_MODELS:
        raise ValueError(f"Unknown model family: {model_family}")
    try:
        loaded = inference.load_model(model_family)
    except RuntimeError as error:
        if "Cannot read configured MLflow record" in str(error):
            raise ValidationInfrastructureError(str(error)) from error
        raise
    try:
        evaluation = json.loads(evaluation_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read validation evaluation report: {error}") from error
    model_record = evaluation.get("models", {}).get(model_family)
    if not isinstance(model_record, dict):
        raise ValueError(f"Evaluation report has no evidence for {model_family}")
    if evaluation.get("record_type") != "validation_evaluation":
        raise ValueError("Evidence file is not a validation evaluation record")
    if evaluation.get("evaluation_split", {}).get("identifier") != "chronological_validation_split":
        raise ValueError("Evaluation evidence does not identify the expected validation split")
    spec = loaded.spec
    expected_lineage = {
        "artifact_path": spec.artifact_path,
        "metadata_path": spec.metadata_path,
        "artifact_sha256": spec.artifact_sha256,
        "metadata_sha256": spec.metadata_sha256,
        "pipeline_run_id": spec.pipeline_run_id,
        "model_name": model_family,
        "training_run_id": spec.training_run_id,
        "artifact_import_run_id": spec.artifact_import_run_id,
        "metadata_run_id": spec.pipeline_run_id,
    }
    for key, expected in expected_lineage.items():
        if model_record.get(key) != expected:
            raise ValueError(f"Evaluation report {key} does not match canonical {model_family} artifact")

    client = MlflowClient()
    source_run_id = spec.training_run_id or spec.artifact_import_run_id
    try:
        source_run = client.get_run(source_run_id)
    except Exception as error:
        raise ValidationInfrastructureError(
            f"Could not read source MLflow run {source_run_id}: {error}"
        ) from error
    metadata = loaded.metadata
    if spec.training_run_id:
        run_metric_name = "autoencoder_validation_reconstruction_mse" if model_family == "autoencoder" else f"{model_family}_validation_ap"
        expected_run_metric = metadata.get("configuration", {}).get("best_validation_reconstruction_mse") if model_family == "autoencoder" else metadata.get("reproduced_validation_metric")
        actual_run_metric = source_run.data.metrics.get(run_metric_name)
        if actual_run_metric is None or expected_run_metric is None or not math.isclose(float(actual_run_metric), float(expected_run_metric), rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(f"Training run metric {run_metric_name} does not match model metadata")

    if model_family == "autoencoder":
        mse = metadata.get("configuration", {}).get("best_validation_reconstruction_mse")
        metrics = (MetricEvidence("validation_reconstruction_mse", mse, f"{spec.metadata_path}:configuration.best_validation_reconstruction_mse", "validation reconstruction MSE; checkpoint-selection metric; not a fraud probability"),)
    else:
        common = evaluation.get("common_cohort_results", {}).get("models", {}).get(model_family, {})
        ap = common.get("metrics", {}).get("average_precision")
        metrics = (MetricEvidence("average_precision", ap, f"{evaluation_report_path}:common_cohort_results.models.{model_family}", "sklearn average_precision_score over continuous fraud probabilities"),)

    try:
        commit = source_run.data.tags.get("git_commit")
        branch = source_run.data.tags.get("git_branch")
        if commit == "unknown": commit = None
        if branch == "unknown": branch = None
    except Exception:
        commit = branch = None
    metadata_git = metadata.get("provenance", {}).get("git", {})
    metadata_commit = metadata_git.get("commit") if isinstance(metadata_git, dict) else None
    metadata_branch = metadata_git.get("branch") if isinstance(metadata_git, dict) else None
    if metadata_commit == "unknown":
        metadata_commit = None
    if metadata_branch == "unknown":
        metadata_branch = None
    lineage_verified = True
    if spec.training_run_id:
        try:
            run_artifacts = client.list_artifacts(
                source_run_id, f"models/{model_family}"
            )
        except Exception as error:
            raise ValidationInfrastructureError(
                f"Could not inspect model artifacts in source MLflow run {source_run_id}: {error}"
            ) from error
        artifact_names = {artifact.path.rsplit("/", 1)[-1] for artifact in run_artifacts}
        lineage_verified = {
            loaded.artifact_path.name, loaded.metadata_path.name,
        }.issubset(artifact_names)
    candidate = CandidateEvidence(
        model_family=model_family,
        artifact_path=loaded.artifact_path,
        metadata_path=loaded.metadata_path,
        artifact_uri=spec.artifact_path,
        metadata_uri=spec.metadata_path,
        artifact_sha256=spec.artifact_sha256,
        metadata_sha256=spec.metadata_sha256,
        training_run_id=spec.training_run_id,
        artifact_import_run_id=spec.artifact_import_run_id,
        pipeline_run_id=spec.pipeline_run_id,
        source_run_status=source_run.info.status,
        lineage_verified=lineage_verified,
        metrics=metrics,
        git_commit=commit,
        git_branch=branch,
        metadata_git_commit=metadata_commit,
        metadata_git_branch=metadata_branch,
        artifact_load_verified=True,
        artifact_load_detail="Canonical inference loader verified hash, metadata, lineage, preprocessing and model compatibility",
        validation_evaluation_id=evaluation.get("evaluation_id"),
        validation_evaluation_sha256=_sha256(evaluation_report_path),
    )
    return candidate, lambda _: (True, "Canonical inference loader verified artifact compatibility")


def verify_registry_lineage(candidate: CandidateEvidence, client: Any | None = None) -> tuple[bool, str]:
    """Read a Registry version and verify its source run and artifact tags."""
    from src.model_registry import registered_model_name
    from mlflow.exceptions import MlflowException
    from mlflow.tracking import MlflowClient

    if not candidate.registered_model_name or not candidate.registered_model_version:
        return False, "Registered Model name and version are required for Registry verification"
    expected_name = registered_model_name(candidate.model_family)
    if candidate.registered_model_name != expected_name:
        return False, "Registered Model name does not match the stable project name"
    try:
        registry_client = client or MlflowClient()
        version = registry_client.get_model_version(
            candidate.registered_model_name, candidate.registered_model_version
        )
    except MlflowException as error:
        if getattr(error, "error_code", None) == "RESOURCE_DOES_NOT_EXIST":
            return False, "The requested Registered Model version does not exist"
        raise ValidationInfrastructureError(
            f"Could not read MLflow Registry version: {error}"
        ) from error
    expected_run = candidate.training_run_id or candidate.artifact_import_run_id
    tags = version.tags or {}
    expected_artifact_uri = (
        f"runs:/{expected_run}/models/{candidate.model_family}/"
        f"{candidate.artifact_path.name}"
    )
    expected_metadata_uri = (
        f"runs:/{expected_run}/models/{candidate.model_family}/"
        f"{candidate.metadata_path.name}"
    )
    matches = (
        version.run_id == expected_run
        and tags.get("source_run_id") == expected_run
        and tags.get("pipeline_run_id") == candidate.pipeline_run_id
        and version.source == expected_artifact_uri
        and tags.get("source_artifact_uri") == expected_artifact_uri
        and tags.get("metadata_artifact_uri") == expected_metadata_uri
        and tags.get("model_name") == candidate.model_family
        and tags.get("registered_model_name") == candidate.registered_model_name
    )
    return matches, (
        "Registered version source run, model, and artifact metadata tags match"
        if matches else "Registered version source run or artifact lineage does not match"
    )


def write_report(report: dict[str, Any], output_directory: Path) -> Path:
    """Write a unique JSON report without overwriting an existing report."""
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        path = output_directory / f"validation_{report['model_family']}_{report['report_id']}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except OSError as error:
        raise ValidationInfrastructureError(f"Could not write validation report: {error}") from error
    return path


def main(argv: list[str] | None = None) -> int:
    """Validate one canonical candidate against an existing evaluation record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=MODEL_FAMILIES)
    parser.add_argument("--evaluation-report", required=True, type=Path)
    parser.add_argument("--policy", type=Path, default=Path("configs/validation_policy_v1.json"))
    parser.add_argument("--output-directory", type=Path, default=Path("reports/validation_gates"))
    parser.add_argument("--registered-model-name")
    parser.add_argument("--registered-model-version")
    args = parser.parse_args(argv)
    policy = load_policy(args.policy)
    candidate, validator = canonical_candidate(args.model, args.evaluation_report)
    if bool(args.registered_model_name) != bool(args.registered_model_version):
        parser.error("--registered-model-name and --registered-model-version must be supplied together")
    if args.registered_model_name:
        candidate = replace(
            candidate,
            registered_model_name=args.registered_model_name,
            registered_model_version=args.registered_model_version,
        )
        registry_matches, registry_detail = verify_registry_lineage(candidate)
        candidate = replace(candidate, registry_lineage_verified=registry_matches)
        if not registry_matches:
            print(json.dumps({"registry_lineage": registry_detail}, sort_keys=True))
    report = assess_candidate(candidate, policy, artifact_validator=validator)
    path = write_report(report, args.output_directory)
    print(json.dumps({"decision": report["decision"], "report": str(path)}, sort_keys=True))
    return 0 if report["decision"] == "PASS" else 2 if report["decision"] == "FAIL" else 3


if __name__ == "__main__":
    raise SystemExit(main())
