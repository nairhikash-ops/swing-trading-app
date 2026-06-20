import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone

DEFAULT_INPUT_PATH = "/app/data/exports/ml_dataset_ohlcv_v3.csv"
DEFAULT_OUTPUT_PATH = "/app/data/exports/ml_dataset_ohlcv_regime_v3.csv"

REGIME_COLS = [
    "market_median_20d_return",
    "market_breakout_rate",
    "market_breakdown_rate",
    "market_breadth_delta",
    "market_cross_sectional_volatility",
    "stock_20d_return_minus_market_median",
    "stock_is_stronger_than_market",
    "stock_breakout_while_market_weak"
]

def compute_regime_features_v3(df: pd.DataFrame) -> pd.DataFrame:
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

def generate_regime_dataset_v3(
    input_path: str = DEFAULT_INPUT_PATH,
    output_path: str = DEFAULT_OUTPUT_PATH,
):
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input V3 CSV missing: {input_path}")
        
    df = pd.read_csv(input_path)
    
    metadata_cols = ["symbol", "sample_date", "outcome"]
    if list(df.columns[:3]) != metadata_cols:
        raise ValueError(f"First three columns must be {metadata_cols}")

    existing_regime_cols = [c for c in REGIME_COLS if c in df.columns]
    if existing_regime_cols:
        raise ValueError(f"Input CSV already contains regime columns: {existing_regime_cols}")
        
    initial_cols = len(df.columns)
    if initial_cols != 603:
        raise ValueError(f"Expected 603 input columns, found {initial_cols}")
        
    technical_cols = [c for c in df.columns if c not in metadata_cols]
    if len(technical_cols) != 600:
        raise ValueError(f"Expected 600 technical feature columns, found {len(technical_cols)}")
        
    df = compute_regime_features_v3(df)
    
    regime_cols = REGIME_COLS
    
    if df[regime_cols].isna().any().any():
        raise ValueError("NaN values found in regime columns.")
        
    if np.isinf(df[regime_cols].select_dtypes(include=np.number)).any().any():
        raise ValueError("Infinite values found in regime columns.")
        
    final_cols = metadata_cols + technical_cols + regime_cols
    df = df[final_cols]
    
    if list(df.columns[:3]) != metadata_cols:
        raise ValueError(f"Final output first three columns must be {metadata_cols}")
    if len(technical_cols) != 600:
        raise ValueError(f"Final technical feature count is not 600, got {len(technical_cols)}")
    if len(regime_cols) != 8:
        raise ValueError(f"Final regime feature count is not 8, got {len(regime_cols)}")
    if len(technical_cols) + len(regime_cols) != 608:
        raise ValueError(f"Final total feature count is not 608, got {len(technical_cols) + len(regime_cols)}")
    if len(df.columns) != 611:
        raise ValueError(f"Final total column count is not 611, got {len(df.columns)}")
    if list(df.columns[-8:]) != regime_cols:
        raise ValueError(f"Final output last 8 columns must be {regime_cols}")
    
    duplicate_count = int(df.duplicated(subset=["symbol", "sample_date"]).sum())
    if duplicate_count > 0:
         raise ValueError(f"Found {duplicate_count} duplicate samples in dataset.")
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temp_output_path = output_path + ".tmp"
    
    try:
        df.to_csv(temp_output_path, index=False)
        os.replace(temp_output_path, output_path)
    except Exception as e:
        if os.path.exists(temp_output_path):
            os.remove(temp_output_path)
        raise e
    
    meta_path = output_path.replace(".csv", ".meta.json")
    temp_meta_path = meta_path + ".tmp"
    
    meta = {
        "source_csv": os.path.basename(input_path),
        "output_csv": os.path.basename(output_path),
        "row_count": len(df),
        "metadata_columns": metadata_cols,
        "technical_feature_count": 600,
        "regime_feature_count": 8,
        "total_feature_count": 608,
        "total_column_count": 611,
        "null_count": int(df.isna().sum().sum()),
        "duplicate_count": duplicate_count,
        "regime_feature_names": regime_cols,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": "stock_opportunity_ohlcv_regime_v3",
        "parent_dataset_version": "stock_opportunity_ohlcv_v3"
    }
    
    try:
        with open(temp_meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        os.replace(temp_meta_path, meta_path)
    except Exception as e:
        if os.path.exists(temp_meta_path):
            os.remove(temp_meta_path)
        raise e
        
    return meta

if __name__ == "__main__":
    generate_regime_dataset_v3()
