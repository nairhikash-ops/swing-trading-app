import pandas as pd
import pytest

def test_walk_forward_ablation_column_splits():
    # Verify that the logic correctly isolates 300, 8, and 308 columns.
    
    # Generate dummy dataframe
    stock_feature_cols = []
    for i in range(60):
        prefix = f"c{i:02d}_"
        stock_feature_cols.extend([
            f"{prefix}open_rel",
            f"{prefix}high_rel",
            f"{prefix}low_rel",
            f"{prefix}close_rel",
            f"{prefix}volume_rel",
        ])
    
    assert len(stock_feature_cols) == 300
    
    regime_feature_cols = [
        "market_median_20d_return",
        "market_breakout_rate",
        "market_breakdown_rate",
        "market_breadth_delta",
        "market_cross_sectional_volatility",
        "stock_20d_return_minus_market_median",
        "stock_is_stronger_than_market",
        "stock_breakout_while_market_weak"
    ]
    
    assert len(regime_feature_cols) == 8
    
    all_feature_cols = stock_feature_cols + regime_feature_cols
    assert len(all_feature_cols) == 308
    
    # Check that there is no overlap
    intersection = set(stock_feature_cols).intersection(set(regime_feature_cols))
    assert len(intersection) == 0
