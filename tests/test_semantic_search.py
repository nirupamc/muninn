"""M1 semantic retrieval and embedding lifecycle tests."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.vector_utils import deserialize_vector
from app.models import Memory, MemoryEmbedding, MemoryStatus, MemoryType
from app.repositories.embedding_repository import EmbeddingRepository
from app.schemas.memory import MemoryCreate
from app.services.embedding_service import EmbeddingService
from app.services.memory_service import MemoryService


def _create_memory(client, **overrides):
    payload = {
        "namespace": "personal",
        "user_id": "user-1",
        "agent_id": "cursor",
        "content": "User is building a PDF parsing engine.",
        "memory_type": "project",
        "importance": 0.9,
        "confidence": 1.0,
    }
    payload.update(overrides)
    return client.post("/api/v1/memories", json=payload)


def test_create_memory_persists_embedding(client, db_session, fake_provider):
    response = _create_memory(client)
    assert response.status_code == 201
    memory_id = response.json()["id"]

    # Use a fresh session against the same in-memory engine via client fixture's engine:
    # query through API-side DB by opening session bound to same engine from fixture chain.
    # The client commits into the shared StaticPool engine; reuse db_session's bind.
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        row = EmbeddingRepository(session).get_by_memory_id(memory_id)
        assert row is not None
        assert row.provider == fake_provider.provider_name
        assert row.model_name == fake_provider.model_name
        assert row.dimension == fake_provider.dimension
        vector = deserialize_vector(row.embedding)
        assert vector.shape == (fake_provider.dimension,)


def test_delete_memory_cascades_embedding(client, db_session):
    created = _create_memory(client)
    memory_id = created.json()["id"]
    deleted = client.delete(f"/api/v1/memories/{memory_id}")
    assert deleted.status_code == 204

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        assert EmbeddingRepository(session).get_by_memory_id(memory_id) is None
        assert session.get(Memory, memory_id) is None


def test_patch_content_reembeds(client, db_session):
    created = _create_memory(client, content="User likes cats.")
    memory_id = created.json()["id"]

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        before = EmbeddingRepository(session).get_by_memory_id(memory_id)
        assert before is not None
        vector_a = bytes(before.embedding)
        updated_at_a = before.updated_at

    patched = client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"content": "User is building a PDF document parser."},
    )
    assert patched.status_code == 200

    with Session() as session:
        after = EmbeddingRepository(session).get_by_memory_id(memory_id)
        assert after is not None
        vector_b = bytes(after.embedding)
        assert vector_a != vector_b
        assert after.updated_at >= updated_at_a


def test_patch_importance_does_not_reembed(client, db_session):
    created = _create_memory(client)
    memory_id = created.json()["id"]

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        before = EmbeddingRepository(session).get_by_memory_id(memory_id)
        assert before is not None
        vector_a = bytes(before.embedding)
        updated_at_a = before.updated_at

    patched = client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"importance": 0.42},
    )
    assert patched.status_code == 200
    assert patched.json()["importance"] == 0.42

    with Session() as session:
        after = EmbeddingRepository(session).get_by_memory_id(memory_id)
        assert after is not None
        assert bytes(after.embedding) == vector_a
        assert after.updated_at == updated_at_a


def test_semantic_retrieval_ranks_relevant_first(client):
    _create_memory(
        client,
        content="User enjoys experimenting with local language models.",
        memory_type="preference",
    )
    relevant = _create_memory(
        client,
        content="User is building a PDF parsing engine.",
        memory_type="project",
    )
    assert relevant.status_code == 201

    search = client.post(
        "/api/v1/memories/search",
        json={
            "query": "document parser project",
            "namespace": "personal",
            "limit": 5,
            "min_score": 0.0,
        },
    )
    assert search.status_code == 200
    body = search.json()
    assert body["count"] >= 1
    assert body["results"][0]["memory"]["id"] == relevant.json()["id"]


def test_ranking_higher_similarity_first(client):
    low = _create_memory(client, content="User likes tea.")
    high = _create_memory(client, content="User is building RagParser for PDF document parsing.")
    assert low.status_code == 201
    assert high.status_code == 201

    search = client.post(
        "/api/v1/memories/search",
        json={
            "query": "pdf document parser",
            "namespace": "personal",
        },
    )
    ids = [item["memory"]["id"] for item in search.json()["results"]]
    assert ids.index(high.json()["id"]) < ids.index(low.json()["id"])


def test_min_score_excludes_low_similarity(client):
    _create_memory(client, content="Completely unrelated gardening notes.")
    search = client.post(
        "/api/v1/memories/search",
        json={
            "query": "pdf document parser",
            "namespace": "personal",
            "min_score": 0.99,
        },
    )
    assert search.status_code == 200
    assert search.json()["count"] == 0


def test_search_limit(client):
    for i in range(5):
        _create_memory(client, content=f"User is building PDF document parser number {i}.")

    search = client.post(
        "/api/v1/memories/search",
        json={
            "query": "document parser",
            "namespace": "personal",
            "limit": 2,
            "min_score": 0.0,
        },
    )
    assert search.status_code == 200
    assert search.json()["count"] == 2
    assert len(search.json()["results"]) == 2


def test_search_namespace_isolation(client):
    client.post(
        "/api/v1/memories",
        json={
            "namespace": "ragparser",
            "content": "RagParser parses PDFs and documents.",
            "memory_type": "project",
        },
    )
    client.post(
        "/api/v1/memories",
        json={
            "namespace": "munin",
            "content": "Munin stores long-term agent memory.",
            "memory_type": "project",
        },
    )

    search = client.post(
        "/api/v1/memories/search",
        json={
            "query": "PDF document parser",
            "namespace": "munin",
            "min_score": 0.0,
        },
    )
    assert search.status_code == 200
    namespaces = {item["memory"]["namespace"] for item in search.json()["results"]}
    assert namespaces == {"munin"} or search.json()["count"] == 0
    for item in search.json()["results"]:
        assert item["memory"]["namespace"] == "munin"
        assert "RagParser" not in item["memory"]["content"]


def test_search_user_and_agent_filters(client):
    _create_memory(client, user_id="user-1", agent_id="cursor", content="PDF parser for user-1")
    _create_memory(client, user_id="user-2", agent_id="other", content="PDF parser for user-2")

    by_user = client.post(
        "/api/v1/memories/search",
        json={
            "query": "PDF parser",
            "namespace": "personal",
            "user_id": "user-1",
        },
    )
    assert by_user.status_code == 200
    assert all(item["memory"]["user_id"] == "user-1" for item in by_user.json()["results"])

    by_agent = client.post(
        "/api/v1/memories/search",
        json={
            "query": "PDF parser",
            "namespace": "personal",
            "agent_id": "other",
        },
    )
    assert by_agent.status_code == 200
    assert all(item["memory"]["agent_id"] == "other" for item in by_agent.json()["results"])


def test_search_memory_type_and_status_filters(client):
    _create_memory(
        client,
        content="PDF document parsing project",
        memory_type="project",
        status="active",
    )
    _create_memory(
        client,
        content="PDF document parsing goal",
        memory_type="goal",
        status="archived",
    )

    by_type = client.post(
        "/api/v1/memories/search",
        json={
            "query": "PDF document",
            "namespace": "personal",
            "memory_types": ["goal"],
        },
    )
    assert by_type.status_code == 200
    assert all(item["memory"]["memory_type"] == "goal" for item in by_type.json()["results"])

    by_status = client.post(
        "/api/v1/memories/search",
        json={
            "query": "PDF document",
            "namespace": "personal",
            "statuses": ["archived"],
        },
    )
    assert by_status.status_code == 200
    assert all(item["memory"]["status"] == "archived" for item in by_status.json()["results"])


def test_search_validation(client):
    assert (
        client.post(
            "/api/v1/memories/search",
            json={"query": "   ", "namespace": "personal"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/memories/search",
            json={"query": "hello", "namespace": "personal", "min_score": 1.5},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/memories/search",
            json={"query": "hello", "namespace": "personal", "memory_types": ["nope"]},
        ).status_code
        == 422
    )


def test_model_mismatch_excluded_from_search(client, db_session, fake_provider):
    created = _create_memory(client, content="User is building a PDF parsing engine.")
    memory_id = created.json()["id"]

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        row = EmbeddingRepository(session).get_by_memory_id(memory_id)
        assert row is not None
        row.model_name = "other-model"
        session.add(row)
        session.commit()

    search = client.post(
        "/api/v1/memories/search",
        json={
            "query": "document parser project",
            "namespace": "personal",
            "min_score": 0.0,
        },
    )
    assert search.status_code == 200
    assert search.json()["count"] == 0


def test_backfill_idempotent(db_session, fake_provider):
    memory = Memory(
        namespace="legacy",
        content="Legacy memory without embedding",
        memory_type=MemoryType.fact,
        importance=0.5,
        confidence=1.0,
        status=MemoryStatus.active,
        metadata_={},
    )
    db_session.add(memory)
    db_session.commit()
    db_session.refresh(memory)

    service = EmbeddingService(db_session, provider=fake_provider)
    first = service.backfill_missing()
    assert first["embedded"] == 1
    assert first["failed"] == 0

    second = service.backfill_missing()
    assert second["scanned_missing"] == 0
    assert second["embedded"] == 0

    rows = list(
        db_session.scalars(
            select(MemoryEmbedding).where(MemoryEmbedding.memory_id == memory.id)
        ).all()
    )
    assert len(rows) == 1


def test_embedding_failure_rolls_back_memory(engine):
    class BoomProvider(FakeEmbeddingProvider):
        def embed_text(self, text: str) -> list[float]:
            from app.embeddings.base import EmbeddingError

            raise EmbeddingError("boom")

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with Session() as session:
        service = MemoryService(session, embedding_provider=BoomProvider())
        try:
            service.create(
                MemoryCreate(
                    namespace="personal",
                    content="Should not persist",
                    memory_type=MemoryType.fact,
                )
            )
            raise AssertionError("expected HTTPException")
        except Exception as exc:
            from fastapi import HTTPException

            assert isinstance(exc, HTTPException)
            assert exc.status_code == 503

    with Session() as session:
        memories = list(session.scalars(select(Memory)).all())
        embeddings = list(session.scalars(select(MemoryEmbedding)).all())
        assert memories == []
        assert embeddings == []


def test_search_does_not_return_raw_embedding(client):
    _create_memory(client)
    search = client.post(
        "/api/v1/memories/search",
        json={"query": "PDF parsing", "namespace": "personal"},
    )
    body = search.json()
    assert "embedding" not in body
    if body["results"]:
        assert "embedding" not in body["results"][0]
        assert "embedding" not in body["results"][0]["memory"]
