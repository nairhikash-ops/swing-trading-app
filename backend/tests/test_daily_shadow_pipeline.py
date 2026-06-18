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
    assert mock_run.call_count == 7
    
    calls = mock_run.call_args_list
    # Verify generate_samples_batch was called with execution arguments
    assert "app.scripts.generate_samples_batch" in calls[0][0][0]
    assert "--execute" in calls[0][0][0]
    assert "--limit" in calls[0][0][0]
    assert "500" in calls[0][0][0]
    
    assert "app.scripts.export_ml_dataset" in calls[1][0][0]
    assert "app.scripts.export_ml_dataset_regime" in calls[2][0][0]
    assert "app.scripts.score_latest_regime" in calls[3][0][0]
    assert "app.scripts.track_shadow_shortlist" in calls[4][0][0]
    assert "app.scripts.resolve_shadow_outcomes" in calls[5][0][0]
    assert "app.scripts.report_shadow_performance" in calls[6][0][0]

@patch('app.scripts.daily_shadow_pipeline.subprocess.run')
@patch('app.scripts.daily_shadow_pipeline.get_shadow_db_count')
@patch('app.scripts.daily_shadow_pipeline.get_shadow_db_status_counts')
@patch('os.path.exists')
def test_pipeline_stops_on_subprocess_failure(mock_exists, mock_get_status, mock_get_count, mock_run):
    mock_exists.return_value = True
    mock_get_count.return_value = 0
    mock_get_status.return_value = {"OBSERVING": 0, "RESOLVED": 0}
    
    # Simulate generate_samples_batch failing
    mock_run_result = MagicMock()
    mock_run_result.returncode = 1
    mock_run.return_value = mock_run_result
    
    with pytest.raises(SystemExit) as excinfo:
        run_pipeline()
        
    assert excinfo.value.code == 1
    assert mock_run.call_count == 1 # Only the first module should have been attempted
