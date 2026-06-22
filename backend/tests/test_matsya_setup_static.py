from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_matsya_api_routes_exist_and_do_not_return_token_fields() -> None:
    api = read("backend/app/matsya/api.py")

    assert '"/health"' in api
    assert '"/dhan/status"' in api
    assert '"/dhan/token"' in api
    assert '"/dhan/status/refresh"' in api
    assert '"/dhan/renew"' in api
    assert "access_token:" in api
    assert "access_token:" not in api.split("class MatsyaDhanStatusResponse", 1)[1].split(
        "class MatsyaDhanTokenRequest", 1
    )[0]
    assert "masked_token" not in api


def test_matsya_token_storage_is_encrypted_and_not_plaintext() -> None:
    schema = read("backend/app/matsya/schema.sql")
    service = read("backend/app/matsya/token_service.py")

    assert "encrypted_access_token TEXT NOT NULL" in schema
    assert "access_token_hash TEXT NOT NULL" in schema
    assert "crypto.encrypt(access_token)" in service
    assert "token_hash(access_token)" in service
    assert '"access_token"' not in service.split("return {", 1)[1]


def test_matsya_setup_compose_is_setup_only() -> None:
    compose = read("deploy/matsya-setup/docker-compose.yml")

    assert "matsya-api" in compose
    assert "matsya-ui" in compose
    assert "app.matsya_api:app" in compose
    assert ":8020" in compose
    assert ":80" in compose
    assert "postgres:" not in compose
    assert "dhan-auth-data" not in compose
    assert "swing-trading-app-dev" not in compose
    assert "5173" not in compose
    assert "8000" not in compose


def test_matsya_frontend_clears_token_and_avoids_browser_storage() -> None:
    source = read("frontend-matsya/src/main.tsx")

    assert "Matsya Dhan Setup" in source
    assert 'type="password"' in source
    assert 'accessToken: ""' in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "Import Instruments" in source
    assert "Fetch OHLCV" in source
    assert "<button disabled>Import Universe</button>" in source


def test_matsya_setup_env_example_has_only_placeholders() -> None:
    env_example = read("deploy/matsya-setup/.env.example")

    assert "change-this-password" in env_example
    assert "replace-with-fernet-key" in env_example
    assert "AAAAC3" not in env_example
    assert "access_token" not in env_example.lower()
