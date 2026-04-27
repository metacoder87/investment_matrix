from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Iterator

import pytest
import psycopg2


pytestmark = pytest.mark.integration


RUN_INTEGRATION = os.getenv("RUN_DOCKER_INTEGRATION") == "1"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _skip_reason() -> str | None:
    if not RUN_INTEGRATION:
        return "Set RUN_DOCKER_INTEGRATION=1 to validate migrations against TimescaleDB."
    if shutil.which("docker") is None:
        return "Docker is not installed or not on PATH."
    info = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if info.returncode != 0:
        return "Docker is installed but the engine is not running."
    return None


@pytest.fixture(scope="module")
def clean_timescale_url() -> Iterator[str]:
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)

    container_name = f"investment-matrix-migrations-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "-e",
            "POSTGRES_DB=cryptoinsight",
            "-e",
            "POSTGRES_USER=user",
            "-e",
            "POSTGRES_PASSWORD=pass",
            "-p",
            "127.0.0.1::5432",
            "timescale/timescaledb-ha:pg16",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            ready = subprocess.run(
                [
                    "docker",
                    "exec",
                    container_name,
                    "pg_isready",
                    "-U",
                    "user",
                    "-d",
                    "cryptoinsight",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(2)
        else:
            raise AssertionError("TimescaleDB container did not become ready.")

        port_result = subprocess.run(
            ["docker", "port", container_name, "5432/tcp"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        port = port_result.stdout.strip().rsplit(":", maxsplit=1)[-1]
        database_url = f"postgresql+psycopg2://user:pass@127.0.0.1:{port}/cryptoinsight"

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                conn = psycopg2.connect(
                    dbname="cryptoinsight",
                    user="user",
                    password="pass",
                    host="127.0.0.1",
                    port=port,
                )
                conn.close()
                break
            except psycopg2.OperationalError:
                time.sleep(2)
        else:
            raise AssertionError("TimescaleDB host port did not accept connections.")

        yield database_url
    finally:
        subprocess.run(
            ["docker", "stop", container_name],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


def test_alembic_upgrade_head_on_clean_timescale(clean_timescale_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = clean_timescale_url
    env["ENVIRONMENT"] = "test"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
