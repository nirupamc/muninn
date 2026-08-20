"""Shared pytest fixtures with an isolated SQLite database."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.admission.factory import get_admission_provider, set_admission_provider_override
from app.admission.providers.deterministic import DeterministicAdmissionProvider
from app.database import Base, get_db
from app.deduplication.factory import (
    get_relationship_provider,
    set_relationship_provider_override,
)
from app.deduplication.providers.deterministic import DeterministicRelationshipProvider
from app.embeddings.factory import get_embedding_provider, set_embedding_provider_override
from app.embeddings.fake import FakeEmbeddingProvider
from app.main import create_app
from app.temporal.factory import get_temporal_provider, set_temporal_provider_override
from app.temporal.providers.deterministic import DeterministicTemporalProvider
from app.models import (  # noqa: F401
    Event,
    Memory,
    MemoryAdmission,
    MemoryDeduplicationDecision,
    MemoryEmbedding,
    MemoryReinforcement,
    MemoryTemporalDecision,
)


@pytest.fixture()
def fake_provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture()
def admission_provider() -> DeterministicAdmissionProvider:
    return DeterministicAdmissionProvider()


@pytest.fixture()
def relationship_provider() -> DeterministicRelationshipProvider:
    return DeterministicRelationshipProvider()


@pytest.fixture()
def engine():
    """In-memory SQLite engine shared across connections in a test."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine) -> Session:
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def temporal_provider() -> DeterministicTemporalProvider:
    return DeterministicTemporalProvider()


@pytest.fixture()
def client(engine, fake_provider, admission_provider, relationship_provider, temporal_provider) -> TestClient:
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    app = create_app()
    set_embedding_provider_override(fake_provider)
    set_admission_provider_override(admission_provider)
    set_relationship_provider_override(relationship_provider)
    set_temporal_provider_override(temporal_provider)

    def _override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_embedding_provider] = lambda: fake_provider
    app.dependency_overrides[get_admission_provider] = lambda: admission_provider
    app.dependency_overrides[get_relationship_provider] = lambda: relationship_provider
    app.dependency_overrides[get_temporal_provider] = lambda: temporal_provider
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    set_embedding_provider_override(None)
    set_admission_provider_override(None)
    set_relationship_provider_override(None)
    set_temporal_provider_override(None)
