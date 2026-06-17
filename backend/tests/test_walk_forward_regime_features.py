import pandas as pd
import pytest
import numpy as np

from app.scripts.walk_forward_regime_features import compute_regime_features

def test_compute_regime_features():
    # Setup mock data for two symbols on the same date
    # AAPL breaks out
    # MSFT breaks down
    
    # Entry close ratio handling:
    # c59_close_rel = (c59/c59 - 1) = 0.0 -> current ratio = 1.0
    # For AAPL to break out, max(prev_20_highs) < current
    # So max(prev_high_ratios) < 1.0 -> max(high_rel + 1) < 1.0 -> max(high_rel) < 0.0
    # For MSFT to break down, min(prev_20_lows) > current
    # So min(prev_low_ratios) > 1.0 -> min(low_rel + 1) > 1.0 -> min(low_rel) > 0.0
    
    data = {
        "symbol": ["AAPL", "MSFT"],
        "sample_date": ["2023-01-01", "2023-01-01"],
        "c59_close_rel": [0.0, 0.0],
        # AAPL 20d ago was much lower (c39_close_rel < 0) -> Return positive
        # MSFT 20d ago was much higher (c39_close_rel > 0) -> Return negative
        "c39_close_rel": [-0.20, 0.25],  # ratios: 0.8 and 1.25
    }
    
    for i in range(39, 59):
        # AAPL previous highs all below 0.0
        # MSFT previous lows all above 0.0
        data[f"c{i:02d}_high_rel"] = [-0.10, 0.30] 
        data[f"c{i:02d}_low_rel"] = [-0.30, 0.10]
        
    df = pd.DataFrame(data)
    enriched_df = compute_regime_features(df)
    
    assert "market_median_20d_return" in enriched_df.columns
    assert "stock_is_stronger_than_market" in enriched_df.columns
    
    # AAPL 20d return: 1 / (1 + (-0.2)) - 1 = 1 / 0.8 - 1 = 0.25
    # MSFT 20d return: 1 / (1 + 0.25) - 1 = 1 / 1.25 - 1 = -0.20
    assert pytest.approx(enriched_df.loc[enriched_df["symbol"] == "AAPL", "stock_20d_return_minus_market_median"].iloc[0], 0.01) == 0.25 - 0.025
    
    # AAPL breakout = 1, breakdown = 0
    # MSFT breakout = 0, breakdown = 1
    assert enriched_df["market_breakout_rate"].iloc[0] == 0.5
    assert enriched_df["market_breakdown_rate"].iloc[0] == 0.5
    assert enriched_df["market_breadth_delta"].iloc[0] == 0.0
    
    # AAPL is stronger than market
    assert enriched_df.loc[enriched_df["symbol"] == "AAPL", "stock_is_stronger_than_market"].iloc[0] == 1.0
    # MSFT is weaker than market
    assert enriched_df.loc[enriched_df["symbol"] == "MSFT", "stock_is_stronger_than_market"].iloc[0] == 0.0
    
    # No NaNs in critical regime columns
    assert enriched_df["market_cross_sectional_volatility"].isna().sum() == 0
