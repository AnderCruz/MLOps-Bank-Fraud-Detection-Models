"""Audit existing evidence and define an independent evaluation plan.

This module reads persisted reports, model metadata and hashes, and MLflow
records. It never loads datasets or estimators and never scores a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mlflow.tracking import MlflowClient


ROOT = Path(__file__).resolve().parents[1]
MODEL_FAMILIES = (
    "random_forest",
    "xgboost",
    "logistic_regression",
    "lightgbm",
    "mlp",
    "autoencoder",
    "lstm",
    "gru",
)
EVALUATION_PATH = Path(
    "reports/validation_evaluation_1d24658eef4f4241b4f4e4c1e3a00578.json"
)
M5_INVENTORY_PATH = Path(
    "reports/validation_policy_analysis_v1/"
    "8f76ffc6bfb6420dbbe90b4a37de1579/evidence_inventory.json"
)
M5_ANALYSIS_PATH = Path(
    "reports/validation_policy_analysis_v1/"
    "8f76ffc6bfb6420dbbe90b4a37de1579/policy_analysis.json"
)
POLICY_PATH = Path("configs/validation_policy_v2.json")
UNCERTAINTY_PATH = Path(
    "reports/validation_analysis/ap_uncertainty_v1/"
    "1d24658eef4f4241b4f4e4c1e3a00578/"
    "ed15981caa484568a534d15c73d51715/paired_ap_uncertainty.json"
)
TEMPORAL_PATH = Path(
    "reports/validation_analysis/temporal_stability_v1/"
    "1d24658eef4f4241b4f4e4c1e3a00578/"
    "99ea1c0797ab47d5b2c3f8b10f2a4de2/temporal_stability_report.json"
)
DEFAULT_OUTPUT_ROOT = Path("reports/evidence_readiness_v1")


def sha256_file(path: Path) -> str:
    """Hash an existing file without interpreting model or dataset contents."""
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


def _artifact_paths(client: Any, run_id: str) -> list[str]:
    pending = [""]
    result: list[str] = []
    while pending:
        parent = pending.pop()
        for item in client.list_artifacts(run_id, parent):
            if item.is_dir:
                pending.append(item.path)
            else:
                result.append(item.path)
    return sorted(result)


def collect_tracking_evidence(
    inventory: dict[str, Any], client: Any
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Read the referenced MLflow records and Registry without changing them."""
    records: dict[str, dict[str, Any]] = {}
    for family in MODEL_FAMILIES:
        lineage = inventory["models"][family]["lineage"]
        run_id = lineage.get("training_run_id") or lineage.get("artifact_import_run_id")
        if not run_id:
            records[family] = {"record_id": None, "available": False}
            continue
        run = client.get_run(run_id)
        tags = run.data.tags
        records[family] = {
            "record_id": run_id,
            "available": True,
            "status": run.info.status,
            "started_at_utc": (
                datetime.fromtimestamp(run.info.start_time / 1000, timezone.utc).isoformat()
                if run.info.start_time is not None else None
            ),
            "ended_at_utc": (
                datetime.fromtimestamp(run.info.end_time / 1000, timezone.utc).isoformat()
                if run.info.end_time is not None else None
            ),
            "artifact_uri_scheme": str(run.info.artifact_uri).split(":", 1)[0]
            if run.info.artifact_uri else None,
            "record_type_tag": tags.get("record_type"),
            "training_run_recovered_tag": tags.get("training_run_recovered"),
            "pipeline_run_id_tag": tags.get("pipeline_run_id"),
            "git_commit_tag": tags.get("git_commit"),
            "git_branch_tag": tags.get("git_branch"),
            "model_name_tag": tags.get("model_name"),
            "metric_values": {
                key: float(value) for key, value in sorted(run.data.metrics.items())
            },
            "parameters": dict(sorted(run.data.params.items())),
            "artifact_paths": _artifact_paths(client, run_id),
        }
    registered_models = client.search_registered_models()
    registry = {
        "inspection": "read_only",
        "registered_model_count": len(registered_models),
        "registered_model_names": sorted(model.name for model in registered_models),
    }
    return records, registry


def classify_evidence(record_type: str | None, *, is_synthetic: bool = False) -> str:
    """Map evidence facts to explicit provenance classes."""
    if is_synthetic:
        return "SYNTHETIC_TEST_EVIDENCE"
    if record_type == "training_run":
        return "EMPIRICAL_TRAINING_EVIDENCE"
    if record_type == "artifact_import":
        return "ARTIFACT_IMPORT_EVIDENCE"
    if record_type == "validation_evaluation":
        return "EMPIRICAL_VALIDATION_EVIDENCE"
    if record_type == "derived_analysis":
        return "DERIVED_ANALYSIS"
    if record_type == "documentation":
        return "DOCUMENTATION_ONLY"
    if record_type == "missing":
        return "MISSING"
    return "UNVERIFIED"


def _model_evidence(
    family: str,
    inventory_model: dict[str, Any],
    evaluation_model: dict[str, Any],
    common_model: dict[str, Any],
    native_model: dict[str, Any],
    metadata: dict[str, Any],
    observed_artifact_hash: str | None,
    observed_metadata_hash: str | None,
    tracking: dict[str, Any],
    evaluation_document: dict[str, Any],
) -> dict[str, Any]:
    lineage = inventory_model["lineage"]
    is_import = lineage.get("record_type") == "artifact_import"
    expected_artifact_hash = inventory_model["canonical_artifact"]["sha256_expected"]
    expected_metadata_hash = inventory_model["metadata"]["sha256_expected"]
    observed_type = tracking.get("record_type_tag")
    if is_import:
        expected_names = {
            Path(inventory_model["canonical_artifact"]["path"]).name,
            Path(inventory_model["metadata"]["path"]).name,
            "artifact_import_manifest.json",
        }
        observed_names = {Path(path).name for path in tracking.get("artifact_paths", [])}
        tracking_type_matches = observed_type == "artifact_import"
        recovered = tracking.get("training_run_recovered_tag") == "false"
        tracking_classification = (
            "VERIFIED_ARTIFACT_IMPORT_EVENT"
            if tracking_type_matches and recovered
            and expected_names.issubset(observed_names)
            and not tracking.get("metric_values") else "UNVERIFIED"
        )
        training_evidence = "UNVERIFIED"
    else:
        pipeline_matches = (
            tracking.get("pipeline_run_id_tag") == lineage.get("pipeline_run_id")
        )
        expected_names = {
            Path(inventory_model["canonical_artifact"]["path"]).name,
            Path(inventory_model["metadata"]["path"]).name,
        }
        observed_names = {Path(path).name for path in tracking.get("artifact_paths", [])}
        expected_metrics = {f"{family}_validation_ap"}
        if family == "autoencoder":
            expected_metrics.add("autoencoder_validation_reconstruction_mse")
        tracking_classification = (
            "VERIFIED_TRAINING_RUN_RECORD"
            if tracking.get("available")
            and tracking.get("status") == "FINISHED"
            and pipeline_matches
            and expected_names.issubset(observed_names)
            and expected_metrics.issubset(tracking.get("metric_values", {}))
            else "UNVERIFIED"
        )
        training_evidence = (
            classify_evidence("training_run")
            if tracking_classification == "VERIFIED_TRAINING_RUN_RECORD"
            else "UNVERIFIED"
        )

    score_type = inventory_model.get("score_type")
    metric_semantics = (
        "Average Precision over per-row reconstruction-error anomaly scores; not a probability"
        if family == "autoencoder"
        else "Average Precision over continuous fraud-probability scores"
    )
    validation_is_linked = (
        evaluation_model.get("artifact_path") == inventory_model["canonical_artifact"]["path"]
        and evaluation_model.get("artifact_sha256") == expected_artifact_hash
        and evaluation_model.get("metadata_path") == inventory_model["metadata"]["path"]
        and evaluation_model.get("metadata_sha256") == expected_metadata_hash
        and observed_artifact_hash == expected_artifact_hash
        and observed_metadata_hash == expected_metadata_hash
    )
    configuration = metadata.get("configuration", {})
    training_metric = (
        "validation reconstruction MSE" if family == "autoencoder"
        else "Average Precision (AP)" if family in {"mlp", "lstm", "gru"}
        else None
    )
    return {
        "model_family": family,
        "score_type": score_type,
        "artifact": {
            "path": inventory_model["canonical_artifact"]["path"],
            "expected_sha256": expected_artifact_hash,
            "observed_sha256": observed_artifact_hash,
            "hash_matches": observed_artifact_hash == expected_artifact_hash,
            "evidence_classification": "VERIFIED_ARTIFACT_BYTES" if observed_artifact_hash else "MISSING",
        },
        "metadata": {
            "path": inventory_model["metadata"]["path"],
            "expected_sha256": expected_metadata_hash,
            "observed_sha256": observed_metadata_hash,
            "hash_matches": observed_metadata_hash == expected_metadata_hash,
            "model_name": metadata.get("model_name"),
            "ordered_features": metadata.get("features"),
            "preprocessing": inventory_model["metadata"].get("preprocessing"),
            "configuration_summary": configuration,
            "recorded_file_modified_at_utc": inventory_model["metadata"].get("file_modified_at_utc"),
            "evidence_classification": "DOCUMENTATION_ONLY",
            "caveat": "Metadata claims are not treated as independent MLflow tags or proof of original training history.",
        },
        "lineage": {
            "record_type": lineage.get("record_type"),
            "training_run_id": lineage.get("training_run_id"),
            "artifact_import_run_id": lineage.get("artifact_import_run_id"),
            "pipeline_run_id": lineage.get("pipeline_run_id"),
            "tracking_record": tracking,
            "source_artifact_uri_reference": {
                "mlflow_record_id": tracking.get("record_id"),
                "artifact_uri_scheme": tracking.get("artifact_uri_scheme"),
                "relative_artifact_paths": tracking.get("artifact_paths", []),
                "absolute_local_uri_omitted": True,
            },
            "tracking_record_classification": tracking_classification,
            "training_provenance_classification": training_evidence,
            "git_provenance": {
                "mlflow_commit_tag": tracking.get("git_commit_tag"),
                "mlflow_branch_tag": tracking.get("git_branch_tag"),
                "status": (
                    "VERIFIED_FROM_MLFLOW_TAGS"
                    if tracking.get("git_commit_tag") and tracking.get("git_branch_tag")
                    else "UNVERIFIED"
                ),
                "metadata_git_fields_are_independent_evidence": False,
            },
            "original_training_recovered": (
                not is_import
                and tracking_classification == "VERIFIED_TRAINING_RUN_RECORD"
            ),
            "known_limitation": lineage.get("provenance_limitation"),
        },
        "validation_evidence": {
            "evidence_classification": classify_evidence("validation_evaluation"),
            "evaluation_id": "1d24658eef4f4241b4f4e4c1e3a00578",
            "source_report": EVALUATION_PATH.as_posix(),
            "source_record_created_at_utc": evaluation_document.get("created_at_utc"),
            "evaluation_method": {
                "split": evaluation_document.get("evaluation_split"),
                "split_hashes_status": "Recorded in the evaluation report; source dataset bytes were not reread or rehashed during this audit.",
                "metric_definitions": evaluation_document.get("metric_definitions"),
                "metric_implementation_versions": evaluation_document.get("metric_implementation_versions"),
            },
            "artifact_linkage_verified_by_hash_and_report_fields": validation_is_linked,
            "native_cohort": native_model,
            "common_cohort": common_model,
            "metric_semantics": metric_semantics,
            "score_type": score_type,
            "used_for_prior_exploratory_comparison": True,
            "validation_used_for_project_model_comparison": True,
            "checkpoint_selection_metric": training_metric,
            "checkpoint_selection_use": (
                "Validation reconstruction MSE selected the Autoencoder checkpoint. AP is a separate anomaly-ranking result."
                if family == "autoencoder" else
                "Validation AP selected neural checkpoints where configured; validation results also informed project model comparison."
                if family in {"mlp", "lstm", "gru"} else
                "Validation AP informed project-level model comparison; a distinct per-model checkpoint metric is not recorded here."
            ),
            "independent_confirmation": False,
            "independence_limitation": (
                "Validation was used for model/checkpoint selection and prior exploratory analysis; the test split was examined previously."
            ),
        },
        "historical_metric_provenance": {
            "metadata_reproduced_validation_metric": metadata.get("reproduced_validation_metric"),
            "metadata_reference_validation_ap": metadata.get("reference_validation_ap"),
            "current_mlflow_metrics": tracking.get("metric_values", {}),
            "current_persisted_evaluation_linked_to_canonical_artifact": validation_is_linked,
            "historical_reference_ap_attribution_to_canonical_artifact": "NOT_ESTABLISHED",
            "caveat": (
                "The root-level LightGBM binary differs from the canonical aggregate binary; the historical reference AP is not conclusively linked to the canonical bytes."
                if family == "lightgbm" else
                "Original training provenance was not recovered for this imported artifact. The current evaluation record is separate evidence tied to the canonical artifact hash."
                if is_import else
                "A controlled run and current evaluation are linked to the artifact; the notebook reference AP remains a historical comparator, not an independent result for these bytes."
            ),
        },
    }


def build_report(
    *,
    inventory: dict[str, Any],
    evaluation: dict[str, Any],
    policy: dict[str, Any],
    analysis_sources: dict[str, dict[str, Any]],
    metadata_by_model: dict[str, dict[str, Any]],
    artifact_hashes: dict[str, str | None],
    metadata_hashes: dict[str, str | None],
    tracking_records: dict[str, dict[str, Any]],
    registry: dict[str, Any],
    report_id: str,
    created_at_utc: str,
    superseded_prior_report_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build the evidence audit, readiness matrix, requirements and protocol."""
    if set(inventory.get("models", {})) != set(MODEL_FAMILIES):
        raise ValueError("Evidence inventory must contain exactly the eight model families")
    if set(evaluation.get("models", {})) != set(MODEL_FAMILIES):
        raise ValueError("Evaluation report must contain exactly the eight model families")
    if set(policy.get("quality_thresholds", {})) != set(MODEL_FAMILIES):
        raise ValueError("Acceptance policy must cover exactly the eight model families")

    models: dict[str, Any] = {}
    readiness: dict[str, Any] = {}
    for family in MODEL_FAMILIES:
        inventory_model = inventory["models"][family]
        metrics = evaluation["common_cohort_results"]["models"][family]
        native_metrics = evaluation["native_cohort_results"]["models"][family]
        record = _model_evidence(
            family,
            inventory_model,
            evaluation["models"][family],
            metrics,
            native_metrics,
            metadata_by_model[family],
            artifact_hashes.get(family),
            metadata_hashes.get(family),
            tracking_records.get(family, {"available": False}),
            evaluation,
        )
        models[family] = record
        readiness[family] = {
            "exploratory_comparison": "SUITABLE_FOR_EXPLORATORY_ANALYSIS",
            "threshold_calibration": "INSUFFICIENT_EVIDENCE",
            "independent_confirmation": "NOT_INDEPENDENT_FOR_CONFIRMATION",
            "production_approval": "INSUFFICIENT_EVIDENCE",
            "basis": [
                "Persisted validation scores and aggregate metrics exist for the canonical artifact.",
                "The validation cohort was used for model/checkpoint selection and repeated exploratory analysis.",
                "No approved operational objective, numeric threshold rationale, or fresh independent cohort is documented.",
            ],
        }

    operational_register = _operational_register()
    evaluation_design = _evaluation_design()
    acquisition_plan = _acquisition_plan()
    return {
        "schema_version": "1.0.0",
        "record_type": "evidence_acquisition_and_independent_validation_design",
        "report_id": report_id,
        "created_at_utc": created_at_utc,
        "superseded_prior_report_ids": sorted(superseded_prior_report_ids or []),
        "scope": {
            "model_families": list(MODEL_FAMILIES),
            "purpose": "Audit existing evidence, register missing operational decisions, and specify an independent chronological evaluation design.",
            "actions_not_performed": [
                "model training or retraining", "empirical inference or scoring on project data", "dataset loading",
                "test-set metric calculation", "threshold selection", "policy threshold modification",
            ],
            "verification_activity": {
                "full_unit_test_suite_executed": True,
                "synthetic_inference_unit_tests_may_execute_model_code": True,
                "empirical_dataset_loaded_or_scored": False,
                "test_split_loaded_or_used": False,
            },
        },
        "source_manifest": {
            "m5_inventory_id": inventory.get("inventory_id"),
            "m5_analysis_id": inventory.get("inventory_id"),
            "evaluation_id": evaluation.get("evaluation_id"),
            "policy_id": policy.get("policy_id"),
            "registry_inspection": registry,
            "source_references": analysis_sources,
        },
        "evidence_provenance_audit": {
            "classification_definitions": {
                "EMPIRICAL_VALIDATION_EVIDENCE": "Observed validation scores or metrics from a recorded evaluation; selection-conditioned unless stated otherwise.",
                "EMPIRICAL_TRAINING_EVIDENCE": "A completed recorded model-training run and its logged outputs; not independent validation.",
                "ARTIFACT_IMPORT_EVIDENCE": "A recorded import/registration event; it does not establish original model training history.",
                "SYNTHETIC_TEST_EVIDENCE": "Synthetic unit-test fixtures only; never empirical model evidence.",
                "DOCUMENTATION_ONLY": "A statement recorded in source or project documentation, not independently observed data.",
                "DERIVED_ANALYSIS": "A calculation over already persisted validation evidence.",
                "UNVERIFIED": "A claim whose source, lineage, or independent corroboration is absent or insufficient.",
                "MISSING": "Required evidence is not present in inspected repository sources.",
            },
            "models": models,
            "derived_analyses": [
                {
                    "evidence_classification": classify_evidence("derived_analysis"),
                    "name": "Paired AP uncertainty analysis",
                    "path": analysis_sources["paired_ap_uncertainty"]["path"],
                    "limitations": ["Resamples one selected validation cohort; not independent training runs or independent generalization."],
                },
                {
                    "evidence_classification": classify_evidence("derived_analysis"),
                    "name": "Temporal stability analysis",
                    "path": analysis_sources["temporal_stability"]["path"],
                    "limitations": ["Descriptive validation segments; temporal differences do not alone prove drift."],
                },
            ],
            "synthetic_evidence": [
                {
                    "evidence_classification": classify_evidence(None, is_synthetic=True),
                    "path": "tests/",
                    "meaning": "Test fixtures exercise software behavior only and provide no empirical model evidence.",
                }
            ],
            "missing_or_unverified_evidence": [
                {"claim": "Original training runs for XGBoost, Logistic Regression, and LightGBM", "classification": "UNVERIFIED", "reason": "Only artifact-import records were recovered; the import records have no training metrics."},
                {"claim": "Historical LightGBM validation AP associated with its canonical binary", "classification": "UNVERIFIED", "reason": "The root-level and canonical binary differ and no recovered training record links the historical metric to the canonical bytes."},
                {"claim": "Fresh independent evaluation cohort with mature labels", "classification": "MISSING", "reason": "No qualifying, unseen confirmation cohort is identified in inspected repository evidence."},
                {"claim": "Verified Git revision for existing training runs", "classification": "UNVERIFIED", "reason": "Current source MLflow records do not provide both commit and branch tags; metadata fields are not independent tag evidence."},
                {"claim": "Operational acceptance objective and numerical cutoffs", "classification": "MISSING", "reason": "Policy v2 thresholds remain null and no approved operational constraints were located."},
            ],
        },
        "historical_evaluation_independence": {
            "validation_split": evaluation.get("evaluation_split"),
            "validation_disclosure": evaluation.get("holdout_disclosure"),
            "interpretation": "Existing validation results support descriptive exploratory comparisons of the saved canonical artifacts. They are conditional on a cohort used for model/checkpoint selection and repeated exploration.",
            "previous_test_use": "The test split was examined in prior project work. It is not a fresh blind holdout and must not be used to calibrate thresholds or claim independent confirmation.",
            "repeated_comparison_risk": "Repeated candidate comparisons and temporal/operating-point exploration can increase selection bias; the saved bootstrap intervals are conditional on the same cohort and do not remove that bias.",
            "model_assessments": readiness,
        },
        "operational_requirements_register": operational_register,
        "independent_evaluation_design": evaluation_design,
        "evidence_acquisition_plan": acquisition_plan,
        "threshold_readiness": {
            "policy_path": "configs/validation_policy_v2.json",
            "effective_status": policy.get("effective_status"),
            "all_numeric_thresholds_remain_undefined": all(
                entry.get("value") is None
                for entry in policy["quality_thresholds"].values()
            ),
            "models": readiness,
            "decision": "NO_THRESHOLD_DEFINITION_OR_PRODUCTION_APPROVAL",
        },
        "known_limitations": [
            "The validation common cohort contains 56 fraud observations; uncertainty and subgroup estimates are fragile.",
            "Temporal model targets are generated from overlapping length-10 windows and do not represent customer/account histories.",
            "No customer, account, merchant, or device identifiers are available for grouped leakage analysis or entity-level resampling.",
            "The Autoencoder score is reconstruction error (anomaly score), not a calibrated fraud probability; reconstruction MSE and AP have different meanings.",
            "Imported model provenance is incomplete, and LightGBM historical metric lineage is unresolved.",
            "Latency, throughput, memory, transaction volume, alert capacity, serving costs, monitoring, and rollback behavior have not been measured or specified.",
            "Previously examined test results cannot serve as independent confirmation.",
        ],
        "status": "DESIGN_COMPLETE_INDEPENDENT_EVIDENCE_NOT_YET_ACQUIRED",
    }


def _operational_register() -> dict[str, Any]:
    rows = [
        ("OPS-01", "What operational outcome is primary: fraud capture, reduced loss, review prioritization, or another objective?", "A threshold and acceptance rule must optimize an explicitly selected outcome.", "Approved business objective from fraud/product stakeholders.", True, True, "Fraud operations / product owner"),
        ("OPS-02", "What missed-fraud risk or recall constraint is acceptable?", "Defines the tolerated false-negative burden.", "Risk appetite and documented fraud-loss policy.", True, True, "Fraud risk owner"),
        ("OPS-03", "What false-positive or precision constraint is acceptable?", "Controls legitimate transactions routed for review or friction.", "Approved review burden and customer-impact constraints.", True, True, "Fraud operations / customer experience owner"),
        ("OPS-04", "What review capacity and alert-volume limits apply?", "A model can exceed operational capacity even with good ranking metrics.", "Queue staffing/capacity and transaction-volume evidence.", True, True, "Fraud operations owner"),
        ("OPS-05", "What inference latency and availability targets apply?", "Determines whether batch or inline inference is feasible.", "Service-level requirements and controlled latency benchmarks.", False, True, "Platform / service owner"),
        ("OPS-06", "What transaction volume and peak patterns must be supported?", "Affects capacity, latency, and cost requirements.", "Documented expected and peak traffic profile.", False, True, "Data/platform owner"),
        ("OPS-07", "How often may the model be updated, and what triggers an update?", "Defines model lifecycle and evidence cadence.", "Approved change/update policy.", False, True, "Model risk / product owner"),
        ("OPS-08", "What label-maturity delay and acceptable data delay apply?", "Prevents evaluation against incomplete labels and defines evaluation timing.", "Label generation and adjudication process documentation.", True, True, "Fraud data / label operations owner"),
        ("OPS-09", "What production monitoring and alert-quality checks are required?", "Defines detection of data, score, and outcome degradation.", "Monitoring objective, data access, ownership, and response plan.", False, True, "Model operations owner"),
        ("OPS-10", "What failure, fallback, and rollback behavior is required?", "Controls customer and fraud risk during outages or regressions.", "Approved operational continuity and rollback requirements.", False, True, "Service owner / fraud operations"),
        ("OPS-11", "Which security, privacy, retention, and audit controls apply?", "Required to authorize use of transaction features and outcomes.", "Security/privacy review and applicable organizational policy.", False, True, "Security / privacy / compliance roles"),
    ]
    questions = [
        {
            "requirement_id": item[0],
            "question": item[1],
            "why_it_matters": item[2],
            "evidence_or_decision_needed": item[3],
            "blocks_numeric_threshold_definition": item[4],
            "blocks_production_approval": item[5],
            "decision_owner_role": item[6],
            "status": "UNKNOWN_NOT_DOCUMENTED",
            "repository_evidence": None,
        }
        for item in rows
    ]
    return {
        "schema_version": "1.0.0",
        "documented_operational_requirements": [],
        "documented_context": [
            {
                "fact": "No production deployment or inference service is documented.",
                "source": "README.md: Current Project Status",
                "evidence_classification": "DOCUMENTATION_ONLY",
            },
            {
                "fact": "The repository contains an offline shared inference implementation; latency, throughput, memory, and serving behavior have not been measured.",
                "source": "src/inference.py",
                "evidence_classification": "DOCUMENTATION_ONLY",
            },
        ],
        "measured_operational_evidence": [],
        "decision_questions": questions,
        "unknown_requirement_ids": [row["requirement_id"] for row in questions],
    }


def _evaluation_design() -> dict[str, Any]:
    return {
        "status": "DESIGN_ONLY_NO_QUALIFYING_COHORT_CONFIRMED",
        "population_requirements": {
            "chronology": "Use a later, prespecified chronological interval relative to model freeze; do not choose dates or boundaries until an eligible source and label-maturity process are confirmed.",
            "prediction_time_features": "Require proof that each feature and transformation is available at the actual scoring time; prohibit post-outcome or adjudication leakage.",
            "label_maturity": "Define a label-maturity window and censor/incomplete-label policy before cohort extraction; unresolved labels must not be treated as legitimate.",
            "duplicates_and_overlap": "Document transaction identity/deduplication where available. Ensure calibration and confirmation cohorts are disjoint in target observations and temporal windows; length-10 sequences must not cross cohort boundaries.",
            "provenance": "Record source system, extraction query/version, timestamps, dataset content hash, label policy/version, and custody/access history.",
            "representativeness": "Compare the target population and fraud prevalence to the intended operating population using documented covariates, without post-hoc cohort selection.",
            "quality_and_drift": "Predefine missingness, schema, label delay, temporal drift and exclusion reporting; retain chronological ordering.",
        },
        "model_freeze": [
            "Exact canonical model artifact bytes and SHA-256.",
            "Metadata, lineage class, and source run or import record IDs.",
            "Ordered 32-feature contract and feature availability rules.",
            "Preprocessing/scaler bytes and transformation behavior.",
            "Shared inference source revision/hash, including temporal sequence length and row alignment.",
            "Evaluation source revision/hash, metric names/definitions/library versions, cohort rules, and uncertainty method.",
            "Acceptance-policy version and rationale; freeze any threshold only after operational decisions and a separate calibration procedure.",
            "Candidate set, comparison plan, exclusion rules, and decision procedure before accessing confirmation labels.",
        ],
        "protocol": {
            "candidate_identification": "Choose and freeze the candidate set using evidence permitted for development; do not select candidates on confirmation outcomes.",
            "threshold_calibration": "If an operational decision requires a threshold, calibrate it on a designated calibration cohort after objective/capacity constraints are approved, then freeze threshold and policy before confirmation.",
            "independent_confirmation": "Evaluate the frozen candidate and frozen policy once on a separate, later or otherwise independently governed cohort that was not used for fitting, checkpoint/model selection, threshold tuning, or candidate choice.",
            "metrics": "Report AP (sklearn average_precision_score) and ROC-AUC as ranking measures, plus policy-relevant threshold measures only at a threshold frozen before confirmation. Report denominators, prevalence, confusion counts, and missing-label handling.",
            "score_semantics": "Report supervised fraud probabilities separately from Autoencoder reconstruction-error anomaly scores; do not call anomaly scores probabilities or compare calibration without a separate calibration study.",
            "temporal_alignment": "For LSTM/GRU, independently form length-10 windows within each cohort; assign scores to the final row only and omit the first nine rows in each cohort. No window may cross train/calibration/confirmation boundaries.",
            "uncertainty": "Prespecify the resampling unit and temporal dependence assumptions. If transaction dependence is plausible, use justified temporal blocks/sensitivity and report event counts; do not treat row bootstrap as resolving temporal or selection bias.",
            "multiple_comparisons": "Prespecify candidate comparisons and distinguish exploratory ranking from confirmatory claims; account for the planned family of comparisons or limit confirmatory claims to a prespecified primary comparison.",
            "missing_labels": "Specify the label-maturity cutoff and report excluded/unresolved rows. Do not impute unresolved outcomes as non-fraud.",
            "reproducibility": "Persist cohort definition, row/class counts, source and label hashes, artifact/scaler/metadata/source hashes, Git revision and dirty status, software versions, seeds, metrics, and protocol/policy versions.",
        },
        "limitations": [
            "No future observation period or new mature-label dataset has been verified; no boundary, sample size, or date is proposed.",
            "The previously examined test split is not eligible as a fresh independent confirmation set.",
            "No customer/account identifiers are available, and temporal dependence structure may not be fully identified.",
        ],
    }


def _acquisition_plan() -> list[dict[str, Any]]:
    entries = [
        (1, "Operational objective and constraints", "No approved objective, missed-fraud limit, false-positive/review constraint, or alert capacity is documented.", "Fraud operations, risk, product, and compliance decision roles.", "Signed/versioned objective and constraints with rationale and owner.", "Threshold definition and production approval.", True, False, False, True),
        (2, "Independent evaluation population and label maturity", "No qualifying unseen cohort and mature-label policy are evidenced; existing validation was selected on and test was previously examined.", "Data custodian and fraud-label operations.", "Documented population, later chronological window, source provenance, label maturity, and disjointness from development/calibration.", "Independent confirmation and production approval.", True, True, False, True),
        (3, "Candidate and policy freeze", "No approved acceptance threshold or frozen confirmation protocol exists; current policy thresholds are null.", "Model owner, risk owner, and evaluation owner.", "Hashes and versions for selected candidates, metadata, features, scaler, inference, metrics, policy, cohort rules, and decision rules recorded before confirmation access.", "Independent confirmation and production approval.", True, False, False, True),
        (4, "Calibration evidence and procedure", "No objective-backed calibration procedure or calibration cohort is documented.", "Risk/product stakeholders plus evaluation owner; requires a dedicated calibration cohort or approved development procedure.", "Prespecified method, rationale, cohort, versioned threshold, and explicit freeze before independent confirmation.", "Numerical threshold definition and independent confirmation under a threshold.", True, True, True, True),
        (5, "Serving feasibility and operational burden", "Latency, throughput, memory, volume, cost, and human review burden are unmeasured.", "Platform/service owner and fraud operations; future controlled benchmarks.", "Approved service and capacity targets plus measured inference/resource/alert burden for frozen candidates.", "Production approval; not a substitute for quality evidence.", True, False, True, True),
        (6, "Monitoring, failure, rollback, and governance", "No project-specific acceptance evidence for monitoring, failure behavior, rollback, privacy, or audit controls.", "Model operations, security/privacy/compliance, and service owner.", "Approved monitoring and response responsibilities, rollback/fallback procedure, audit trail, and security/privacy review.", "Production approval.", True, False, False, True),
    ]
    result = []
    for priority, title, gap, source, closure, blocker, stakeholder, new_data, experiment, approval in entries:
        result.append({
            "priority": priority,
            "item": title,
            "current_gap": gap,
            "required_source_or_decision": source,
            "acceptance_condition": closure,
            "blocking_decisions": blocker,
            "dependencies": "Operational decisions and evidence availability must be established before downstream confirmation.",
            "requires_stakeholder_input": stakeholder,
            "requires_new_data": new_data,
            "requires_future_controlled_experiment": experiment,
            "resolvable_without_model_training": True,
            "blocks_threshold_definition": priority in {1, 4},
            "blocks_independent_confirmation": priority in {2, 3, 4},
            "blocks_production_approval": approval,
            "status": "NOT_ACQUIRED_OR_RESOLVED",
        })
    return result


def build_from_repository(
    *,
    root: Path = ROOT,
    client: Any | None = None,
    report_id: str | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Read existing reports, model files and MLflow records; never read data splits."""
    if client is None:
        client = MlflowClient()
    paths = {
        "evaluation_report": EVALUATION_PATH,
        "m5_inventory": M5_INVENTORY_PATH,
        "m5_policy_analysis": M5_ANALYSIS_PATH,
        "acceptance_policy": POLICY_PATH,
        "paired_ap_uncertainty": UNCERTAINTY_PATH,
        "temporal_stability": TEMPORAL_PATH,
    }
    documents = {key: _read_json(root / path) for key, path in paths.items()}
    inventory = documents["m5_inventory"]
    evaluation = documents["evaluation_report"]
    if evaluation.get("evaluation_id") != inventory.get("evaluation", {}).get("evaluation_id"):
        raise ValueError("M5 evidence inventory and evaluation report IDs do not match")
    tracking_records, registry = collect_tracking_evidence(inventory, client)
    metadata_by_model: dict[str, dict[str, Any]] = {}
    artifact_hashes: dict[str, str | None] = {}
    metadata_hashes: dict[str, str | None] = {}
    for family in MODEL_FAMILIES:
        model = inventory["models"][family]
        artifact_path = root / model["canonical_artifact"]["path"]
        metadata_path = root / model["metadata"]["path"]
        metadata_by_model[family] = _read_json(metadata_path)
        artifact_hashes[family] = sha256_file(artifact_path) if artifact_path.is_file() else None
        metadata_hashes[family] = sha256_file(metadata_path) if metadata_path.is_file() else None
    source_refs = {
        key: {"path": path.as_posix(), "sha256": sha256_file(root / path)}
        for key, path in paths.items()
    }
    source_refs["project_documentation"] = {
        "path": "README.md",
        "sha256": sha256_file(root / "README.md"),
        "classification": "DOCUMENTATION_ONLY",
    }
    operational_report = (
        Path("reports/validation_analysis/operational_feasibility_v1/")
        / "1d24658eef4f4241b4f4e4c1e3a00578/a3d9952ae0f44206a6b4f1e20c372a5d/operational_feasibility_report.md"
    )
    if (root / operational_report).is_file():
        source_refs["operational_feasibility_report"] = {
            "path": operational_report.as_posix(),
            "sha256": sha256_file(root / operational_report),
            "classification": "DOCUMENTATION_ONLY",
        }
    source_refs["m5_inventory"]["inventory_id"] = inventory.get("inventory_id")
    source_refs["m5_policy_analysis"]["analysis_id"] = documents["m5_policy_analysis"].get("analysis_id")
    source_refs["evaluation_report"]["evaluation_id"] = evaluation.get("evaluation_id")
    source_refs["paired_ap_uncertainty"]["record_type"] = documents["paired_ap_uncertainty"].get("record_type")
    source_refs["paired_ap_uncertainty"]["created_at_utc"] = documents["paired_ap_uncertainty"].get("created_at_utc")
    source_refs["paired_ap_uncertainty"]["analysis_id"] = documents["paired_ap_uncertainty"].get("analysis_id")
    source_refs["temporal_stability"]["record_type"] = documents["temporal_stability"].get("record_type")
    source_refs["temporal_stability"]["created_at_utc"] = documents["temporal_stability"].get("created_at_utc")
    source_refs["temporal_stability"]["analysis_id"] = documents["temporal_stability"].get("analysis_id")
    source_refs["paired_ap_uncertainty"]["limitations"] = documents["paired_ap_uncertainty"].get("limitations")
    source_refs["temporal_stability"]["limitations"] = documents["temporal_stability"].get("limitations")
    source_path = Path(__file__).resolve()
    source_refs["analysis_source"] = {
        "path": source_path.relative_to(root).as_posix(),
        "sha256": sha256_file(source_path),
        "classification": "DOCUMENTATION_ONLY",
    }
    prior_ids: list[str] = []
    output_root = root / DEFAULT_OUTPUT_ROOT
    if output_root.is_dir():
        for previous in sorted(output_root.glob("*/evidence_readiness_report.json")):
            try:
                prior_report = _read_json(previous)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            prior_ids.append(str(prior_report.get("report_id", previous.parent.name)))
    return build_report(
        inventory=inventory,
        evaluation=evaluation,
        policy=documents["acceptance_policy"],
        analysis_sources=source_refs,
        metadata_by_model=metadata_by_model,
        artifact_hashes=artifact_hashes,
        metadata_hashes=metadata_hashes,
        tracking_records=tracking_records,
        registry=registry,
        report_id=report_id or uuid.uuid4().hex,
        created_at_utc=created_at_utc or datetime.now(timezone.utc).isoformat(),
        superseded_prior_report_ids=prior_ids,
    )


def write_report(report: dict[str, Any], output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    """Write one uniquely named report and refuse to overwrite existing output."""
    directory = output_root / report["report_id"]
    directory.mkdir(parents=True, exist_ok=False)
    output = directory / "evidence_readiness_report.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    report = build_from_repository()
    output = write_report(report, args.output_root)
    print(output.as_posix())


if __name__ == "__main__":
    main()
