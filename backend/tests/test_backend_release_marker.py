from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
DOCKERFILE = ROOT / "backend" / "Dockerfile"
SHA = "a" * 40


def test_dockerfile_has_strict_marker_guard() -> None:
    source = DOCKERFILE.read_text(encoding="utf-8")
    assert "ARG RELEASE_COMMIT" in source
    assert "^[0-9a-f]{40}$" in source
    assert "printf '%s\\n' \"$RELEASE_COMMIT\" > /app/RELEASE_COMMIT" in source
    assert "chown root:root /app/RELEASE_COMMIT" in source
    assert "chmod 0444 /app/RELEASE_COMMIT" in source


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker unavailable")
@pytest.mark.parametrize("value", [None, "ABC", "g" * 40, "a" * 39])
def test_missing_or_malformed_build_arg_fails(value: str | None) -> None:
    tag = f"matsya-marker-invalid-{os.getpid()}"
    command = ["docker", "build", "-f", str(DOCKERFILE), "-t", tag]
    if value is not None:
        command += ["--build-arg", f"RELEASE_COMMIT={value}"]
    command.append(str(ROOT / "backend"))
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    assert result.returncode != 0


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker unavailable")
def test_built_marker_properties() -> None:
    tag = f"matsya-marker-valid-{os.getpid()}"
    build = subprocess.run(
        ["docker", "build", "-f", str(DOCKERFILE), "-t", tag, "--build-arg", f"RELEASE_COMMIT={SHA}", str(ROOT / "backend")],
        capture_output=True, text=True, timeout=300,
    )
    assert build.returncode == 0, build.stderr
    try:
        check = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "sh", tag, "-c",
             f'test "$(readlink -f /app/RELEASE_COMMIT)" = /app/RELEASE_COMMIT; '
             f'test "$(cat /app/RELEASE_COMMIT)" = "{SHA}"; '
             'test "$(stat -c %u:%g:%a /app/RELEASE_COMMIT)" = 0:0:444'],
            capture_output=True, text=True, timeout=60,
        )
        assert check.returncode == 0, check.stderr
    finally:
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, text=True, timeout=60)
