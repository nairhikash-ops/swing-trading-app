import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone

def compute_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["current_close_ratio"] = (1.0 + df["c59_close_rel"]).astype(np.float32)
    df["past_close_ratio"] = (1.0 + df["c39_close_rel"]).astype(np.float32)
    df["stock_20d_return"] = (df["current_close_ratio"] / df["past_close_ratio"] - 1.0).astype(np.float32)

    prev_20_high_cols = [f"c{i:02d}_high_rel" for i in range(39, 59)]
    prev_20_low_cols = [f"c{i:02d}_low_rel" for i in range(39, 59)]

    max_prev_20_high = df[prev_20_high_cols].max(axis=1) + 1.0
    min_prev_20_low = df[prev_20_low_cols].min(axis=1) + 1.0

    df["stock_is_breakout"] = (df["current_close_ratio"] > max_prev_20_high).astype(np.float32)
    df["stock_is_breakdown"] = (df["current_close_ratio"] < min_prev_20_low).astype(np.float32)

    market_df = df.groupby("sample_date").agg(
        market_median_20d_return=("stock_20d_return", "median"),
        market_cross_sectional_volatility=("stock_20d_return", "std"),
        market_breakout_rate=("stock_is_breakout", "mean"),
        market_breakdown_rate=("stock_is_breakdown", "mean")
    ).reset_index()

    market_df["market_breadth_delta"] = (market_df["market_breakout_rate"] - market_df["market_breakdown_rate"]).astype(np.float32)
    market_df["market_cross_sectional_volatility"] = market_df["market_cross_sectional_volatility"].fillna(0.0).astype(np.float32)
    market_df["market_median_20d_return"] = market_df["market_median_20d_return"].astype(np.float32)
    market_df["market_breakout_rate"] = market_df["market_breakout_rate"].astype(np.float32)
    market_df["market_breakdown_rate"] = market_df["market_breakdown_rate"].astype(np.float32)

    df = df.merge(market_df, on="sample_date", how="left")

    df["stock_20d_return_minus_market_median"] = (df["stock_20d_return"] - df["market_median_20d_return"]).astype(np.float32)
    df["stock_is_stronger_than_market"] = (df["stock_20d_return"] > df["market_median_20d_return"]).astype(np.float32)
    df["stock_breakout_while_market_weak"] = ((df["stock_is_breakout"] == 1.0) & (df["market_breadth_delta"] < 0)).astype(np.float32)

    df.drop(columns=["current_close_ratio", "past_close_ratio", "stock_20d_return", "stock_is_breakout", "stock_is_breakdown"], inplace=True)
    return df

def generate_regime_dataset(
    input_path: str = "/app/data/exports/ml_dataset_ohlcv_v1.csv",
    output_path: str = "/app/data/exports/ml_dataset_ohlcv_regime_v1.csv",
    expected_rows: int = 440411,
    skip_row_check: bool = False
):
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input V1 CSV missing: {input_path}")
        
    print(f"Loading V1 dataset from {input_path}...")
    df = pd.read_csv(input_path)
    
    if not skip_row_check and len(df) != expected_rows:
        raise ValueError(f"Input CSV row count {len(df)} does not match expected {expected_rows}")
        
    print(f"Computing regime features for {len(df)} rows...")
    df = compute_regime_features(df)
    
    metadata_cols = ["symbol", "sample_date", "outcome"]
    regime_cols = [
        "market_median_20d_return",
        "market_breakout_rate",
        "market_breakdown_rate",
        "market_breadth_delta",
        "market_cross_sectional_volatility",
        "stock_20d_return_minus_market_median",
        "stock_is_stronger_than_market",
        "stock_breakout_while_market_weak"
    ]
    
    technical_cols = [c for c in df.columns if c not in metadata_cols and c not in regime_cols]
    
    # Validation checks
    if list(df.columns[:3]) != metadata_cols:
        raise ValueError(f"First three columns must be {metadata_cols}")
        
    if len(technical_cols) != 300:
        raise ValueError(f"Expected 300 technical feature columns, found {len(technical_cols)}")
        
    if len(df.columns) != 311:
        raise ValueError(f"Expected 311 total columns, found {len(df.columns)}")
        
    if df[regime_cols].isna().any().any():
        raise ValueError("NaN values found in regime columns.")
        
    if np.isinf(df[regime_cols].select_dtypes(include=np.number)).any().any():
        raise ValueError("Infinite values found in regime columns.")
        
    # Reorder columns just to be absolutely certain (meta, then technical, then regime)
    final_cols = metadata_cols + technical_cols + regime_cols
    df = df[final_cols]
    
    # Check for duplicates using purely symbol and sample_date
    duplicate_count = int(df.duplicated(subset=["symbol", "sample_date"]).sum())
    if not skip_row_check and duplicate_count > 0:
         raise ValueError(f"Found {duplicate_count} duplicate samples in dataset.")
    
    print(f"Writing derived dataset to {output_path}...")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    
    meta_path = output_path.replace(".csv", ".meta.json")
    
    meta = {
        "source_csv": os.path.basename(input_path),
        "output_csv": os.path.basename(output_path),
        "row_count": len(df),
        "metadata_columns": metadata_cols,
        "technical_feature_count": 300,
        "regime_feature_count": 8,
        "total_feature_count": 308,
        "total_column_count": 311,
        "null_count": int(df.isna().sum().sum()),
        "duplicate_count": duplicate_count,
        "regime_feature_names": regime_cols,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": "stock_opportunity_ohlcv_regime_v1",
        "parent_dataset_version": "stock_opportunity_ohlcv_v1"
    }
    
    print(f"Writing metadata to {meta_path}...")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        
    print("Export complete.")

if __name__ == "__main__":
    generate_regime_dataset()
