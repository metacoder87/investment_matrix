from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Iterator

import httpx
import pytest


pytestmark = pytest.mark.integration


RUN_INTEGRATION = os.getenv("RUN_DOCKER_INTEGRATION") == "1"
REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = [
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "docker-compose.integration.yml",
]


def _integration_unavailable_reason() -> str | None:
    if not RUN_INTEGRATION:
        return "Set RUN_DOCKER_INTEGRATION=1 to boot the full Docker Compose stack."
    if shutil.which("docker") is None:
        return "Docker is not installed or not on PATH."

    docker_info = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if docker_info.returncode != 0:
        return "Docker is installed but the engine is not running."

    return None


def _compose_cmd(project_name: str, *args: str) -> list[str]:
    cmd = ["docker", "compose"]
    for compose_file in COMPOSE_FILES:
        cmd.extend(["-f", str(compose_file)])
    cmd.extend(["--project-name", project_name, *args])
    return cmd


def _run_compose(project_name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _compose_cmd(project_name, *args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )


def _wait_for_http(url: str, *, expected_status: int = 200, timeout: int = 300) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    with httpx.Client(follow_redirects=False, timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(url)
                if response.status_code == expected_status:
                    return
            except Exception as exc:
                last_error = exc
            time.sleep(2)
    raise AssertionError(f"Timed out waiting for {url}. Last error: {last_error!r}")


@pytest.fixture(scope="module")
def full_stack() -> Iterator[dict[str, str]]:
    unavailable_reason = _integration_unavailable_reason()
    if unavailable_reason:
        pytest.skip(unavailable_reason)

    project_name = f"investmentmatrixit{uuid.uuid4().hex[:8]}"
    try:
        _run_compose(project_name, "up", "-d", "--build")
        _wait_for_http("http://127.0.0.1:8000/api/health")
        _wait_for_http("http://127.0.0.1:3000/")
        yield {
            "api": "http://127.0.0.1:8000/api",
            "frontend": "http://127.0.0.1:3000",
            "project_name": project_name,
        }
    finally:
        subprocess.run(
            _compose_cmd(project_name, "down", "-v", "--remove-orphans"),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


def test_api_and_frontend_health(full_stack: dict[str, str]) -> None:
    with httpx.Client(timeout=10.0) as client:
        api_response = client.get(f"{full_stack['api']}/health")
        frontend_response = client.get(f"{full_stack['frontend']}/")
        proxied_api_response = client.get(f"{full_stack['frontend']}/api/health")

    assert api_response.status_code == 200
    assert api_response.json() == {"status": "ok"}
    assert frontend_response.status_code == 200
    assert "CryptoInsight" in frontend_response.text
    assert proxied_api_response.status_code == 200
    assert proxied_api_response.json() == {"status": "ok"}


def test_auth_cookie_unlocks_protected_frontend_route(full_stack: dict[str, str]) -> None:
    user_email = f"integration-{uuid.uuid4().hex[:8]}@example.com"
    password = "IntegrationPass123!"

    with httpx.Client(base_url=full_stack["frontend"], follow_redirects=False, timeout=10.0) as web_client:
        protected_response = web_client.get("/market")
        assert protected_response.status_code in {302, 307}
        assert "/login" in protected_response.headers["location"]

        register_response = web_client.post(
            f"{full_stack['api']}/auth/register",
            json={
                "email": user_email,
                "password": password,
                "full_name": "Integration User",
            },
        )
        assert register_response.status_code == 200

        login_response = web_client.post(
            f"{full_stack['api']}/auth/token",
            data={
                "username": user_email,
                "password": password,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert login_response.status_code == 200
        assert "auth_token" in web_client.cookies

        me_response = web_client.get(f"{full_stack['api']}/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["email"] == user_email

        market_response = web_client.get("/market")
        assert market_response.status_code == 200
        assert "Market Overview" in market_response.text
