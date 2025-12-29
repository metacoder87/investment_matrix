import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure the repo root is on sys.path when pytest collects from `tests/`.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings  # noqa: E402
from app.main import create_app, get_coingecko_connector, get_db  # noqa: E402
from database import Base  # noqa: E402


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_engine(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", TEST_DATABASE_URL)
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(test_engine):
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db_session, request):
    """
    Creates a FastAPI TestClient with a test database and optionally mocked connectors.
    """

    def override_get_db():
        yield db_session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    if hasattr(request, "param"):
        for mock_name, mock_fixture in request.param.items():
            if mock_name == "get_coingecko_connector":
                app.dependency_overrides[get_coingecko_connector] = lambda: mock_fixture

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_db_session():
    """Fixture to mock the database session."""
    with patch("app.main.get_db") as mock:
        yield mock


@pytest.fixture
def mock_coingecko_connector():
    """Fixture to mock the CoinGecko connector."""
    mock_connector = MagicMock()
    mock_connector.get_all_coins.return_value = [{"id": "bitcoin", "name": "Bitcoin"}]
    return mock_connector
