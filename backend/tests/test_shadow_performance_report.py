import pytest
from app.scripts.report_shadow_performance import calculate_metrics, get_rank_band, get_prob_band

def test_calculate_metrics():
    records = [
        {"future_observed_outcome": "WIN", "win_probability": 0.55, "days_to_outcome": 3},
        {"future_observed_outcome": "LOSS", "win_probability": 0.45, "days_to_outcome": 1},
        {"future_observed_outcome": "TIMEOUT", "win_probability": 0.35, "days_to_outcome": 20},
        {"future_observed_outcome": "AMBIGUOUS", "win_probability": 0.25, "days_to_outcome": 5},
    ]
    
    metrics = calculate_metrics(records)
    
    assert metrics["row_count"] == 4
    assert metrics["win_count"] == 1
    assert metrics["loss_count"] == 1
    assert metrics["timeout_count"] == 1
    assert metrics["ambiguous_count"] == 1
    
    assert metrics["win_rate"] == 0.25
    assert metrics["loss_rate"] == 0.25
    
    assert metrics["avg_win_probability"] == pytest.approx((0.55 + 0.45 + 0.35 + 0.25) / 4)
    assert metrics["avg_days_to_outcome"] == pytest.approx((3 + 1 + 20 + 5) / 4)
    
    # Valid rows for expectancy = 3 (WIN, LOSS, TIMEOUT)
    # p_win = 1/3, p_loss = 1/3, p_timeout = 1/3
    # expectancy = (1/3 * 7) - (1/3 * 3) = 4/3 = 1.3333
    assert metrics["gross_expectancy"] == 1.3333

def test_calculate_metrics_all_ambiguous():
    records = [
        {"future_observed_outcome": "AMBIGUOUS", "win_probability": 0.50, "days_to_outcome": 1},
    ]
    metrics = calculate_metrics(records)
    assert metrics["gross_expectancy"] == 0.0
    assert metrics["row_count"] == 1

def test_calculate_metrics_empty():
    metrics = calculate_metrics([])
    assert metrics["row_count"] == 0
    assert metrics["gross_expectancy"] == 0.0

def test_get_rank_band():
    assert get_rank_band(1) == "1-4"
    assert get_rank_band(4) == "1-4"
    assert get_rank_band(5) == "5-10"
    assert get_rank_band(10) == "5-10"
    assert get_rank_band(11) == "11-22"
    assert get_rank_band(22) == "11-22"
    assert get_rank_band(23) == "23+"

def test_get_prob_band():
    assert get_prob_band(0.55) == ">= 0.50"
    assert get_prob_band(0.50) == ">= 0.50"
    assert get_prob_band(0.45) == "0.40 to 0.50"
    assert get_prob_band(0.40) == "0.40 to 0.50"
    assert get_prob_band(0.35) == "0.30 to 0.40"
    assert get_prob_band(0.30) == "0.30 to 0.40"
    assert get_prob_band(0.25) == "below 0.30"
