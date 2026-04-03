"""
Shared pytest fixtures.
SQLite in-memory for speed. S3 and Celery fully mocked.
"""
import pytest
import asyncio
import pandas as pd
from unittest.mock import MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer
from sqlalchemy import text

from app.main import app
from app.core.database.engine import Base, get_db
from app.core.security.auth import hash_password
from app.models import User

import os
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-not-production")

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres

@pytest.fixture(scope="session")
async def test_engine(postgres_container):
    # Get the URL from container and convert to asyncpg
    sync_url = postgres_container.get_connection_url()
    async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://")
    
    engine = create_async_engine(async_url, poolclass=NullPool)
    
    # Run migrations using Alembic (sync operation, so we need to bridge or use sync engine)
    # For speed and simplicity in tests, we can run Base.metadata.create_all on the async engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    Session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client(db_session):
    async def override_db():
        yield db_session
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(db_session) -> User:
    user = User(email="test@example.com", hashed_password=hash_password("TestPass1"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_headers(client, test_user) -> dict:
    resp = await client.post("/api/v1/auth/login",
                             json={"email": "test@example.com", "password": "TestPass1"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


SAMPLE_DF = pd.DataFrame({
    "age":    [25, 30, None, 45, 200],
    "salary": [50000.0, 60000.0, 70000.0, None, 80000.0],
    "city":   ["NYC", "LA", "NYC", "LA", "NYC"],
})


@pytest.fixture(autouse=True)
def mock_s3(monkeypatch):
    mock = MagicMock()
    mock.upload_file.return_value = "users/1/raw/test.csv"
    mock.upload_csv_from_df.return_value = "users/1/outputs/out.csv"
    mock.download_to_df.return_value = SAMPLE_DF.copy()
    mock.get_signed_url.return_value = "https://s3.example.com/signed"
    mock.delete_object.return_value = None
    mock.generate_upload_key.return_value = "users/1/raw/abc.csv"
    mock.generate_output_key.return_value = "users/1/outputs/abc.csv"
    mock.ensure_buckets.return_value = None
    monkeypatch.setattr("app.routers.datasets.s3", mock)
    monkeypatch.setattr("app.routers.pipelines.s3", mock)
    monkeypatch.setattr("app.services.tasks.s3", mock)
    return mock


@pytest.fixture(autouse=True)
def mock_celery(monkeypatch):
    task_result = MagicMock()
    task_result.id = "test-task-id"
    mp = MagicMock(); mp.apply_async.return_value = task_result
    me = MagicMock(); me.apply_async.return_value = task_result
    monkeypatch.setattr("app.routers.datasets.profile_dataset_task", mp)
    monkeypatch.setattr("app.routers.pipelines.execute_pipeline_task", me)
    return {"profile": mp, "execute": me}
