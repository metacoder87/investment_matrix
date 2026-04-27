import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure the repo root is on sys.path when pytest collects from `tests/`.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings  # noqa: E402
from app.auth import create_access_token, get_password_hash  # noqa: E402
from app.main import create_app, get_coingecko_connector, get_db  # noqa: E402
from database import Base  # noqa: E402
import app.models.backtest  # noqa: F401,E402
import app.models.imports  # noqa: F401,E402
import app.models.instrument  # noqa: F401,E402
import app.models.market  # noqa: F401,E402
import app.models.paper  # noqa: F401,E402
import app.models.portfolio  # noqa: F401,E402
import app.models.research  # noqa: F401,E402
import app.models.ticks  # noqa: F401,E402
import app.models.user  # noqa: F401,E402
from app.models.user import User  # noqa: E402


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
    
    # Mock Redis to prevent cache poisoning in dev environment
    mock_redis = MagicMock()
    # Async methods need to be awaitable
    async def async_return(val=None):
        return val
    mock_redis.get.side_effect = lambda k: async_return(None)
    mock_redis.setex.side_effect = lambda k, t, v: async_return(True)
    mock_redis.mget.side_effect = lambda k: async_return([None]*len(k))
    mock_redis.flushdb.side_effect = lambda: async_return(True)

    # Patch the global SessionLocal so that any code importing usage sees this one
    with patch("database.SessionLocal", TestingSessionLocal), \
         patch("database.init_db", return_value=None), \
         patch("database.engine", test_engine), \
         patch("app.redis_client.redis_client", mock_redis):
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


@pytest.fixture
def test_user(db_session):
    user = User(
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=get_password_hash("TestPassword123!"),
        full_name="Test User",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user):
    token = create_access_token({"sub": test_user.email, "user_id": test_user.id})
    return {"Authorization": f"Bearer {token}"}
