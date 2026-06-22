from __future__ import annotations

import re
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_matsya_renewal_worker_exists_and_is_safe() -> None:
    worker = read("backend/app/matsya/renewal_worker.py")
    
    assert "class MatsyaRenewalWorker:" in worker
    
    # Secret printing patterns
    assert "print(os.environ" not in worker
    assert "print(settings.database_url" not in worker
    assert "print(access_token" not in worker
    assert not re.search(r"logger\..*access_token", worker)
    assert "cat .env" not in worker


def test_matsya_setup_compose_has_worker_service() -> None:
    compose = read("deploy/matsya-setup/docker-compose.yml")
    
    assert "matsya-renewal-worker:" in compose
    
    # Verify worker service config
    worker_block = compose.split("matsya-renewal-worker:")[1].split("networks:", 1)[1].split("matsya-db:", 1)[0]
    if "networks:" in compose.split("matsya-renewal-worker:")[1].split("matsya-db")[0]:
        worker_network_block = compose.split("matsya-renewal-worker:")[1]
        assert "env_file:\n      - .env" in worker_network_block or "env_file:\r\n      - .env" in worker_network_block
        assert "- matsya-db" in worker_network_block
    
    # Extract the block for the worker service
    # Just roughly checking for "ports" inside the worker section
    worker_section = compose.split("matsya-renewal-worker:")[1].split("matsya-db:")[0] # goes up to global networks definition
    assert "ports:" not in worker_section

    # No new postgres service
    assert compose.count("postgres:") == 0


def test_env_example_includes_renewal_keys() -> None:
    env_example = read("deploy/matsya-setup/.env.example")
    
    assert "MATSYA_RENEWAL_WORKER_ENABLED=true" in env_example
    assert "MATSYA_RENEWAL_CHECK_INTERVAL_SECONDS=900" in env_example
    assert "MATSYA_RENEW_BEFORE_MINUTES=180" in env_example


def test_old_app_compose_not_touched() -> None:
    old_compose = read("docker-compose.yml")
    
    assert "matsya-renewal-worker" not in old_compose
    assert "matsya-setup" not in old_compose
