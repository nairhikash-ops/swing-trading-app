import pytest
import os
import json
from unittest.mock import patch, MagicMock
import sqlite3
from app.scripts.daily_shadow_pipeline import run_pipeline, get_shadow_db_count, get_shadow_db_status_counts

@patch('os.path.exists')
@patch('sys.exit')
def test_pipeline_artifact_verification_failure(mock_exit, mock_exists):
    # Simulate missing artifacts
    mock_exists.return_value = False
    mock_exit.side_effect = SystemExit(1)
    
    with pytest.raises(SystemExit):
        run_pipeline()
    
    mock_exit.assert_called_with(1)

@patch('app.scripts.daily_shadow_pipeline.subprocess.run')
@patch('app.scripts.daily_shadow_pipeline.get_shadow_db_count')
@patch('app.scripts.daily_shadow_pipeline.get_shadow_db_status_counts')
@patch('os.path.exists')
@patch('builtins.open')
def test_pipeline_successful_execution(mock_open, mock_exists, mock_get_status, mock_get_count, mock_run):
    # Simulate that all files exist
    mock_exists.return_value = True
    
    # Mock subprocess.run to always succeed
    mock_run_result = MagicMock()
    mock_run_result.returncode = 0
    mock_run.return_value = mock_run_result
    
    # Mock DB counts to simulate insertions
    mock_get_count.side_effect = [100, 105]  # Inserted 5 rows
    mock_get_status.side_effect = [
        {"OBSERVING": 80, "RESOLVED": 20},
        {"OBSERVING": 82, "RESOLVED": 23}   # 3 newly resolved
    ]
    
    # Mock the metadata JSON read
    mock_file = MagicMock()
    mock_file.read.return_value = json.dumps({
        "scored_sample_date": "2026-05-16",
        "ranking_count": 200
    })
    mock_open.return_value.__enter__.return_value = mock_file
    
    run_pipeline()
    
    # Verify scripts were called
    assert mock_run.call_count == 4
    
    calls = mock_run.call_args_list
    assert "app.scripts.score_latest_regime" in calls[0][0][0]
    assert "app.scripts.track_shadow_shortlist" in calls[1][0][0]
    assert "app.scripts.resolve_shadow_outcomes" in calls[2][0][0]
    assert "app.scripts.report_shadow_performance" in calls[3][0][0]
