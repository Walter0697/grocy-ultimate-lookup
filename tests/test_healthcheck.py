import asyncio
from pathlib import Path

from app.main import health


def run(coro):
    return asyncio.run(coro)


def test_health_endpoint_reports_ok() -> None:
    assert run(health()) == {"status": "ok"}


def test_dockerfile_defines_healthcheck_against_health_endpoint() -> None:
    dockerfile = Path("Dockerfile").read_text()

    assert "HEALTHCHECK" in dockerfile
    assert "127.0.0.1:9290/health" in dockerfile


def test_compose_lookup_defines_healthcheck_against_health_endpoint() -> None:
    compose = Path("docker-compose.yml").read_text()

    assert "healthcheck:" in compose
    assert "127.0.0.1:9290/health" in compose
