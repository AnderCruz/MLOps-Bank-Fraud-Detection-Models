"""Register existing model artifacts as traceable MLflow model versions.

This module registers the files already logged by the training pipeline. It
does not package models as pyfunc models or alter their serialization.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient


logger = logging.getLogger(__name__)
REGISTRATION_SUMMARY_ARTIFACT = "registry/registration_summary.json"
REGISTRATION_SUMMARY_SCHEMA_VERSION = 1
REGISTRATION_TIMEOUT_SECONDS = 300
REGISTRATION_POLL_INTERVAL_SECONDS = 1

REGISTERED_MODEL_NAMES = {
    "random_forest": "bank-fraud-random-forest",
    "xgboost": "bank-fraud-xgboost",
    "logistic_regression": "bank-fraud-logistic-regression",
    "lightgbm": "bank-fraud-lightgbm",
    "mlp": "bank-fraud-mlp",
    "autoencoder": "bank-fraud-autoencoder",
    "lstm": "bank-fraud-lstm",
    "gru": "bank-fraud-gru",
}


class ModelRegistryRegistrationError(RuntimeError):
    """Raised after registration attempts when one or more versions failed."""

    def __init__(self, summary: dict[str, Any]) -> None:
        self.summary = summary
        failed_models = [
            record["model_name"]
            for record in summary["models"]
            if record["registration_status"] != "READY"
        ]
        super().__init__(
            "MLflow Registry registration did not reach READY for: "
            + ", ".join(failed_models)
        )


class ModelVersionStateError(RuntimeError):
    """Raised when a created version fails or does not become ready in time."""

    def __init__(self, message: str, model_version: str, status: str) -> None:
        self.model_version = model_version
        self.registration_status = status
        super().__init__(message)


def registered_model_name(model_name: str) -> str:
    """Return the stable Registry name for an internal model family."""
    try:
        return REGISTERED_MODEL_NAMES[model_name]
    except KeyError as error:
        raise ValueError(f"Unknown model family: {model_name}") from error


def _required_active_run_id() -> str:
    active_run = mlflow.active_run()
    if active_run is None:
        raise RuntimeError("Model registration requires an active MLflow run")
    return active_run.info.run_id


def _read_metadata(metadata_path: Path, model_name: str,
                   pipeline_run_id: str) -> dict[str, Any]:
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Model metadata file does not exist: {metadata_path}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Model metadata is unreadable or malformed: {metadata_path}") from error
    if not isinstance(metadata, dict):
        raise ValueError(f"Model metadata must contain a JSON object: {metadata_path}")
    if metadata.get("model_name") != model_name:
        raise ValueError(
            f"Metadata model_name does not match the requested family: {model_name}"
        )
    provenance = metadata.get("provenance")
    run_provenance = provenance.get("run") if isinstance(provenance, dict) else None
    metadata_pipeline_run_id = (
        run_provenance.get("run_id")
        if isinstance(run_provenance, dict)
        else None
    )
    if metadata_pipeline_run_id != pipeline_run_id:
        raise ValueError(
            "Metadata pipeline run ID does not match the active pipeline run"
        )
    return metadata


def _require_logged_artifact(client: MlflowClient, run_id: str,
                             artifact_relative_path: str) -> None:
    parent_path = str(Path(artifact_relative_path).parent).replace("\\", "/")
    expected_name = Path(artifact_relative_path).name
    artifacts = client.list_artifacts(run_id, parent_path)
    if not any(
        artifact.path.rsplit("/", 1)[-1] == expected_name
        and not artifact.is_dir
        for artifact in artifacts
    ):
        raise FileNotFoundError(
            f"Artifact was not found in source MLflow run: {artifact_relative_path}"
        )


def _get_or_create_registered_model(client: MlflowClient,
                                    name: str,
                                    model_name: str) -> None:
    try:
        client.get_registered_model(name)
        return
    except MlflowException as error:
        if error.error_code != "RESOURCE_DOES_NOT_EXIST":
            raise

    try:
        client.create_registered_model(
            name,
            tags={"project": "Bank-Fraud-Detection", "model_name": model_name},
            description=f"Bank-Fraud-Detection model family: {model_name}",
        )
    except MlflowException as error:
        # A concurrent caller may have created the stable family name first.
        if error.error_code != "RESOURCE_ALREADY_EXISTS":
            raise
        client.get_registered_model(name)


def _wait_for_terminal_version(client: MlflowClient,
                               name: str,
                               version: str,
                               timeout_seconds: float,
                               poll_interval_seconds: float):
    if timeout_seconds < 0:
        raise ValueError("Registration timeout must be non-negative")
    if poll_interval_seconds <= 0:
        raise ValueError("Registration poll interval must be positive")
    deadline = time.monotonic() + timeout_seconds
    while True:
        model_version = client.get_model_version(name, str(version))
        if model_version.status == "READY":
            return model_version
        if model_version.status == "FAILED":
            message = model_version.status_message or "No status message supplied"
            raise ModelVersionStateError(
                f"Model version {name}/{version} failed registration: {message}",
                str(version),
                "FAILED",
            )
        if model_version.status != "PENDING_REGISTRATION":
            raise ModelVersionStateError(
                f"Model version {name}/{version} has unexpected status "
                f"{model_version.status!r}",
                str(version),
                str(model_version.status),
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelVersionStateError(
                f"Model version {name}/{version} remained pending beyond "
                f"{timeout_seconds:g} seconds",
                str(version),
                "PENDING_REGISTRATION",
            )
        time.sleep(min(poll_interval_seconds, remaining))


def _version_tags(model_name: str,
                  registered_name: str,
                  metadata: dict[str, Any],
                  source_run_id: str,
                  pipeline_run_id: str,
                  source_artifact_uri: str,
                  metadata_artifact_uri: str,
                  run_tags: dict[str, str]) -> dict[str, str]:
    provenance = metadata.get("provenance", {})
    git_info = provenance.get("git", {})
    validation_metric = metadata.get("validation_metric")
    validation_score = metadata.get("reproduced_validation_metric")
    tags = {
        "project": "Bank-Fraud-Detection",
        "model_name": model_name,
        "registered_model_name": registered_name,
        "pipeline_run_id": pipeline_run_id,
        "source_run_id": source_run_id,
        "source_artifact_uri": source_artifact_uri,
        "metadata_artifact_uri": metadata_artifact_uri,
        "git_commit": str(git_info.get("commit") or "unknown"),
        "git_branch": str(git_info.get("branch") or "unknown"),
        "validation_metric": str(validation_metric or "not_available"),
        "validation_score": (
            str(validation_score) if validation_score is not None else "not_available"
        ),
    }
    # Keep version tags consistent with the source run's M2 provenance tags.
    for key in ("project", "pipeline_run_id", "git_commit", "git_branch"):
        if run_tags.get(key) != tags[key]:
            raise ValueError(f"Registry tag {key!r} conflicts with source run metadata")
    if model_name == "autoencoder":
        reconstruction_mse = metadata.get("configuration", {}).get(
            "best_validation_reconstruction_mse"
        )
        tags["validation_reconstruction_mse"] = (
            str(reconstruction_mse)
            if reconstruction_mse is not None
            else "not_available"
        )
        tags["score_type"] = "reconstruction_error_anomaly_score"
    else:
        tags["score_type"] = "fraud_probability"
    return tags


def register_model_artifact(model_name: str,
                            artifact_path: Path,
                            metadata_path: Path,
                            pipeline_run_id: str,
                            *,
                            client: MlflowClient | None = None,
                            timeout_seconds: float = REGISTRATION_TIMEOUT_SECONDS,
                            poll_interval_seconds: float = REGISTRATION_POLL_INTERVAL_SECONDS,
                            ) -> dict[str, Any]:
    """Register one already-logged file, reusing a matching version on retry."""
    registered_name = registered_model_name(model_name)
    source_run_id = _required_active_run_id()
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Model artifact does not exist: {artifact_path}")
    metadata = _read_metadata(metadata_path, model_name, pipeline_run_id)
    registry_client = client or MlflowClient()
    source_run = registry_client.get_run(source_run_id)
    run_tags = source_run.data.tags
    if run_tags.get("pipeline_run_id") != pipeline_run_id:
        raise ValueError("Active source run does not match the pipeline run ID")

    relative_root = f"models/{model_name}"
    artifact_relative_path = f"{relative_root}/{artifact_path.name}"
    metadata_relative_path = f"{relative_root}/{metadata_path.name}"
    _require_logged_artifact(registry_client, source_run_id, artifact_relative_path)
    _require_logged_artifact(registry_client, source_run_id, metadata_relative_path)
    source_artifact_uri = f"runs:/{source_run_id}/{artifact_relative_path}"
    metadata_artifact_uri = f"runs:/{source_run_id}/{metadata_relative_path}"
    tags = _version_tags(
        model_name, registered_name, metadata, source_run_id, pipeline_run_id,
        source_artifact_uri, metadata_artifact_uri, run_tags,
    )

    _get_or_create_registered_model(registry_client, registered_name, model_name)
    matching_version = next(
        (
            version
            for version in registry_client.search_model_versions(
                filter_string=f"name='{registered_name}'"
            )
            if version.run_id == source_run_id
            and version.tags.get("source_artifact_uri") == source_artifact_uri
        ),
        None,
    )
    if matching_version is None:
        matching_version = registry_client.create_model_version(
            name=registered_name,
            source=source_artifact_uri,
            run_id=source_run_id,
            tags=tags,
            description=(
                f"Artifact registered from pipeline run {pipeline_run_id}; "
                f"validation metric: {tags['validation_metric']}"
            ),
            await_creation_for=0,
        )
    else:
        for key, value in tags.items():
            if matching_version.tags.get(key) != value:
                registry_client.set_model_version_tag(
                    registered_name, str(matching_version.version), key, value
                )

    ready_version = _wait_for_terminal_version(
        registry_client,
        registered_name,
        str(matching_version.version),
        timeout_seconds,
        poll_interval_seconds,
    )
    return {
        "model_name": model_name,
        "registered_model_name": registered_name,
        "model_version": str(ready_version.version),
        "source_run_id": source_run_id,
        "source_artifact_uri": source_artifact_uri,
        "metadata_artifact_uri": metadata_artifact_uri,
        "pipeline_run_id": pipeline_run_id,
        "registration_status": ready_version.status,
        "validation_metric": metadata.get("validation_metric"),
        "validation_score": metadata.get("reproduced_validation_metric"),
    }


def register_logged_models(artifacts: list[dict[str, Any]],
                           pipeline_run_id: str,
                           *,
                           client: MlflowClient | None = None) -> dict[str, Any]:
    """Register each logged model, log a summary, then raise on partial failure."""
    _required_active_run_id()
    model_names = [record["model_name"] for record in artifacts]
    if not artifacts:
        raise ValueError("No logged model artifacts were supplied for registration")
    if len(model_names) != len(set(model_names)):
        raise ValueError("A model family cannot be registered twice in one pipeline run")
    for model_name in model_names:
        registered_model_name(model_name)

    records: list[dict[str, Any]] = []
    for artifact_record in artifacts:
        model_name = artifact_record["model_name"]
        try:
            record = register_model_artifact(
                model_name=model_name,
                artifact_path=Path(artifact_record["artifact_path"]),
                metadata_path=Path(artifact_record["metadata_path"]),
                pipeline_run_id=pipeline_run_id,
                client=client,
            )
        except Exception as error:
            registered_name = registered_model_name(model_name)
            source_run_id = _required_active_run_id()
            registration_status = getattr(error, "registration_status", "FAILED")
            artifact_path = Path(artifact_record["artifact_path"])
            metadata_path = Path(artifact_record["metadata_path"])
            artifact_uri = (
                f"runs:/{source_run_id}/models/{model_name}/{artifact_path.name}"
            )
            metadata_uri = (
                f"runs:/{source_run_id}/models/{model_name}/{metadata_path.name}"
            )
            try:
                failed_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                failed_metadata = {}
            records.append({
                "model_name": model_name,
                "registered_model_name": registered_name,
                "model_version": getattr(error, "model_version", None),
                "source_run_id": source_run_id,
                "source_artifact_uri": artifact_uri,
                "metadata_artifact_uri": metadata_uri,
                "pipeline_run_id": pipeline_run_id,
                "registration_status": registration_status,
                "validation_metric": failed_metadata.get("validation_metric"),
                "validation_score": failed_metadata.get(
                    "reproduced_validation_metric"
                ),
                "error": f"{type(error).__name__}: {error}",
            })
            logger.exception("Registry registration failed for model %s", model_name)
        else:
            records.append(record)

    failed = any(record["registration_status"] != "READY" for record in records)
    summary = {
        "schema_version": REGISTRATION_SUMMARY_SCHEMA_VERSION,
        "pipeline_run_id": pipeline_run_id,
        "source_run_id": _required_active_run_id(),
        "registration_status": "PARTIAL_FAILURE" if failed else "READY",
        "models": records,
    }
    mlflow.log_dict(summary, REGISTRATION_SUMMARY_ARTIFACT)
    if failed:
        raise ModelRegistryRegistrationError(summary)
    return summary
