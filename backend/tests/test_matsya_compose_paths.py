from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
COMPOSE = ROOT / "deploy" / "matsya-setup" / "docker-compose.yml"
SHA = "a" * 40


def compose_config(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    clean = {"PATH": os.environ.get("PATH", "")}
    clean.update(env)
    return subprocess.run(
        ["docker", "compose", "--profile", "manual", "-f", str(COMPOSE), "config"],
        env=clean, capture_output=True, text=True, timeout=60,
    )


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker unavailable")
def test_compose_requires_both_absolute_runtime_inputs(tmp_path: Path) -> None:
    env_file = tmp_path / "matsya.env"
    env_file.write_text("", encoding="utf-8")
    missing_root = compose_config({"RELEASE_COMMIT": SHA, "MATSYA_ENV_FILE": str(env_file)})
    assert missing_root.returncode != 0
    missing_env = compose_config({"RELEASE_COMMIT": SHA, "MATSYA_DATA_ROOT": str(tmp_path)})
    assert missing_env.returncode != 0


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker unavailable")
def test_compose_resolves_all_persistent_paths_and_modes(tmp_path: Path) -> None:
    env_file = tmp_path / "matsya.env"
    env_file.write_text("", encoding="utf-8")
    data_root = tmp_path / "persistent-data"
    result = compose_config({
        "RELEASE_COMMIT": SHA,
        "MATSYA_DATA_ROOT": str(data_root),
        "MATSYA_ENV_FILE": str(env_file),
    })
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "../../data/" not in output
    normalized = output.replace("\\", "/")
    assert normalized.count("persistent-data/v8_demo_trader") == 3
    assert normalized.count("persistent-data/uptrend_sideways_paper_trader") == 3
    assert output.count("target: /app/data/v8_demo_trader") == 3
    assert output.count("target: /app/data/uptrend_sideways_paper_trader") == 3
    assert output.count("read_only: true") == 2
    assert "RELEASE_COMMIT: " + SHA in output
    assert COMPOSE.read_text(encoding="utf-8").count("MATSYA_ENV_FILE:?MATSYA_ENV_FILE must be set") == 6


def test_compose_source_has_no_release_relative_or_local_env_paths() -> None:
    source = COMPOSE.read_text(encoding="utf-8")
    assert "../../data/" not in source
    assert "- .env" not in source
    assert source.count("MATSYA_DATA_ROOT:?MATSYA_DATA_ROOT must be set") == 6
    assert source.count("MATSYA_ENV_FILE:?MATSYA_ENV_FILE must be set") == 6
