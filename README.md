# Bank Fraud Detection

An end-to-end Data Science and Machine Learning project focused on detecting fraudulent credit card transactions in a highly imbalanced dataset.

The project covers exploratory data analysis, feature preparation, traditional machine learning, deep learning, model evaluation, experiment tracking, artifact management, automated testing, and model governance.

> **Project status:** Research and validation. Reported results are preliminary validation results. Independent performance confirmation and production approval have not been established.

## 1. Project Objectives

The main objectives are to:

* Investigate a highly imbalanced credit card transaction dataset.
* Develop and compare traditional machine learning and deep learning models.
* Evaluate models using metrics appropriate for fraud detection.
* Track experiments, model metadata, and artifacts.
* Establish automated validation and testing workflows.
* Document reproducibility limitations, acceptance criteria, and governance requirements.

## 2. Dataset

The project uses the [Credit Card Fraud Detection dataset on Kaggle](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud), originally associated with the ULB Machine Learning Group.

| Property                |                Value |
| ----------------------- | -------------------: |
| Total transactions      |              284,807 |
| Legitimate transactions |              284,315 |
| Fraudulent transactions |                  492 |
| Fraud prevalence        | Approximately 0.173% |
| Target variable         |              `Class` |

The target variable is defined as:

* `Class = 0`: Legitimate transaction
* `Class = 1`: Fraudulent transaction

Most input variables (`V1` to `V28`) are anonymized PCA-transformed features. `Time` and `Amount` provide additional transaction information.

The severe class imbalance makes accuracy alone unsuitable for assessing model performance.

## 3. Data Preparation and Evaluation Design

The modeling feature set contains 32 features:

* `V1` to `V28`
* `Amount`
* `Amount_log`
* `Time`
* `Time_hour`

The project uses a chronological 70/15/15 train-validation-test split.

| Split      | Transactions | Fraudulent Transactions | Fraud Prevalence |
| ---------- | -----------: | ----------------------: | ---------------: |
| Train      |      199,364 |                     384 |          0.1926% |
| Validation |       42,721 |                      56 |          0.1311% |
| Test       |       42,722 |                      52 |          0.1217% |

The validation and test partitions contain relatively few fraudulent transactions. Performance estimates may therefore be sensitive to individual predictions.

**Evaluation limitation:** The test partition has previously been inspected. It must not be presented as an untouched, independent holdout. The results reported below are validation results.

## 4. Models Evaluated

### Traditional Machine Learning

* Logistic Regression
* Random Forest
* XGBoost
* LightGBM

### Deep Learning for Tabular Data

* Multilayer Perceptron (MLP)
* Autoencoder

### Temporal Deep Learning

* Long Short-Term Memory (LSTM)
* Gated Recurrent Unit (GRU)

The eight model approaches above form the reported comparison. A 1D CNN was considered during planning but is not included in these results. Transformer and Graph Neural Network approaches remain potential future extensions.

## 5. Evaluation Metrics

The project emphasizes metrics suitable for highly imbalanced classification.

* **Average Precision (AP):** Summarizes precision-recall performance and is useful when the positive class is rare.
* **Precision:** Measures the proportion of flagged transactions that are fraudulent.
* **Recall:** Measures the proportion of fraudulent transactions detected.
* **F1-score:** Represents the harmonic mean of precision and recall at a specified decision threshold.

Average Precision depends on the prevalence of fraud in the evaluation cohort. It should be interpreted alongside the cohort composition and the number of positive observations.

Precision, recall, and F1-score also depend on the decision threshold. Model selection must account for false positives, missed fraud, and operational requirements rather than relying on a single metric.

## 6. Validation Results

The following Average Precision (AP) results were recorded on the common validation cohort.

| Model               | Validation AP |
| ------------------- | ------------: |
| Random Forest       |      0.857966 |
| MLP                 |      0.855181 |
| LSTM                |      0.853892 |
| GRU                 |      0.852555 |
| XGBoost             |      0.828447 |
| Logistic Regression |      0.784910 |
| LightGBM            |      0.681359 |
| Autoencoder         |     0.292606* |

* The Autoencoder result is based on an anomaly score derived from reconstruction error, not a directly calibrated fraud probability. It is therefore reported separately and should not be interpreted as directly equivalent to a supervised classifier's probability output.

### Interpretation

Random Forest achieved the highest recorded AP among the supervised models, followed closely by MLP, LSTM, and GRU.

These results are preliminary and specific to the evaluated models, checkpoints, and validation cohort. The validation set contains only 56 fraudulent transactions, limiting the strength of conclusions about model ranking and generalization.

The results do not establish that the highest-ranked model is the best operational choice. Further work is required on threshold selection, error analysis, stability, reproducibility, and independent evaluation.

## 7. Model Governance and Acceptance Policy

The project includes a validation policy at:

`configs/validation_policy_v2.json`

The policy is intended to formalize model acceptance criteria and support consistent evaluation decisions.

Current limitations include:

* Numerical acceptance thresholds have not been defined.
* The validation policy remains incomplete.
* Independent confirmation of model performance has not been established.
* The operational costs of false positives and false negatives have not been translated into approved acceptance criteria.
* No model has been approved for production.

Model acceptance should eventually consider detection performance, false-positive volume, stability, reproducibility, operational constraints, and the intended use case.

**A strong validation AP score alone is insufficient for production approval.**

## 8. Experiment Tracking and Artifact Management

The project uses MLflow for experiment tracking and includes functionality for recording model metadata, provenance information, metrics, and artifacts.

The repository also includes workflows for model validation, registry-related checks, and evidence-readiness assessment.

Reproducibility limitations remain:

* The local MLflow database and associated artifacts are not necessarily available in a clean Git checkout.
* The inspected local MLflow registry did not contain the expected registered model versions.
* Exact model artifacts and fitted preprocessing objects may not be available to another user.
* Historical model results must be linked reliably to the corresponding model artifacts and evaluation evidence.
* An implemented tracking workflow does not, by itself, demonstrate that every experiment can be reproduced from a clean environment.

These limitations must be resolved and verified before claiming full end-to-end reproducibility.

## 9. Automated Testing and Validation

The repository includes automated tests covering validation gates, MLflow registry behavior, and evidence-readiness checks.

The following focused test suites have passed:

| Test Suite         | Tests Passed |
| ------------------ | -----------: |
| Validation gates   |           17 |
| MLflow registry    |           11 |
| Evidence readiness |           14 |
| **Total**          |       **42** |

These results establish that the tested behaviors passed their corresponding automated checks. They do not independently establish model quality, production readiness, or complete project reproducibility.

## 10. Repository Structure

The repository organizes the project into configuration, data, notebooks, source code, tests, and evaluation reports.

```text
Bank-Fraud-Detection/
├── configs/
│   └── validation_policy_v2.json
├── data/
│   └── raw/
├── notebooks/
├── reports/
├── src/
├── tests/
├── .gitignore
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

The exact contents of each directory may evolve as the project develops.

## 11. Current Limitations and Next Steps

The project is still in the research and validation stage.

The main priorities are:

1. **Complete the validation policy:** Define numerical acceptance thresholds and document their rationale.
2. **Strengthen independent evaluation:** Establish a suitable independent evaluation cohort and avoid using previously inspected test results as independent confirmation.
3. **Improve artifact provenance:** Ensure that reported metrics can be traced to the exact model artifacts, configurations, and evaluation outputs that produced them.
4. **Verify reproducibility:** Test the documented workflow from a clean checkout with the required dependencies and data access.
5. **Define operational requirements:** Specify acceptable false-positive rates, detection objectives, latency, monitoring, security, privacy, and rollback requirements.
6. **Document model selection:** Combine performance evidence with operational constraints before recommending a model for deployment.

## 12. Final Status

This project demonstrates the implementation and evaluation of multiple machine learning approaches for credit card fraud detection, together with supporting experiment-tracking, testing, and governance workflows.

The current validation results provide a basis for further investigation, not proof of independent generalization or production suitability.

**No model is currently approved for production.**
