import asyncio
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from App.api import dependencies
from App.api.dependencies import (
    close_mongo_client,
    get_mongo_client,
    ping_mongo,
)
from App.core.config import settings
from services.documents.main import app as documents_app


@pytest.mark.asyncio
async def test_concurrent_mongo_initialization_no_duplicates(monkeypatch):
    """Verify that multiple concurrent requests share the exact same client

    and no duplicate clients are created.
    """
    close_mongo_client()
    monkeypatch.setattr(settings, "MONGODB_ENABLED", True)

    instantiations = 0

    class MockMotorClient:
        def __init__(self, *args, **kwargs):
            nonlocal instantiations
            instantiations += 1
            self.admin = MagicMock()
            self.admin.command = AsyncMock(return_value={"ok": 1.0})
            self.closed = False

        def close(self):
            self.closed = True

        def __getitem__(self, name):
            return MagicMock()

    monkeypatch.setattr(dependencies, "AsyncIOMotorClient", MockMotorClient)

    # Launch 50 concurrent requests for the client
    tasks = [get_mongo_client() for _ in range(50)]
    clients = await asyncio.gather(*tasks)

    # Exactly one client should have been instantiated
    assert instantiations == 1
    assert len(clients) == 50

    # All 50 references must be the exact same instance
    first_client = clients[0]
    for client in clients:
        assert client is first_client

    # Verify connection closure
    close_mongo_client()
    assert first_client.closed
    assert dependencies._mongo_client is None
    assert dependencies._mongo_lock is None


@pytest.mark.asyncio
async def test_mongo_client_closure_and_reinitialization(monkeypatch):
    """Verify correct connection closure and clean re-initialization."""
    close_mongo_client()
    monkeypatch.setattr(settings, "MONGODB_ENABLED", True)

    mock_client_1 = MagicMock()
    mock_client_1.close = MagicMock()
    mock_client_2 = MagicMock()
    mock_client_2.close = MagicMock()

    call_count = 0

    def mock_factory(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_client_1 if call_count == 1 else mock_client_2

    monkeypatch.setattr(dependencies, "AsyncIOMotorClient", mock_factory)

    c1 = await get_mongo_client()
    assert c1 is mock_client_1

    # Close client
    close_mongo_client()
    mock_client_1.close.assert_called_once()
    assert dependencies._mongo_client is None

    # Re-initialization should create a fresh client
    c2 = await get_mongo_client()
    assert c2 is mock_client_2
    assert c2 is not c1

    close_mongo_client()
    mock_client_2.close.assert_called_once()


@pytest.mark.asyncio
async def test_ping_mongo_handles_connection_errors(monkeypatch):
    """Verify that ping_mongo catches and reports connection errors gracefully."""
    close_mongo_client()
    monkeypatch.setattr(settings, "MONGODB_ENABLED", True)

    mock_client = MagicMock()
    mock_client.admin.command = AsyncMock(side_effect=TimeoutError("Connection timed out"))
    monkeypatch.setattr(dependencies, "AsyncIOMotorClient", lambda *args, **kwargs: mock_client)

    result = await ping_mongo()
    assert result is False

    # Now verify success when ping responds
    mock_client.admin.command = AsyncMock(return_value={"ok": 1})
    result = await ping_mongo()
    assert result is True

    close_mongo_client()


def test_documents_readiness_when_mongo_available(monkeypatch):
    """Verify /health/ready returns 200 when MongoDB is connected."""
    monkeypatch.setattr(settings, "MONGODB_ENABLED", True)
    monkeypatch.setattr("services.documents.main.ping_mongo", AsyncMock(return_value=True))

    with TestClient(documents_app) as client:
        res = client.get("/health/ready")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ready"
        assert body["persistence"] == "mongodb"
        assert body["database"] == "connected"


def test_documents_readiness_when_mongo_unavailable(monkeypatch):
    """Verify /health/ready returns 503 when MongoDB is down or unreachable."""
    monkeypatch.setattr(settings, "MONGODB_ENABLED", True)
    monkeypatch.setattr("services.documents.main.ping_mongo", AsyncMock(return_value=False))

    with TestClient(documents_app) as client:
        res = client.get("/health/ready")
        assert res.status_code == 503
        body = res.json()
        assert body["status"] == "not_ready"
        assert body["persistence"] == "mongodb"
        assert body["database"] == "disconnected"


def test_documents_readiness_recovers_when_mongo_reconnects(monkeypatch):
    """Verify /health/ready transitions from 503 to 200 upon database recovery."""
    monkeypatch.setattr(settings, "MONGODB_ENABLED", True)

    mock_ping = AsyncMock(return_value=False)
    monkeypatch.setattr("services.documents.main.ping_mongo", mock_ping)

    with TestClient(documents_app) as client:
        # Step 1: MongoDB down -> 503
        res1 = client.get("/health/ready")
        assert res1.status_code == 503
        assert res1.json()["status"] == "not_ready"

        # Step 2: MongoDB recovers -> 200
        mock_ping.return_value = True
        res2 = client.get("/health/ready")
        assert res2.status_code == 200
        assert res2.json()["status"] == "ready"
        assert res2.json()["database"] == "connected"


def test_docker_compose_dependencies_and_healthchecks():
    """Verify Docker Compose configuration for startup order and healthchecks."""
    compose_path = Path("docker-compose.yml")
    assert compose_path.exists()

    with compose_path.open("r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    services = compose_data["services"]

    # 1. MongoDB has healthcheck
    assert "mongodb" in services
    assert "healthcheck" in services["mongodb"]

    # 2. Documents depends on MongoDB being healthy
    assert "documents" in services
    assert services["documents"]["depends_on"]["mongodb"]["condition"] == "service_healthy"
    assert "healthcheck" in services["documents"]

    # 3. Extractor has healthcheck
    assert "extractor" in services
    assert "healthcheck" in services["extractor"]

    # 4. Proxy depends on both extractor and documents being healthy
    assert "proxy" in services
    proxy_deps = services["proxy"]["depends_on"]
    assert proxy_deps["extractor"]["condition"] == "service_healthy"
    assert proxy_deps["documents"]["condition"] == "service_healthy"
