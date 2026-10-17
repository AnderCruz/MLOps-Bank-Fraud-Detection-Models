"""Focused tests for MLflow parameter and artifact tracking helpers."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import ANY, MagicMock, Mock, call, patch

from src import train_models


class MlflowTrackingTests(unittest.TestCase):
    def test_flatten_mlflow_params_serializes_nested_configuration(self) -> None:
        flattened = train_models.flatten_mlflow_params({
            "run": {"seed": 42},
            "features": {"names": ["V1", "Amount"]},
            "models": {"mlp": {"training_rows": None}},
        })

        self.assertEqual(flattened["run.seed"], "42")
        self.assertEqual(flattened["features.names"], '["V1", "Amount"]')
        self.assertEqual(flattened["models.mlp.training_rows"], "None")

    def test_main_uses_one_managed_mlflow_run(self) -> None:
        config = train_models.RunConfig()
        active_run = Mock()
        active_run.info.run_id = "mock-mlflow-run-id"
        run_context = MagicMock()
        run_context.__enter__.return_value = active_run

        with (
            patch.object(train_models.mlflow, "set_experiment") as set_experiment,
            patch.object(train_models.mlflow, "start_run", return_value=run_context) as start_run,
            patch.object(train_models, "_run_training") as run_training,
        ):
            train_models.main(config)

        set_experiment.assert_called_once_with("Bank-Fraud-Detection")
        start_run.assert_called_once_with()
        run_training.assert_called_once_with(config)

    def test_main_propagates_training_failure_through_run_context(self) -> None:
        config = train_models.RunConfig()
        active_run = Mock()
        active_run.info.run_id = "mock-mlflow-run-id"

        class RecordingRunContext:
            exception_type = None

            def __enter__(self):
                return active_run

            def __exit__(self, exception_type, exception, traceback):
                self.exception_type = exception_type
                return False

        run_context = RecordingRunContext()
        with (
            patch.object(train_models.mlflow, "set_experiment"),
            patch.object(train_models.mlflow, "start_run", return_value=run_context),
            patch.object(train_models, "_run_training", side_effect=RuntimeError("synthetic failure")),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                train_models.main(config)

        self.assertIs(run_context.exception_type, RuntimeError)

    def test_main_records_success_and_failure_statuses_in_isolated_store(self) -> None:
        config = train_models.RunConfig()
        previous_tracking_uri = train_models.mlflow.get_tracking_uri()

        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "tracking.db"
            try:
                train_models.mlflow.set_tracking_uri(
                    f"sqlite:///{database_path.as_posix()}"
                )

                with patch.object(train_models, "_run_training"):
                    train_models.main(config)

                with (
                    patch.object(
                        train_models,
                        "_run_training",
                        side_effect=RuntimeError("synthetic training failure"),
                    ),
                    self.assertRaisesRegex(
                        RuntimeError, "synthetic training failure"
                    ),
                ):
                    train_models.main(config)

                client = train_models.mlflow.tracking.MlflowClient()
                experiment = client.get_experiment_by_name("Bank-Fraud-Detection")
                self.assertIsNotNone(experiment)
                runs = client.search_runs([experiment.experiment_id])
                self.assertEqual(len(runs), 2)
                self.assertCountEqual(
                    [run.info.status for run in runs], ["FINISHED", "FAILED"]
                )
            finally:
                train_models.mlflow.set_tracking_uri(previous_tracking_uri)

    def test_provenance_collection_tolerates_unavailable_git_metadata(self) -> None:
        config = train_models.RunConfig()
        selected_models = ["random_forest"]

        with patch.object(train_models, "_git_command", return_value=None):
            provenance = train_models.collect_provenance(
                config, selected_models, "pipeline-run-id"
            )

        self.assertEqual(
            provenance["git"],
            {"commit": None, "branch": None, "dirty": None},
        )
        self.assertEqual(provenance["run"]["selected_models"], selected_models)

    def test_pipeline_logs_required_tags_from_provenance_and_handles_missing_git(
        self,
    ) -> None:
        config = train_models.RunConfig()
        config.run.selected_models = ["random_forest"]
        active_run = Mock()
        active_run.info.run_id = "mock-mlflow-run-id"

        provenance_cases = (
            (
                {
                    "commit": "commit-from-provenance",
                    "branch": "branch-from-provenance",
                },
                "commit-from-provenance",
                "branch-from-provenance",
            ),
            ({"commit": None, "branch": None}, "unknown", "unknown"),
        )

        for git_info, expected_commit, expected_branch in provenance_cases:
            with (
                self.subTest(git_info=git_info),
                TemporaryDirectory() as temporary_directory,
            ):
                stop_before_loading_data = RuntimeError("stop before data loading")
                provenance = {"git": git_info}
                with (
                    patch.object(train_models, "ROOT", Path(temporary_directory)),
                    patch.object(
                        train_models.mlflow,
                        "active_run",
                        return_value=active_run,
                    ),
                    patch.object(train_models.mlflow, "set_tags") as set_tags,
                    patch.object(train_models.mlflow, "log_params") as log_params,
                    patch.object(train_models.mlflow, "log_metric") as log_metric,
                    patch.object(
                        train_models,
                        "collect_provenance",
                        return_value=provenance,
                    )
                    as collect_provenance,
                    patch.object(train_models, "set_seed"),
                    patch.object(
                        train_models,
                        "load_splits",
                        side_effect=stop_before_loading_data,
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "stop before data loading"
                    ):
                        train_models._run_training(config)

                collect_provenance.assert_called_once_with(
                    config, ["random_forest"], ANY
                )
                tags = set_tags.call_args.args[0]
                self.assertEqual(tags["project"], "Bank-Fraud-Detection")
                self.assertEqual(tags["model_count"], "1")
                self.assertEqual(
                    tags["pipeline_run_id"],
                    collect_provenance.call_args.args[2],
                )
                self.assertEqual(tags["git_commit"], expected_commit)
                self.assertEqual(tags["git_branch"], expected_branch)

                parameters = log_params.call_args.args[0]
                self.assertEqual(parameters["run.seed"], "42")
                self.assertEqual(parameters["run.device"], "auto")
                self.assertEqual(parameters["run.selected_models"], '["random_forest"]')
                self.assertEqual(parameters["features.count"], "32")
                self.assertEqual(parameters["training.learning_rate"], "0.001")
                self.assertEqual(
                    parameters["models.random_forest.parameters.n_estimators"],
                    "200",
                )
                log_metric.assert_not_called()

    def test_sklearn_and_pytorch_artifacts_are_logged_under_model_paths(self) -> None:
        config = train_models.RunConfig()
        with TemporaryDirectory() as temporary_directory:
            for model_name, model_filename in (
                ("random_forest", "random_forest.joblib"),
                ("mlp", "mlp_state_dict.pt"),
            ):
                with self.subTest(model_name=model_name):
                    model_dir = Path(temporary_directory) / model_name
                    model_dir.mkdir()
                    model_path = model_dir / model_filename
                    metadata_path = model_dir / f"{model_name}_metadata.json"
                    model_path.write_bytes(b"synthetic weights")
                    metadata_path.write_text("{}", encoding="utf-8")

                    with patch.object(train_models.mlflow, "log_artifact") as log_artifact:
                        train_models.log_model_artifacts(model_name, model_dir, config)

                    self.assertEqual(log_artifact.call_args_list, [
                        call(str(model_path), artifact_path=f"models/{model_name}"),
                        call(str(metadata_path), artifact_path=f"models/{model_name}"),
                    ])


if __name__ == "__main__":
    unittest.main()
