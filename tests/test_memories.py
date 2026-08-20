"""Memory API and persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.models.memory import Memory, MemoryStatus, MemoryType
from app.repositories.memory_repository import MemoryRepository


def _create_memory(client, **overrides):
    payload = {
        "namespace": "personal",
        "user_id": "user-1",
        "agent_id": "cursor",
        "content": "User is building Munin.",
        "memory_type": "project",
        "importance": 0.95,
        "confidence": 1.0,
        "metadata": {"project": "munin"},
    }
    payload.update(overrides)
    return client.post("/api/v1/memories", json=payload)


def test_memory_crud(client):
    create = _create_memory(client)
    assert create.status_code == 201
    body = create.json()
    memory_id = body["id"]
    assert body["content"] == "User is building Munin."
    assert body["memory_type"] == "project"
    assert body["status"] == "active"
    assert body["metadata"] == {"project": "munin"}

    got = client.get(f"/api/v1/memories/{memory_id}")
    assert got.status_code == 200
    assert got.json()["id"] == memory_id

    updated_at_before = got.json()["updated_at"]
    patch = client.patch(
        f"/api/v1/memories/{memory_id}",
        json={"content": "User is building Munin M0.", "importance": 0.8},
    )
    assert patch.status_code == 200
    assert patch.json()["content"] == "User is building Munin M0."
    assert patch.json()["importance"] == 0.8
    assert patch.json()["updated_at"] >= updated_at_before

    deleted = client.delete(f"/api/v1/memories/{memory_id}")
    assert deleted.status_code == 204

    missing = client.get(f"/api/v1/memories/{memory_id}")
    assert missing.status_code == 404


def test_memory_not_found(client):
    response = client.get("/api/v1/memories/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_memory_delete_not_found(client):
    response = client.delete("/api/v1/memories/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_memory_persistence_across_sessions(engine):
    SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with SessionFactory() as session:
        repo = MemoryRepository(session)
        memory = Memory(
            namespace="default",
            content="Durable fact",
            memory_type=MemoryType.fact,
            importance=0.5,
            confidence=1.0,
            status=MemoryStatus.active,
            metadata_={},
        )
        created = repo.create(memory)
        memory_id = created.id

    with SessionFactory() as session:
        repo = MemoryRepository(session)
        loaded = repo.get_by_id(memory_id)
        assert loaded is not None
        assert loaded.content == "Durable fact"


def test_memory_validation_failures(client):
    cases = [
        {"importance": -1},
        {"importance": 1.5},
        {"confidence": -0.2},
        {"content": "   "},
        {"content": ""},
        {"memory_type": "not-a-type"},
        {"status": "not-a-status"},
    ]
    for override in cases:
        response = _create_memory(client, **override)
        assert response.status_code == 422, override


def test_valid_until_before_valid_from_rejected(client):
    now = datetime.now(UTC)
    response = _create_memory(
        client,
        valid_from=(now + timedelta(days=2)).isoformat(),
        valid_until=now.isoformat(),
    )
    assert response.status_code == 422


def test_memory_filters_and_pagination(client):
    _create_memory(
        client,
        namespace="ns-a",
        user_id="u1",
        agent_id="a1",
        memory_type="fact",
        status="active",
        content="fact one",
    )
    _create_memory(
        client,
        namespace="ns-a",
        user_id="u2",
        agent_id="a2",
        memory_type="goal",
        status="archived",
        content="goal one",
    )
    _create_memory(
        client,
        namespace="ns-b",
        user_id="u1",
        agent_id="a1",
        memory_type="fact",
        content="other ns",
    )

    by_user = client.get("/api/v1/memories", params={"namespace": "ns-a", "user_id": "u1"})
    assert by_user.status_code == 200
    assert len(by_user.json()) == 1
    assert by_user.json()[0]["content"] == "fact one"

    by_type = client.get("/api/v1/memories", params={"namespace": "ns-a", "memory_type": "goal"})
    assert len(by_type.json()) == 1
    assert by_type.json()[0]["memory_type"] == "goal"

    by_status = client.get("/api/v1/memories", params={"namespace": "ns-a", "status": "archived"})
    assert len(by_status.json()) == 1

    by_agent = client.get("/api/v1/memories", params={"namespace": "ns-a", "agent_id": "a2"})
    assert len(by_agent.json()) == 1

    page = client.get("/api/v1/memories", params={"namespace": "ns-a", "limit": 1, "offset": 0})
    assert len(page.json()) == 1

    page2 = client.get("/api/v1/memories", params={"namespace": "ns-a", "limit": 1, "offset": 1})
    assert len(page2.json()) == 1
    assert page.json()[0]["id"] != page2.json()[0]["id"]


def test_provenance_survives_event_deletion(client):
    event = client.post(
        "/api/v1/events",
        json={
            "namespace": "personal",
            "role": "user",
            "content": "I am building Munin using FastAPI.",
        },
    )
    assert event.status_code == 201
    event_id = event.json()["id"]

    memory = _create_memory(client, source_event_id=event_id)
    assert memory.status_code == 201
    memory_id = memory.json()["id"]
    assert memory.json()["source_event_id"] == event_id

    deleted = client.delete(f"/api/v1/events/{event_id}")
    assert deleted.status_code == 204

    surviving = client.get(f"/api/v1/memories/{memory_id}")
    assert surviving.status_code == 200
    assert surviving.json()["source_event_id"] is None


def test_invalid_source_event_id_rejected(client):
    response = _create_memory(
        client,
        source_event_id="00000000-0000-0000-0000-000000000000",
    )
    assert response.status_code == 400


def test_patch_rejects_invalid_temporal_bounds(client):
    created = _create_memory(client)
    memory_id = created.json()["id"]
    now = datetime.now(UTC)
    response = client.patch(
        f"/api/v1/memories/{memory_id}",
        json={
            "valid_from": (now + timedelta(days=5)).isoformat(),
            "valid_until": now.isoformat(),
        },
    )
    assert response.status_code == 422
