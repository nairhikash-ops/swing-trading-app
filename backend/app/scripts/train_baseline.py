import os

import joblib
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def encode_label(outcome: str) -> int:
    """Encode outcome to binary classification target."""
    if outcome == "WIN":
        return 1
    elif outcome in ("LOSS", "TIMEOUT"):
        return 0
    raise ValueError(f"Unknown outcome: {outcome}")


def run_training_experiment(
    input_csv_path: str = "/app/data/exports/ml_dataset_ohlcv_v1.csv",
    report_path: str = "/app/data/exports/baseline_report.txt",
    model_path: str = "/app/data/models/experiments/baseline_logistic_ohlcv_v1.joblib"
):
    if not os.path.exists(input_csv_path):
        raise FileNotFoundError(f"Dataset not found at {input_csv_path}")

    print("Loading dataset...")
    df = pd.read_csv(input_csv_path)

    # Validate columns
    metadata_cols = {"symbol", "sample_date", "outcome"}
    expected_cols = set(df.columns)

    feature_cols = []
    for i in range(60):
        prefix = f"c{i:02d}_"
        feature_cols.extend([
            f"{prefix}open_rel",
            f"{prefix}high_rel",
            f"{prefix}low_rel",
            f"{prefix}close_rel",
            f"{prefix}volume_rel",
        ])

    missing_metadata = metadata_cols - expected_cols
    if missing_metadata:
        raise ValueError(f"Missing metadata columns: {missing_metadata}")

    actual_feature_cols = [c for c in df.columns if c not in metadata_cols]
    if len(actual_feature_cols) != 300:
        raise ValueError(f"Expected exactly 300 feature columns, got {len(actual_feature_cols)}")

    if set(actual_feature_cols) != set(feature_cols):
        raise ValueError("Feature columns do not exactly match the expected c00-c59 OHLCV set.")

    # Sort by sample_date
    df = df.sort_values("sample_date").reset_index(drop=True)

    # Encode labels
    df["target"] = df["outcome"].apply(encode_label)

    # Train/test split (chronological)
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    X_train = train_df[feature_cols]
    y_train = train_df["target"]
    X_test = test_df[feature_cols]
    y_test = test_df["target"]

    # Baseline Dummy
    dummy = DummyClassifier(strategy="most_frequent")
    dummy.fit(X_train, y_train)
    dummy_acc = accuracy_score(y_test, dummy.predict(X_test))

    # Logistic Regression
    lr = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(max_iter=1000, random_state=42))
    ])
    lr.fit(X_train, y_train)

    y_pred = lr.predict(X_test)
    y_prob = lr.predict_proba(X_test)[:, 1]

    # Metrics
    lr_acc = accuracy_score(y_test, y_pred)
    lr_bal_acc = balanced_accuracy_score(y_test, y_pred)

    # confusion_matrix with labels=[0, 1] returns a 2x2 matrix
    # [TN, FP]
    # [FN, TP]
    cm = confusion_matrix(y_test, y_pred, labels=[0, 1])
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)

    # Top-decile WIN rate
    test_df = test_df.copy()
    test_df["prob"] = y_prob
    test_df_sorted = test_df.sort_values("prob", ascending=False)
    top_10_percent_idx = max(1, int(len(test_df_sorted) * 0.1))
    top_decile = test_df_sorted.iloc[:top_10_percent_idx]
    top_decile_win_rate = top_decile["target"].mean()

    overall_win_rate = test_df["target"].mean()

    report_lines = [
        "=== BASELINE TRAINING EXPERIMENT ===",
        "Artifact status: EXPERIMENTAL ONLY - not for live trading or production scoring",
        f"Input CSV:            {input_csv_path}",
        f"Input row count:      {len(df)}",
        f"Feature column count: {len(feature_cols)}",
        f"Total column count:   {len(df.columns) - 1}",  # minus our temp target col
        f"Train row count:      {len(train_df)}",
        f"Test row count:       {len(test_df)}",
        "",
        "Label counts overall:",
        str(df["outcome"].value_counts().to_dict()),
        "",
        "Label counts train:",
        str(train_df["outcome"].value_counts().to_dict()),
        "",
        "Label counts test:",
        str(test_df["outcome"].value_counts().to_dict()),
        "",
        "=== METRICS ===",
        f"Dummy Baseline Acc:   {dummy_acc:.4f}",
        f"Logistic Reg Acc:     {lr_acc:.4f}",
        f"Logistic Bal Acc:     {lr_bal_acc:.4f}",
        f"WIN Precision:        {precision:.4f}",
        f"WIN Recall:           {recall:.4f}",
        f"Overall test WIN rate:{overall_win_rate:.4f}",
        f"Top-decile WIN rate:  {top_decile_win_rate:.4f}",
        "",
        "Confusion Matrix (Test):",
        f"TN: {cm[0][0]}  FP: {cm[0][1]}",
        f"FN: {cm[1][0]}  TP: {cm[1][1]}",
    ]

    report_text = "\n".join(report_lines) + "\n"
    print(report_text)

    # Save report
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    # Save model
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    joblib.dump(lr, model_path)

    print(f"Report saved to: {report_path}")
    print(f"Experimental model saved to: {model_path}")


if __name__ == "__main__":
    run_training_experiment()
