from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_container_context_excludes_secrets_and_local_credentials() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".secrets" in dockerignore
    assert ".env" in dockerignore
    assert ".git" in dockerignore


def test_api_container_uses_runtime_lock_and_cloud_run_port() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "requirements.runtime.lock" in dockerfile
    assert "requirements.lock " not in dockerfile
    assert "${PORT:-8080}" in dockerfile
    assert ".secrets" not in dockerfile
