"""Build a read-only M5 validation evidence inventory and policy analysis.

This module reads existing validation reports, canonical model metadata, M4
gate reports, and MLflow records. It never loads model estimators or datasets.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mlflow.tracking import MlflowClient

from src import inference
from src.validation_gates import (
    MODEL_FAMILIES,
    CandidateEvidence,
    MetricEvidence,
    ValidationInfrastructureError,
    assess_candidate,
    load_policy,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVALUATION = Path(
    "reports/validation_evaluation_1d24658eef4f4241b4f4e4c1e3a00578.json"
)
DEFAULT_UNCERTAINTY = Path(
    "reports/validation_analysis/ap_uncertainty_v1/"
    "1d24658eef4f4241b4f4e4c1e3a00578/"
    "ed15981caa484568a534d15c73d51715/paired_ap_uncertainty.json"
)
DEFAULT_TEMPORAL = Path(
    "reports/validation_analysis/temporal_stability_v1/"
    "1d24658eef4f4241b4f4e4c1e3a00578/"
    "99ea1c0797ab47d5b2c3f8b10f2a4de2/temporal_stability_report.json"
)
DEFAULT_OUTPUT_ROOT = Path("reports/validation_policy_analysis_v1")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _safe_tracking_uri(uri: str | None) -> str | None:
    """Avoid persisting local absolute paths or credentials in the inventory."""
    if uri is None:
        return None
    if uri.startswith("sqlite:"):
        return "sqlite:///mlflow.db" if uri.rstrip("/").endswith("mlflow.db") else "sqlite:///<redacted>"
    if uri.startswith("file:"):
        return "file:///<redacted>"
    if "://" in uri:
        scheme, remainder = uri.split("://", 1)
        authority = remainder.split("/", 1)[0]
        if "@" in authority:
            authority = authority.rsplit("@", 1)[1]
        return f"{scheme}://{authority}/<path-redacted>"
    return "<redacted>"


def _source_record(client: Any, record_id: str | None) -> dict[str, Any]:
    if not record_id:
        return {"record_id": None, "status": None, "record_type": None, "error": "No source record ID"}
    try:
        run = client.get_run(record_id)
    except Exception as error:  # Tracking evidence is optional but reported explicitly.
        return {"record_id": record_id, "status": None, "record_type": None,
                "error": f"{type(error).__name__}: {error}"}
    tags = run.data.tags
    record_type = tags.get("record_type")
    try:
        artifact_paths = _list_artifact_paths(client, record_id)
        artifact_error = None
    except Exception as error:
        artifact_paths = []
        artifact_error = f"{type(error).__name__}: {error}"
    return {
        "record_id": record_id,
        "status": run.info.status,
        "record_type": record_type,
        "record_type_tag": record_type,
        "pipeline_run_id": tags.get("pipeline_run_id"),
        "project_tag": tags.get("project"),
        "training_run_recovered_tag": tags.get("training_run_recovered"),
        "git_commit": tags.get("git_commit"),
        "git_branch": tags.get("git_branch"),
        "started_at_utc": (
            datetime.fromtimestamp(start_time / 1000, timezone.utc).isoformat()
            if (start_time := getattr(run.info, "start_time", None)) is not None else None
        ),
        "ended_at_utc": (
            datetime.fromtimestamp(end_time / 1000, timezone.utc).isoformat()
            if (end_time := getattr(run.info, "end_time", None)) is not None else None
        ),
        "recorded_metric_names": sorted(run.data.metrics),
        "recorded_metrics": {key: float(value) for key, value in sorted(run.data.metrics.items())},
        "artifact_paths": artifact_paths,
        "artifact_listing_error": artifact_error,
    }


def _list_artifact_paths(client: Any, run_id: str) -> list[str]:
    """List an existing run's artifact paths read-only, without downloading data."""
    paths: list[str] = []
    pending = [""]
    while pending:
        parent = pending.pop()
        for item in client.list_artifacts(run_id, parent):
            if item.is_dir:
                pending.append(item.path)
            else:
                paths.append(item.path)
    return sorted(paths)


def _gate_path(gate_directory: Path, family: str, evaluation_id: str) -> Path | None:
    matches = []
    for path in sorted(gate_directory.glob("*.json")):
        try:
            report = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if report.get("model_family") == family and report.get("validation_evaluation", {}).get("evaluation_id") == evaluation_id:
            matches.append(path)
    return matches[0] if len(matches) == 1 else None


def _metric_source(record: dict[str, Any], family: str, cohort: str) -> dict[str, Any]:
    metrics = record["metrics"]
    return {
        "average_precision": metrics.get("average_precision"),
        "roc_auc": metrics.get("roc_auc"),
        "row_count": record.get("row_count"),
        "target_class_counts": record.get("target_class_counts"),
        "source_pointer": f"{cohort}_cohort_results.models.{family}",
    }


def _verify_source_record_identity(
    source_record: dict[str, Any],
    expected_type: str,
    pipeline_run_id: str,
    artifact_path: str,
    metadata_path: str,
    model_family: str,
) -> bool | None:
    """Verify source type and the lineage fields appropriate to that record type."""
    observed_type = source_record.get("record_type")
    if observed_type is not None and observed_type != expected_type:
        return False
    if expected_type == "training_run" and observed_type in (None, "training_run"):
        observed_pipeline = source_record.get("pipeline_run_id")
        if observed_pipeline is None:
            return None
        if observed_pipeline != pipeline_run_id:
            return False
        names = {Path(path).name for path in source_record.get("artifact_paths", [])}
        if not {Path(artifact_path).name, Path(metadata_path).name}.issubset(names):
            return None
        metrics = set(source_record.get("recorded_metric_names", []))
        required_metrics = {f"{model_family}_validation_ap"}
        if model_family == "autoencoder":
            required_metrics.add("autoencoder_validation_reconstruction_mse")
        if not required_metrics.issubset(metrics):
            return None
        return True
    if expected_type == "artifact_import":
        if observed_type != "artifact_import":
            return None
        if source_record.get("artifact_listing_error"):
            return None
        paths = source_record.get("artifact_paths", [])
        names = {Path(path).name for path in paths}
        if not names:
            return None
        expected_names = {Path(artifact_path).name, Path(metadata_path).name, "artifact_import_manifest.json"}
        return expected_names.issubset(names)
    return False


def _prior_m5_outputs(output_root: Path) -> list[dict[str, str]]:
    """Identify earlier task-generated analyses so the latest record is unambiguous."""
    prior: list[dict[str, str]] = []
    if not output_root.is_dir():
        return prior
    for directory in sorted(item for item in output_root.iterdir() if item.is_dir()):
        inventory_path = directory / "evidence_inventory.json"
        analysis_path = directory / "policy_analysis.json"
        if not inventory_path.is_file() or not analysis_path.is_file():
            continue
        try:
            inventory = _read_json(inventory_path)
            report = _read_json(analysis_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if inventory.get("record_type") != "validation_evidence_inventory" or report.get("record_type") != "validation_policy_analysis":
            continue
        false_git_claim = any(
            model.get("lineage", {}).get("source_record", {}).get("git_commit") is None
            and model.get("lineage", {}).get("source_record", {}).get("git_branch") is None
            and model.get("existing_m4_gate_report", {}).get("decision") is not None
            and (
                candidate.get("other_gate_statuses", candidate.get("non_policy_gate_statuses", {}))
                .get("git_provenance") == "PASS"
            )
            for family, model in inventory.get("models", {}).items()
            for candidate in [report.get("candidates", {}).get(family, {})]
        )
        prior.append({
            "inventory_id": inventory.get("inventory_id", directory.name),
            "reason": (
                "Superseded: an earlier draft treated metadata Git fields as independently verified MLflow Git tags."
                if false_git_claim else
                "Superseded by the final M5 report, which includes the v2 incomplete-policy gate and final provenance checks."
            ),
        })
    return prior


def build_reports(
    *,
    evaluation_path: Path,
    policy_path: Path,
    gate_directory: Path,
    uncertainty_path: Path,
    temporal_path: Path,
    output_root: Path,
    client: Any | None = None,
    tracking_uri: str | None = None,
    registry_state: dict[str, Any] | None = None,
    created_at_utc: str | None = None,
    inventory_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Assemble evidence from persisted sources and run the M4 assessor read-only."""
    evaluation = _read_json(evaluation_path)
    if evaluation.get("record_type") != "validation_evaluation":
        raise ValueError("The supplied report is not a validation evaluation")
    policy = load_policy(policy_path)
    if set(evaluation.get("models", {})) != set(MODEL_FAMILIES):
        raise ValueError("Validation report does not contain all canonical model families")
    if set(evaluation.get("common_cohort_results", {}).get("models", {})) != set(MODEL_FAMILIES):
        raise ValueError("Common-cohort validation evidence is incomplete")
    if set(evaluation.get("native_cohort_results", {}).get("models", {})) != set(MODEL_FAMILIES):
        raise ValueError("Native-cohort validation evidence is incomplete")
    split = evaluation.get("evaluation_split", {})
    project_validation_report = (
        split.get("identifier") == "chronological_validation_split"
        and split.get("features_path") == "data/processed/X_val.parquet"
        and split.get("labels_path") == "data/processed/y_val.parquet"
        and bool(split.get("features_sha256"))
        and bool(split.get("labels_sha256"))
    )
    if client is None:
        client = MlflowClient()

    evaluation_hash = _sha256(evaluation_path)
    policy_hash = _sha256(policy_path)
    models: dict[str, Any] = {}
    decisions: dict[str, Any] = {}
    for family in MODEL_FAMILIES:
        spec = inference.CANONICAL_MODELS[family]
        artifact_path = ROOT / spec.artifact_path
        metadata_path = ROOT / spec.metadata_path
        metadata = _read_json(metadata_path)
        record = evaluation["models"][family]
        common = evaluation["common_cohort_results"]["models"][family]
        native = evaluation["native_cohort_results"]["models"][family]
        gate_path = _gate_path(gate_directory, family, evaluation["evaluation_id"])
        gate = _read_json(gate_path) if gate_path else None
        artifact_observed_hash = _sha256(artifact_path) if artifact_path.is_file() else None
        metadata_observed_hash = _sha256(metadata_path)
        model_report_matches_canonical = (
            record.get("artifact_path") == spec.artifact_path
            and record.get("artifact_sha256") == spec.artifact_sha256
            and record.get("metadata_path") == spec.metadata_path
            and record.get("metadata_sha256") == spec.metadata_sha256
        )
        gate_artifacts = gate.get("artifacts", {}) if gate else {}
        gate_matches_canonical = (
            gate_artifacts.get("artifact_sha256") == spec.artifact_sha256
            and gate_artifacts.get("metadata_sha256") == spec.metadata_sha256
            and gate_artifacts.get("validation_evaluation_id") == evaluation["evaluation_id"]
            and gate_artifacts.get("validation_evaluation_sha256") == evaluation_hash
        )
        canonical_files_match = (
            artifact_observed_hash == spec.artifact_sha256
            and metadata_observed_hash == spec.metadata_sha256
        )
        source_id = spec.training_run_id or spec.artifact_import_run_id
        source_record = _source_record(client, source_id)
        if registry_state is None:
            try:
                registered = client.search_registered_models()
                registry_state = {"status": "available", "registered_model_count": len(registered),
                                  "names": sorted(item.name for item in registered)}
            except Exception as error:
                registry_state = {"status": "unavailable", "error": f"{type(error).__name__}: {error}"}

        source_type = "training_run" if spec.training_run_id else "artifact_import"
        source_identity_verified = _verify_source_record_identity(
            source_record, source_type, spec.pipeline_run_id,
            spec.artifact_path, spec.metadata_path, family,
        )
        source_record["record_type_classification"] = source_type if source_identity_verified else "unverified"
        source_record["record_type_classification_basis"] = (
            "canonical model registry identifier, matching pipeline tag, expected validation metric, and matching logged artifact files"
            if source_type == "training_run" and source_identity_verified else
            "explicit artifact_import record tag and matching logged model, metadata, and import manifest files"
            if source_type == "artifact_import" and source_identity_verified else
            "source record evidence was incomplete or inconsistent"
        )
        expected_metric = "validation_reconstruction_mse" if family == "autoencoder" else "average_precision"
        if gate is None:
            metric_value = None
            metric_source = None
            metric_interpretation = None
            artifact_load_verified = None
            lineage_verified = None
        else:
            quality_metric = next(
                (item for item in gate.get("metrics", []) if item.get("name") == expected_metric), None
            )
            metric_value = quality_metric.get("value") if quality_metric else None
            metric_source = quality_metric.get("source") if quality_metric else None
            metric_interpretation = quality_metric.get("interpretation") if quality_metric else None
            gate_statuses = {item.get("name"): item.get("status") for item in gate.get("gates", [])}
            artifact_load_verified = gate_statuses.get("artifact_compatibility") == "PASS"
            lineage_verified = gate_statuses.get("provenance_lineage") == "PASS"
        metrics = [MetricEvidence(expected_metric, metric_value, metric_source, metric_interpretation or expected_metric)]
        if family != "autoencoder":
            metrics.append(MetricEvidence(
                "roc_auc", common["metrics"].get("roc_auc"),
                f"{evaluation_path.relative_to(ROOT)}:common_cohort_results.models.{family}",
                "supporting ranking metric; not the primary policy metric",
            ))
        else:
            metrics.append(MetricEvidence(
                "average_precision", common["metrics"].get("average_precision"),
                f"{evaluation_path.relative_to(ROOT)}:common_cohort_results.models.{family}",
                "ranking AP over per-row reconstruction-error anomaly scores; not a fraud probability",
            ))
        candidate = CandidateEvidence(
            model_family=family,
            artifact_path=artifact_path,
            metadata_path=metadata_path,
            artifact_uri=spec.artifact_path,
            metadata_uri=spec.metadata_path,
            artifact_sha256=spec.artifact_sha256,
            metadata_sha256=spec.metadata_sha256,
            training_run_id=spec.training_run_id,
            artifact_import_run_id=spec.artifact_import_run_id,
            pipeline_run_id=spec.pipeline_run_id,
            source_run_status=source_record.get("status"),
            lineage_verified=(
                False if lineage_verified is False or source_identity_verified is False
                else True if lineage_verified is True and source_identity_verified is True
                else None
            ),
            metrics=tuple(metrics),
            git_commit=source_record.get("git_commit"),
            git_branch=source_record.get("git_branch"),
            metadata_git_commit=metadata.get("provenance", {}).get("git", {}).get("commit"),
            metadata_git_branch=metadata.get("provenance", {}).get("git", {}).get("branch"),
            artifact_load_verified=artifact_load_verified,
            artifact_load_detail="Canonical artifact compatibility was verified by the linked M4 report" if artifact_load_verified else None,
            validation_evaluation_id=evaluation["evaluation_id"],
            validation_evaluation_sha256=evaluation_hash,
        )
        decision = assess_candidate(candidate, policy)
        decisions[family] = {
            "decision": decision["decision"],
            "policy": decision["policy"],
            "quality_threshold": next(
                (item for item in decision["gates"] if item["name"] == "quality_threshold"), None
            ),
            "missing_evidence": decision["missing_evidence"],
            "decision_reasons": decision["decision_reasons"],
            "other_gate_statuses": {
                item["name"]: item["status"] for item in decision["gates"]
                if item["name"] != "quality_threshold"
            },
            "m4_report_path": str(gate_path.relative_to(ROOT)) if gate_path else None,
            "m4_report_sha256": _sha256(gate_path) if gate_path else None,
        }
        models[family] = {
            "evidence_classification": (
                "persisted_empirical_validation_tied_to_canonical_artifact"
                if project_validation_report and model_report_matches_canonical and gate_matches_canonical and canonical_files_match
                else "synthetic_or_unverified_fixture"
            ),
            "canonical_artifact": {
                "path": spec.artifact_path,
                "sha256_expected": spec.artifact_sha256,
                "sha256_observed": artifact_observed_hash,
                "exists": artifact_path.is_file(),
            },
            "metadata": {
                "path": spec.metadata_path,
                "sha256_expected": spec.metadata_sha256,
                "sha256_observed": metadata_observed_hash,
                "model_name": metadata.get("model_name"),
                "recorded_validation_metric": metadata.get("validation_metric"),
                "recorded_validation_value": metadata.get("reproduced_validation_metric"),
                "features": metadata.get("features"),
                "preprocessing": spec.preprocessing,
                "file_modified_at_utc": datetime.fromtimestamp(
                    metadata_path.stat().st_mtime, timezone.utc
                ).isoformat(),
            },
            "score_type": spec.score_type,
            "lineage": {
                "record_type": source_type,
                "training_run_id": spec.training_run_id,
                "artifact_import_run_id": spec.artifact_import_run_id,
                "pipeline_run_id": spec.pipeline_run_id,
                "source_record": source_record,
                "source_record_identity_verified": source_identity_verified,
                "provenance_limitation": spec.provenance_limitation,
            },
            "empirical_validation_metrics": {
                "source_report": str(evaluation_path.relative_to(ROOT)),
                "source_report_sha256": evaluation_hash,
                "native_cohort": _metric_source(native, family, "native"),
                "common_cohort": _metric_source(common, family, "common"),
                "quality_metric_for_policy": {
                    "name": expected_metric,
                    "value": metric_value,
                    "source": metric_source,
                    "interpretation": metric_interpretation,
                },
            },
            "existing_m4_gate_report": {
                "path": str(gate_path.relative_to(ROOT)) if gate_path else None,
                "sha256": _sha256(gate_path) if gate_path else None,
                "decision": gate.get("decision") if gate else None,
                "matches_canonical_artifact_and_evaluation": gate_matches_canonical,
                "note": "M4 report evaluates structure, lineage, and metric availability; its undefined threshold is preserved.",
            },
        }

    uncertainty = _read_json(uncertainty_path)
    temporal = _read_json(temporal_path)
    # Locate the score-analysis manifest by its recorded evaluation ID without reading data splits.
    manifests = list((ROOT / "reports/validation_analysis" / evaluation["evaluation_id"]).glob("**/analysis_manifest.json"))
    score_manifest_path = manifests[0] if manifests else None
    inventory_id = inventory_id or uuid.uuid4().hex
    created_at_utc = created_at_utc or datetime.now(timezone.utc).isoformat()
    prior_outputs = _prior_m5_outputs(output_root)
    try:
        tracking_uri_value = _safe_tracking_uri(tracking_uri or client.tracking_uri)
    except Exception:
        tracking_uri_value = tracking_uri
    inventory = {
        "schema_version": "1.0.0",
        "record_type": "validation_evidence_inventory",
        "inventory_id": inventory_id,
        "created_at_utc": created_at_utc,
        "scope": "Existing validation evidence only; no datasets or model predictions are loaded by this inventory.",
        "superseded_prior_m5_outputs": prior_outputs,
        "evaluation": {
            "path": str(evaluation_path.relative_to(ROOT)),
            "sha256": evaluation_hash,
            "evaluation_id": evaluation["evaluation_id"],
            "record_type": evaluation["record_type"],
            "created_at_utc": evaluation.get("created_at_utc"),
            "split": evaluation.get("evaluation_split"),
            "holdout_disclosure": evaluation.get("holdout_disclosure"),
            "metric_definitions": evaluation.get("metric_definitions"),
            "metric_implementation_versions": evaluation.get("metric_implementation_versions"),
        },
        "analysis_sources": {
            "paired_ap_uncertainty": {"path": str(uncertainty_path.relative_to(ROOT)), "sha256": _sha256(uncertainty_path), "analysis_id": uncertainty.get("analysis_id"), "record_type": uncertainty.get("record_type"), "limitations": uncertainty.get("limitations"), "method_count": len(uncertainty.get("results", []))},
            "temporal_stability": {"path": str(temporal_path.relative_to(ROOT)), "sha256": _sha256(temporal_path), "analysis_id": temporal.get("analysis_id"), "record_type": temporal.get("record_type"), "limitations": temporal.get("limitations"), "segmentation": temporal.get("segmentation"), "stability_summaries": temporal.get("stability_summaries")},
            "per_observation_scores": {"available": score_manifest_path is not None, "manifest_path": str(score_manifest_path.relative_to(ROOT)) if score_manifest_path else None, "manifest_sha256": _sha256(score_manifest_path) if score_manifest_path else None, "note": "Existing validation-only score outputs are identified but not read or recalculated here."},
            "m4_gate_reports": {"directory": str(gate_directory.relative_to(ROOT)), "reports_are_m4_outputs": True},
        },
        "models": models,
        "non_empirical_evidence": {
            "synthetic_test_fixtures": [{"path": "tests/test_validation_gates.py", "classification": "synthetic_unit_test_only", "not_empirical_model_evidence": True}],
            "documentation_search": {"locations": ["README.md", "configs/", "reports/validation_analysis/operational_feasibility_v1/"], "finding": "No approved numerical business or technical model-acceptance thresholds were found. Existing operating-point summaries are descriptive and explicitly do not select a threshold."},
            "missing_evidence": ["Approved business objective and acceptance requirement", "Operational constraints or documented cost/benefit assumptions", "Independent confirmation cohort for any threshold calibrated from validation data", "Recovered original training provenance for imported XGBoost, Logistic Regression, and LightGBM artifacts"],
        },
        "tracking_and_registry": {
            "tracking_uri": tracking_uri_value,
            "experiment_name": "Bank-Fraud-Detection",
            "registry": registry_state,
            "read_only_inspection": True,
        },
        "environment": {
            "python_version": platform.python_version(),
            "numpy": _version("numpy"), "pandas": _version("pandas"),
            "scikit_learn": _version("scikit-learn"), "mlflow": _version("mlflow"),
        },
        "policy": {
            "path": str(policy_path.relative_to(ROOT)),
            "sha256": policy_hash,
            "policy_id": policy.policy_id,
            "version": policy.version,
            "effective_status": policy.effective_status,
            "numerical_thresholds_defined": False,
        },
        "limitations": [
            "Validation metrics are conditional on the existing validation cohort and were used for model/checkpoint selection.",
            "The validation cohort contains only 56 fraud observations; uncertainty summaries are exploratory and do not establish superiority.",
            "The saved paired bootstrap uses repeated resamples of one validation cohort, not repeated independent model-training runs.",
            "The test split was examined previously; it is not used or included in this inventory and is not an untouched blind holdout.",
            "The Autoencoder is assessed with reconstruction MSE for checkpoint selection and anomaly-score AP as a separate ranking analysis; neither is a calibrated fraud probability.",
            "Imported artifact records identify artifact registration/import and are not recovered model-training runs.",
            "A LightGBM historical validation metric is not conclusively associated with the canonical binary.",
        ],
    }
    analysis = {
        "schema_version": "1.0.0",
        "record_type": "validation_policy_analysis",
        "analysis_id": inventory_id,
        "created_at_utc": created_at_utc,
        "evidence_inventory_id": inventory_id,
        "evidence_inventory_sha256": hashlib.sha256(
            json.dumps(inventory, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest(),
        "policy": inventory["policy"],
        "decision_semantics": {"precedence": ["FAIL", "INSUFFICIENT_EVIDENCE", "PASS"], "production_approval": False},
        "candidates": decisions,
        "thresholds": {
            family: {
                "metric": policy.quality_thresholds[family]["metric"],
                "operator": policy.quality_thresholds[family]["operator"],
                "value": policy.quality_thresholds[family]["value"],
                "source": policy.threshold_details.get(family, {}).get("source"),
                "rationale": policy.threshold_details.get(family, {}).get("rationale"),
                "calibration_evidence_reference": policy.threshold_details.get(family, {}).get("calibration_evidence_reference"),
                "calibration_timestamp": policy.threshold_details.get(family, {}).get("calibration_timestamp"),
                "calibration_method": policy.threshold_details.get(family, {}).get("calibration_method"),
                "decision": "INSUFFICIENT_EVIDENCE",
            }
            for family in MODEL_FAMILIES
        },
        "calibration_method": None,
        "calibration_evidence_reference": None,
        "interpretation": "No acceptance threshold is justified by current evidence. M4's deterministic decision engine is reused; available empirical metrics do not become approval criteria merely because they are observed.",
        "next_safe_action": "Obtain an approved operational objective and constraints, define a calibration protocol without using test data, and reserve a distinct cohort for independent confirmation before activating numerical thresholds.",
    }
    run_directory = output_root / inventory_id
    if run_directory.exists():
        raise ValidationInfrastructureError(f"Refusing to overwrite existing policy-analysis output: {run_directory}")
    try:
        run_directory.mkdir(parents=True, exist_ok=False)
        for name, payload in (("evidence_inventory.json", inventory), ("policy_analysis.json", analysis)):
            with (run_directory / name).open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
    except OSError as error:
        raise ValidationInfrastructureError(f"Could not write M5 policy-analysis reports: {error}") from error
    return inventory, analysis, run_directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-report", type=Path, default=DEFAULT_EVALUATION)
    parser.add_argument("--policy", type=Path, default=Path("configs/validation_policy_v2.json"))
    parser.add_argument("--gate-directory", type=Path, default=Path("reports/validation_gates"))
    parser.add_argument("--uncertainty-report", type=Path, default=DEFAULT_UNCERTAINTY)
    parser.add_argument("--temporal-report", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    paths = [args.evaluation_report, args.policy, args.uncertainty_report, args.temporal_report]
    resolved = [path if path.is_absolute() else ROOT / path for path in paths]
    gate_directory = args.gate_directory if args.gate_directory.is_absolute() else ROOT / args.gate_directory
    output_root = args.output_root if args.output_root.is_absolute() else ROOT / args.output_root
    try:
        inventory, analysis, directory = build_reports(
            evaluation_path=resolved[0], policy_path=resolved[1], gate_directory=gate_directory,
            uncertainty_path=resolved[2], temporal_path=resolved[3], output_root=output_root,
        )
    except (OSError, ValueError, ValidationInfrastructureError) as error:
        parser.error(str(error))
    print(json.dumps({
        "evidence_inventory": str(directory / "evidence_inventory.json"),
        "policy_analysis": str(directory / "policy_analysis.json"),
        "candidate_decisions": {key: value["decision"] for key, value in analysis["candidates"].items()},
        "registry_state": inventory["tracking_and_registry"]["registry"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
