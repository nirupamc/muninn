"""M4 temporal memory tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.deduplication.models import RelationshipType
from app.deduplication.service import DeduplicationService
from app.embeddings.fake import FakeEmbeddingProvider
from app.models import Memory, MemoryTemporalDecision, MemoryType
from app.models.event import EventRole
from app.models.memory import MemoryStatus
from app.schemas.event import EventCreate
from app.schemas.memory import MemoryCreate, MemorySearchRequest
from app.services.event_service import EventService
from app.services.memory_service import MemoryService
from app.temporal.base import TemporalRelationshipError, TemporalRelationshipProvider
from app.temporal.evaluate import evaluate_cases
from app.temporal.models import TemporalRelationshipAnalysis, TemporalRelationshipType
from app.temporal.policy import TemporalPolicyConfig
from app.temporal.service import TemporalService


def _create_event(client, content: str, **overrides):
    payload = {
        "namespace": "personal",
        "user_id": "user-1",
        "agent_id": "cursor",
        "session_id": "s1",
        "role": "user",
        "content": content,
    }
    payload.update(overrides)
    return client.post("/api/v1/events", json=payload)


def _admit(client, event_id: str, **kwargs):
    return client.post(f"/api/v1/events/{event_id}/admit", **kwargs)


def _store_memory(client, content: str, **overrides):
    payload = {
        "namespace": "personal",
        "user_id": "user-1",
        "agent_id": "cursor",
        "content": content,
        "memory_type": "preference",
        "importance": 0.9,
        "confidence": 1.0,
    }
    payload.update(overrides)
    return client.post("/api/v1/memories", json=payload)


def test_preference_supersede(client, db_session):
    first = _create_event(client, "I prefer OpenAI APIs.")
    a1 = _admit(client, first.json()["id"])
    assert a1.status_code == 200
    old_id = a1.json()["results"][0]["memory_id"]
    assert old_id

    second = _create_event(client, "I now prefer local models.")
    a2 = _admit(client, second.json()["id"])
    assert a2.status_code == 200
    store = [r for r in a2.json()["results"] if r["decision"] == "STORE"][0]
    assert store["deduplication"]["relationship"] == "NEW"
    assert store["temporal"]["relationship"] == "SUPERSEDES"
    assert store["temporal"]["matched_memory_id"] == old_id
    new_id = store["memory_id"]
    assert new_id and new_id != old_id

    old = client.get(f"/api/v1/memories/{old_id}").json()
    new = client.get(f"/api/v1/memories/{new_id}").json()
    assert old["status"] == "superseded"
    assert old["valid_until"] is not None
    assert new["status"] == "active"
    assert new["valid_from"] is not None


def test_no_longer_use_supersedes(client):
    first = _create_event(client, "I use SQLite for Munin.")
    a1 = _admit(client, first.json()["id"])
    old_id = a1.json()["results"][0]["memory_id"]

    second = _create_event(client, "I no longer use SQLite.")
    a2 = _admit(client, second.json()["id"])
    store = [r for r in a2.json()["results"] if r["decision"] == "STORE"][0]
    assert store["temporal"]["relationship"] == "SUPERSEDES"
    assert client.get(f"/api/v1/memories/{old_id}").json()["status"] == "superseded"


def test_m3_reinforces_skips_m4(client):
    first = _create_event(client, "I use FastAPI.")
    a1 = _admit(client, first.json()["id"])
    old_id = a1.json()["results"][0]["memory_id"]

    second = _create_event(client, "I still use FastAPI.")
    a2 = _admit(client, second.json()["id"])
    store = [r for r in a2.json()["results"] if r["decision"] == "STORE"][0]
    assert store["deduplication"]["relationship"] == "REINFORCES"
    assert store["temporal"] is None

    search = client.post(
        "/api/v1/memories/search",
        json={
            "query": "User uses FastAPI.",
            "namespace": "personal",
            "user_id": "user-1",
            "statuses": ["active"],
            "limit": 10,
        },
    )
    assert search.json()["count"] == 1


def test_related_but_new(client):
    first = _create_event(client, "I'm building Munin.")
    a1 = _admit(client, first.json()["id"])
    old_id = a1.json()["results"][0]["memory_id"]

    second = _create_event(client, "Munin uses FastAPI.")
    a2 = _admit(client, second.json()["id"])
    store = [r for r in a2.json()["results"] if r["decision"] == "STORE"][0]
    assert store["deduplication"]["relationship"] == "NEW"
    assert store["temporal"]["relationship"] == "NEW"
    assert client.get(f"/api/v1/memories/{old_id}").json()["status"] == "active"


def test_unresolved_contradiction(client):
    first = _create_event(client, "I prefer Python.")
    a1 = _admit(client, first.json()["id"])
    old_id = a1.json()["results"][0]["memory_id"]

    second = _create_event(client, "I prefer Rust.")
    a2 = _admit(client, second.json()["id"])
    store = [r for r in a2.json()["results"] if r["decision"] == "STORE"][0]
    assert store["temporal"]["relationship"] == "CONTRADICTS"
    assert client.get(f"/api/v1/memories/{old_id}").json()["status"] == "active"
    assert store["memory_id"] != old_id


def test_low_confidence_fallback_new(client, db_session):
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="I now prefer local models.",
            )
        )
        mem = MemoryService(session, embedding_provider=FakeEmbeddingProvider()).create(
            MemoryCreate(
                namespace="personal",
                user_id="user-1",
                content="User prefers OpenAI APIs.",
                memory_type=MemoryType.preference,
            ),
            commit=False,
        )
        session.commit()

        class LowConfidenceProvider(TemporalRelationshipProvider):
            @property
            def provider_name(self) -> str:
                return "test"

            @property
            def model_name(self) -> str:
                return "test"

            def classify(self, **kwargs: Any) -> TemporalRelationshipAnalysis:
                return TemporalRelationshipAnalysis(
                    relationship=TemporalRelationshipType.SUPERSEDES,
                    confidence=0.2,
                )

        dedup = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        dedup_result = dedup.process_candidate(
            event=evt,
            admission_id=None,
            content="User now prefers local models.",
            memory_type=MemoryType.preference,
            importance=0.8,
            confidence=0.9,
            create_memory=True,
        )
        temporal = TemporalService(
            session,
            temporal_provider=LowConfidenceProvider(),
            embedding_provider=FakeEmbeddingProvider(),
            policy=TemporalPolicyConfig(min_relationship_confidence=0.75),
        )
        result = temporal.process_new_candidate(
            event=evt,
            admission_id=None,
            dedup_decision_id=dedup_result.decision_id,
            content="User now prefers local models.",
            memory_type=MemoryType.preference,
            created_memory_id=dedup_result.created_memory_id,
        )
        assert result.relationship == TemporalRelationshipType.NEW
        old = session.get(Memory, mem.id)
        assert old is not None
        assert old.status == MemoryStatus.active


def test_provider_failure_fallback_new(client, db_session):
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="I no longer use SQLite.",
            )
        )
        mem = MemoryService(session, embedding_provider=FakeEmbeddingProvider()).create(
            MemoryCreate(
                namespace="personal",
                user_id="user-1",
                content="User uses SQLite.",
                memory_type=MemoryType.fact,
            ),
            commit=False,
        )
        session.commit()

        class FailingProvider(TemporalRelationshipProvider):
            @property
            def provider_name(self) -> str:
                return "test"

            @property
            def model_name(self) -> str:
                return "test"

            def classify(self, **kwargs: Any) -> TemporalRelationshipAnalysis:
                raise TemporalRelationshipError("down")

        dedup = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        dedup_result = dedup.process_candidate(
            event=evt,
            admission_id=None,
            content="User no longer uses SQLite.",
            memory_type=MemoryType.fact,
            importance=0.8,
            confidence=0.9,
            create_memory=True,
        )
        temporal = TemporalService(
            session,
            temporal_provider=FailingProvider(),
            embedding_provider=FakeEmbeddingProvider(),
        )
        result = temporal.process_new_candidate(
            event=evt,
            admission_id=None,
            dedup_decision_id=dedup_result.decision_id,
            content="User no longer uses SQLite.",
            memory_type=MemoryType.fact,
            created_memory_id=dedup_result.created_memory_id,
        )
        assert result.relationship == TemporalRelationshipType.NEW
        assert session.get(Memory, mem.id).status == MemoryStatus.active


def test_namespace_isolation(client):
    _store_memory(
        client,
        "User prefers Python.",
        namespace="team-a",
        memory_type="preference",
    )
    evt = _create_event(
        client,
        "I now prefer Rust.",
        namespace="team-b",
        user_id="user-1",
    )
    a = _admit(client, evt.json()["id"])
    store = [r for r in a.json()["results"] if r["decision"] == "STORE"][0]
    assert store["temporal"]["relationship"] == "NEW"


def test_user_isolation(client):
    _store_memory(
        client,
        "User prefers Python.",
        user_id="user-a",
        memory_type="preference",
    )
    evt = _create_event(client, "I now prefer Rust.", user_id="user-b")
    a = _admit(client, evt.json()["id"])
    store = [r for r in a.json()["results"] if r["decision"] == "STORE"][0]
    assert store["temporal"]["relationship"] == "NEW"


def test_superseded_historical_retrieval(client):
    first = _create_event(client, "I prefer OpenAI APIs.")
    a1 = _admit(client, first.json()["id"])
    old_id = a1.json()["results"][0]["memory_id"]

    second = _create_event(client, "I now prefer local models.")
    _admit(client, second.json()["id"])

    search = client.post(
        "/api/v1/memories/search",
        json={
            "query": "OpenAI APIs",
            "namespace": "personal",
            "user_id": "user-1",
            "statuses": ["active", "superseded"],
            "limit": 10,
        },
    )
    ids = {hit["memory"]["id"] for hit in search.json()["results"]}
    assert old_id in ids


def test_history_endpoint(client):
    first = _create_event(client, "I prefer OpenAI APIs.")
    a1 = _admit(client, first.json()["id"])
    old_id = a1.json()["results"][0]["memory_id"]

    second = _create_event(client, "I now prefer local models.")
    a2 = _admit(client, second.json()["id"])
    new_id = a2.json()["results"][0]["memory_id"]

    old_history = client.get(f"/api/v1/memories/{old_id}/history")
    assert old_history.status_code == 200
    assert len(old_history.json()["temporal_decisions"]) >= 1
    assert any(
        row["relationship"] == "SUPERSEDES"
        for row in old_history.json()["temporal_decisions"]
    )

    new_history = client.get(f"/api/v1/memories/{new_id}/history")
    assert new_history.status_code == 200


def test_provenance_preserved(client):
    first = _create_event(client, "I prefer OpenAI APIs.")
    old_event_id = first.json()["id"]
    a1 = _admit(client, old_event_id)
    old_id = a1.json()["results"][0]["memory_id"]

    second = _create_event(client, "I now prefer local models.")
    new_event_id = second.json()["id"]
    a2 = _admit(client, new_event_id)
    new_id = a2.json()["results"][0]["memory_id"]

    old = client.get(f"/api/v1/memories/{old_id}").json()
    new = client.get(f"/api/v1/memories/{new_id}").json()
    assert old["source_event_id"] == old_event_id
    assert new["source_event_id"] == new_event_id


def test_idempotent_replay(client, db_session):
    evt = _create_event(client, "I prefer OpenAI APIs.")
    event_id = evt.json()["id"]
    first = _admit(client, event_id)
    second = _admit(client, event_id)
    assert second.json()["idempotent_replay"] is True

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        temporal_count = session.scalar(
            select(func.count()).select_from(MemoryTemporalDecision)
        )
        memory_count = session.scalar(select(func.count()).select_from(Memory))
    assert temporal_count == 1
    assert memory_count == 1


def test_transaction_rollback_on_temporal_failure(client, db_session):
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        mem = MemoryService(session, embedding_provider=FakeEmbeddingProvider()).create(
            MemoryCreate(
                namespace="personal",
                user_id="user-1",
                content="User prefers OpenAI APIs.",
                memory_type=MemoryType.preference,
            )
        )
        old_id = mem.id

    evt = _create_event(client, "I now prefer local models.")
    event_id = evt.json()["id"]

    with patch(
        "app.temporal.service.TemporalService.process_new_candidate",
        side_effect=RuntimeError("simulated failure"),
    ):
        with pytest.raises(RuntimeError, match="simulated failure"):
            _admit(client, event_id)

    with Session() as session:
        old = session.get(Memory, old_id)
        assert old.status == MemoryStatus.active
        assert session.scalar(select(func.count()).select_from(MemoryTemporalDecision)) == 0
        assert session.scalar(select(func.count()).select_from(Memory)) == 1


def test_temporal_evaluation_fixtures():
    metrics = evaluate_cases()
    assert metrics["total"] >= 30
    assert metrics["false_supersede_count"] == 0
    assert metrics["accuracy"] >= 0.7


def test_event_temporal_audit_endpoint(client):
    evt = _create_event(client, "I prefer OpenAI APIs.")
    _admit(client, evt.json()["id"])
    second = _create_event(client, "I now prefer local models.")
    _admit(client, second.json()["id"])

    rows = client.get(f"/api/v1/events/{second.json()['id']}/temporal")
    assert rows.status_code == 200
    assert len(rows.json()) >= 1
    assert rows.json()[0]["relationship"] == "SUPERSEDES"
