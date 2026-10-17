# Operational Feasibility Analysis

Analysis ID: `a3d9952ae0f44206a6b4f1e20c372a5d`  
Evaluation ID: `1d24658eef4f4241b4f4e4c1e3a00578`  
Common cohort: 42,712 validation observations; 56 fraud cases, 42656 legitimate cases.

> Validation findings are conditional on the existing cohort. Validation was used for model/checkpoint selection. The test split was examined previously and is not an untouched or blind holdout. No production threshold is selected.

## Executive summary

Random Forest and MLP have close aggregate validation AP (0.857966 versus 0.855181). MLP has higher aggregate ROC-AUC (0.982751 versus 0.960911). Paired AP uncertainty intervals include zero, and the four-segment AP leaders vary. The evidence does not establish a production winner. Runtime cost and serving performance are unmeasured.

## Aggregate validation results

| Model | AP | ROC-AUC | Score type |
|---|---:|---:|---|
| random_forest | 0.857966 | 0.960911 | fraud_probability |
| mlp | 0.855181 | 0.982751 | fraud_probability |
| lstm | 0.853892 | 0.979813 | fraud_probability |
| gru | 0.852555 | 0.978332 | fraud_probability |

## Descriptive validation operating points

Points use stored PR coordinates on the common cohort. Policy: nearest recall coordinate; ties choose highest precision, then higher recall. Threshold values are not reported. Counts are derived from the curve coordinate and 56 fraud labels; these are observed validation counts, not future expectations.

### Random Forest

| Recall target | Achieved recall | Precision | TP | FN | FP | Total alerts |
|---:|---:|---:|---:|---:|---:|---:|
| 50% | 0.5000 | 1.0000 | 28 | 28 | 0 | 28 |
| 70% | 0.6964 | 1.0000 | 39 | 17 | 0 | 39 |
| 80% | 0.8036 | 0.8491 | 45 | 11 | 8 | 53 |
| 90% | 0.8929 | 0.1969 | 50 | 6 | 204 | 254 |
| 95% | 0.9286 | 0.0185 | 52 | 4 | 2758 | 2810 |

| Increase in target | Additional TP | Change in FN | Additional FP | Additional alerts |
|---|---:|---:|---:|---:|
| 50% → 70% | 11 | -11 | 0 | 11 |
| 70% → 80% | 6 | -6 | 8 | 14 |
| 80% → 90% | 5 | -5 | 196 | 201 |
| 90% → 95% | 2 | -2 | 2554 | 2556 |

### Mlp

| Recall target | Achieved recall | Precision | TP | FN | FP | Total alerts |
|---:|---:|---:|---:|---:|---:|---:|
| 50% | 0.5000 | 1.0000 | 28 | 28 | 0 | 28 |
| 70% | 0.6964 | 1.0000 | 39 | 17 | 0 | 39 |
| 80% | 0.8036 | 0.7377 | 45 | 11 | 16 | 61 |
| 90% | 0.8929 | 0.4065 | 50 | 6 | 73 | 123 |
| 95% | 0.9464 | 0.0100 | 53 | 3 | 5271 | 5324 |

| Increase in target | Additional TP | Change in FN | Additional FP | Additional alerts |
|---|---:|---:|---:|---:|
| 50% → 70% | 11 | -11 | 0 | 11 |
| 70% → 80% | 6 | -6 | 16 | 22 |
| 80% → 90% | 5 | -5 | 57 | 62 |
| 90% → 95% | 3 | -3 | 5198 | 5201 |

At 90% target recall, the nearest stored point is 89.29% for both models: Random Forest has 254 alerts (204 false positives), while MLP has 123 alerts (73 false positives). Near 95%, Random Forest reaches 92.86% recall with 2,810 alerts; MLP reaches 94.64% with 5,324 alerts. These illustrate the observed validation precision/recall trade-off only. More recall can require flagging many more legitimate transactions; no business costs are assumed.

## Temporal stability

| Segment | IDs | Frauds | RF AP / rank | MLP AP / rank | RF ROC-AUC | MLP ROC-AUC |
|---|---|---:|---:|---:|---:|---:|
| 1 | 199373–210050 | 10 | 0.900094 / 4 | 0.900668 / 1 | 0.946822 | 0.986061 |
| 2 | 210051–220728 | 13 | 0.748056 / 1 | 0.723158 / 3 | 0.917343 | 0.947153 |
| 3 | 220729–231406 | 14 | 0.920466 / 1 | 0.909273 / 2 | 0.996731 | 0.987729 |
| 4 | 231407–242084 | 19 | 0.887771 / 6 | 0.914921 / 3 | 0.971702 | 0.999585 |

AP ranks across segments were RF 4, 1, 1, 6 and MLP 1, 3, 2, 3. Segment AP leaders across all models were MLP, RF, RF, and Logistic Regression. This ranking variation is descriptive and does not prove concept drift. The segments contain only 10–19 frauds each.

## Paired AP uncertainty

Difference is AP(Random Forest) − AP(MLP). The saved paired bootstrap uses 1,000 valid replicates per method; every 95% percentile interval includes zero. Intervals are exploratory and conditional on this validation cohort and selected models.

| Method | Block length | Observed difference | 95% percentile interval | Valid/requested |
|---|---:|---:|---|---:|
| paired_row | — | 0.002785 | [-0.024064, 0.032959] | 1000/1000 |
| paired_class_stratified_row | — | 0.002785 | [-0.024218, 0.031605] | 1000/1000 |
| paired_moving_block | 10 | 0.002785 | [-0.025060, 0.031960] | 1000/1000 |
| paired_moving_block | 68 | 0.002785 | [-0.023859, 0.033513] | 1000/1000 |
| paired_moving_block | 372 | 0.002785 | [-0.023862, 0.034673] | 1000/1000 |

## Qualitative deployment comparison

| Dimension | Random Forest | MLP | Evidence status |
|---|---|---|---|
| Inference architecture | 200-tree scikit-learn RandomForestClassifier; class-1 probability is selected from predict_proba using estimator.classes_. | PyTorch feed-forward network 32→64→32→1; logits are converted with sigmoid. | documented implementation |
| Preprocessing | Raw ordered 32 features; no scaler required. | Scaled ordered 32 features using the saved RobustScaler; shared inference verifies scaler hash and does not refit it. | verified by evaluation manifest and inference code |
| Runtime dependencies | Python, NumPy/pandas, scikit-learn, joblib, shared inference code. | Python, NumPy/pandas, PyTorch, scikit-learn metric/provenance stack, saved scaler, strict architecture/state-dictionary compatibility. | requirements and implementation inspected |
| Deployment complexity | Requires compatible joblib/scikit-learn loading and fixed feature schema. Actual operational simplicity is not measured. | Requires matching PyTorch architecture, strict state-dictionary loading, evaluation mode, scaler integrity, and probability conversion. | qualitative inference from implementation |
| Model artifact management | joblib estimator plus metadata; evaluation manifest records artifact and metadata hashes and training lineage. | PyTorch state dictionary plus architecture/config metadata and scaler reference/hash; evaluation manifest records lineage and hashes. | verified from manifest and metadata |
| Explainability and auditability | Tree structure and feature-importance facilities may be inspectable, but no explanation report or audit workflow is established here. | Weights and architecture are recorded; the network is less directly interpretable and no explanation method is established here. | partial/unknown |
| Monitoring and maintenance | Monitor feature schema/distribution, class-1 probability behavior, and estimator/dependency compatibility. Monitoring system is not present in reviewed evidence. | Monitor schema, scaler identity/input drift, probability behavior, and PyTorch/artifact compatibility. Monitoring system is not present in reviewed evidence. | recommended considerations; not implemented evidence |
| Latency and throughput | Not measured. Benchmark with representative rows, batch sizes, concurrency, warm/cold loading, and target hardware. | Not measured. Benchmark the same conditions, including scaler transformation and PyTorch execution. | unknown |
| Memory consumption | Not measured; measure process/model memory at load and peak inference under intended batch/concurrency. | Not measured; measure model, framework, scaler, and peak batch memory. | unknown |
| Serving cost | Unknown; requires target deployment architecture, utilization, resource pricing, and measured workload. | Unknown; requires target deployment architecture, utilization, resource pricing, and measured workload. | unknown |
| Temporal robustness | Across four saved validation segments, AP ranks were 4,1,1,6; AP range 0.748056–0.920466. | Across four saved validation segments, AP ranks were 1,3,2,3; AP range 0.723158–0.914921. | descriptive validation only; segment counts are small |
| Performance uncertainty | RF−MLP observed AP difference +0.002785; all saved 95% paired intervals include zero. | Same paired comparison; uncertainty is conditional on validation cohort and selected models. | exploratory paired bootstrap |

## LSTM and GRU context

Both use scaled features and length-10 globally chronological windows, with each prediction assigned to the final row. The first nine rows have no prediction. The project has no customer, account, merchant, or device identifiers; adjacent transactions may belong to unrelated entities. These models therefore do not establish entity-level histories.

## Remaining limitations and next investigation

- Latency, throughput, memory, and serving cost have not been measured; tree models must not be assumed faster or cheaper without benchmarking in the intended environment.
- Explainability tooling and monitoring workflows are not established by the reviewed artifacts.
- Original provenance remains incomplete for imported XGBoost, Logistic Regression, and LightGBM artifacts; LightGBM historical AP is not conclusively linked to its imported binary.
- Validation was used for model/checkpoint selection, and the test split was examined previously.

Next, define alert-capacity and infrastructure constraints and benchmark both candidates under the intended workload, including scaler cost, model loading, batch/concurrency, memory, and serving cost. Keep the threshold decision separate and require a genuinely independent evaluation cohort for generalization claims. No model or threshold is selected.
