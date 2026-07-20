from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="requires POSIX shell")

ROOT = Path(__file__).parents[2]
WRAPPER = ROOT / "deploy" / "matsya-setup" / "matsya-compose.sh"
SHA = "a" * 40


def run_wrapper(tmp_path: Path, *, data: str | None = "/opt/data", env_file: str | None = None, sha: str | None = SHA, args: list[str] | None = None):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    log = tmp_path / "docker-args"
    (fake_bin / "docker").write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$LOG\"\n", encoding="utf-8")
    (fake_bin / "docker").chmod(stat.S_IRWXU)
    clean = {"PATH": f"{fake_bin}:/bin:/usr/bin", "LOG": str(log)}
    if data is not None:
        clean["MATSYA_DATA_ROOT"] = data
    if env_file is not None:
        clean["MATSYA_ENV_FILE"] = env_file
    if sha is not None:
        clean["RELEASE_COMMIT"] = sha
    result = subprocess.run(["sh", str(WRAPPER), *(args or ["config"])], cwd=ROOT, env=clean, capture_output=True, text=True)
    return result, log


def test_wrapper_requires_env_file_and_validates_sha(tmp_path: Path) -> None:
    result, _ = run_wrapper(tmp_path, env_file=None)
    assert result.returncode != 0
    env_file = tmp_path / "env"
    env_file.write_text("", encoding="utf-8")
    for sha in (None, "", "A" * 40, "a" * 39, "a" * 41, "g" * 40):
        result, _ = run_wrapper(tmp_path, env_file=str(env_file), sha=sha)
        assert result.returncode != 0


@pytest.mark.parametrize("value", ["relative", "./relative", "/", "/tmp/data/", "/tmp/data\nmore", "/tmp/data\rmore"])
def test_data_root_rejects_unsafe_values(tmp_path: Path, value: str) -> None:
    env_file = tmp_path / "env"
    env_file.write_text("", encoding="utf-8")
    result, _ = run_wrapper(tmp_path, data=value, env_file=str(env_file))
    assert result.returncode != 0


@pytest.mark.parametrize("value", ["relative.env", "./relative.env", "/", "/tmp/env/", "/tmp/env\nmore", "/tmp/env\rmore"])
def test_env_file_rejects_unsafe_values(tmp_path: Path, value: str) -> None:
    env_file = tmp_path / "real env"
    env_file.write_text("KEY=value\n", encoding="utf-8")
    result, _ = run_wrapper(tmp_path, env_file=value)
    assert result.returncode != 0


def test_valid_paths_with_spaces_and_arguments_are_preserved(tmp_path: Path) -> None:
    data_root = tmp_path / "persistent data"
    env_file = tmp_path / "matsya env"
    data_root.mkdir()
    env_file.write_text("KEY=value\n", encoding="utf-8")
    result, log = run_wrapper(tmp_path, data=str(data_root), env_file=str(env_file), args=["build", "matsya-api", "--progress", "plain"])
    assert result.returncode == 0, result.stderr
    assert log.read_text(encoding="utf-8").splitlines() == ["compose", "--profile", "manual", "-f", "deploy/matsya-setup/docker-compose.yml", "build", "matsya-api", "--progress", "plain"]


def test_env_file_must_be_regular_non_symlink(tmp_path: Path) -> None:
    directory = tmp_path / "env-dir"
    directory.mkdir()
    result, _ = run_wrapper(tmp_path, env_file=str(directory))
    assert result.returncode != 0
    real = tmp_path / "real-env"
    real.write_text("", encoding="utf-8")
    link = tmp_path / "env-link"
    link.symlink_to(real)
    result, _ = run_wrapper(tmp_path, env_file=str(link))
    assert result.returncode != 0


def test_wrapper_has_no_eval_or_shell_string_execution() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert "eval" not in source
    assert '"$@"' in source
