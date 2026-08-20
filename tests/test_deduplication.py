"""M3 deduplication & reinforcement tests."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.deduplication.base import RelationshipError, RelationshipProvider
from app.deduplication.evaluate import evaluate_cases
from app.deduplication.models import RelationshipAnalysis, RelationshipType
from app.deduplication.policy import DedupPolicyConfig, apply_relationship_policy
from app.deduplication.providers.deterministic import DeterministicRelationshipProvider
from app.deduplication.service import DeduplicationService
from app.embeddings.base import EmbeddingError
from app.embeddings.fake import FakeEmbeddingProvider
from app.models import (
    Memory,
    MemoryAdmission,
    MemoryDeduplicationDecision,
    MemoryEmbedding,
    MemoryReinforcement,
    MemoryType,
)
from app.models.event import EventRole
from app.schemas.event import EventCreate
from app.schemas.memory import MemoryCreate
from app.services.event_service import EventService
from app.services.memory_service import MemoryService


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


def _admit(client, event_id: str):
    return client.post(f"/api/v1/events/{event_id}/admit")


def _store_memory(client, content: str, **overrides):
    payload = {
        "namespace": "personal",
        "user_id": "user-1",
        "agent_id": "cursor",
        "content": content,
        "memory_type": "project",
        "importance": 0.9,
        "confidence": 1.0,
    }
    payload.update(overrides)
    return client.post("/api/v1/memories", json=payload)


def test_exact_duplicate(client, db_session):
    first = _create_event(client, "I'm building RagParser.")
    a1 = _admit(client, first.json()["id"])
    assert a1.status_code == 200
    assert a1.json()["results"][0]["deduplication"]["relationship"] == "NEW"
    memory_id = a1.json()["results"][0]["memory_id"]
    assert memory_id

    second = _create_event(client, "User is building RagParser.")
    # Force candidate via direct memory path already exists; admit a matching utterance
    a2 = _admit(client, second.json()["id"])
    assert a2.status_code == 200
    store = [r for r in a2.json()["results"] if r["decision"] == "STORE"]
    assert store
    dedup = store[0]["deduplication"]
    assert dedup["relationship"] == "DUPLICATE"
    assert dedup["created_new_memory"] is False
    assert dedup["matched_memory_id"] == memory_id
    assert store[0]["memory_id"] is None

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Memory)) == 1
        decisions = list(session.scalars(select(MemoryDeduplicationDecision)).all())
        assert any(d.relationship == "DUPLICATE" for d in decisions)


def test_normalized_duplicate(client, db_session):
    _store_memory(
        client,
        "User prefers Python.",
        memory_type="preference",
    )
    event = _create_event(client, " user   prefers   python. ")
    # Deterministic admission may rewrite; seed via analyze path by using Remember wording
    # Prefer direct service-level check for normalization:
    from app.deduplication.normalize import normalize_for_exact_match

    assert normalize_for_exact_match("User prefers Python.") == normalize_for_exact_match(
        " user   prefers   python. "
    )

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="user prefers python.",
            )
        )
        svc = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content=" user   prefers   python. ",
            memory_type=MemoryType.preference,
            importance=0.8,
            confidence=0.9,
        )
        session.commit()
        assert result.relationship == RelationshipType.DUPLICATE
        assert result.created_new_memory is False


def test_semantic_duplicate(client, db_session):
    seeded = _store_memory(client, "User is building RagParser.")
    memory_id = seeded.json()["id"]

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="RagParser is a project the user is currently working on.",
            )
        )
        svc = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content="RagParser is a project the user is currently working on.",
            memory_type=MemoryType.project,
            importance=0.9,
            confidence=0.95,
        )
        session.commit()
        assert result.relationship == RelationshipType.DUPLICATE
        assert result.matched_memory_id == memory_id
        assert result.created_new_memory is False
        assert session.scalar(select(func.count()).select_from(Memory)) == 1

        # Exact-normalized path also covers admit-time duplicates when M2
        # normalizes to the same candidate string.
        evt2 = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="I'm building RagParser again.",
            )
        )
        result2 = svc.process_candidate(
            event=evt2,
            admission_id=None,
            content="User is building RagParser.",
            memory_type=MemoryType.project,
            importance=0.9,
            confidence=0.95,
        )
        session.commit()
        assert result2.relationship == RelationshipType.DUPLICATE


def test_reinforcement(client, db_session):
    seeded = _store_memory(
        client,
        "User prefers Python for backend work.",
        memory_type="preference",
    )
    memory_id = seeded.json()["id"]
    original_source = seeded.json().get("source_event_id")

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="Python is still the user's default backend language.",
            )
        )
        svc = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content="Python is still the user's default backend language.",
            memory_type=MemoryType.preference,
            importance=0.8,
            confidence=0.9,
        )
        session.commit()
        assert result.relationship == RelationshipType.REINFORCES
        assert result.created_new_memory is False
        assert result.matched_memory_id == memory_id

        reinforcements = list(
            session.scalars(
                select(MemoryReinforcement).where(MemoryReinforcement.memory_id == memory_id)
            ).all()
        )
        assert len(reinforcements) == 1
        assert reinforcements[0].source_event_id == evt.id
        assert reinforcements[0].relationship_confidence >= 0.7

        mem = session.get(Memory, memory_id)
        assert mem is not None
        assert mem.source_event_id == original_source
        assert session.scalar(select(func.count()).select_from(Memory)) == 1


def test_related_but_new(client, db_session):
    _store_memory(client, "User is building Munin.")
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="Munin uses FastAPI.",
            )
        )
        svc = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content="Munin uses FastAPI.",
            memory_type=MemoryType.fact,
            importance=0.8,
            confidence=0.9,
        )
        session.commit()
        assert result.relationship == RelationshipType.NEW
        assert result.created_new_memory is True
        assert result.created_memory_id is not None
        assert session.scalar(select(func.count()).select_from(Memory)) == 2


def test_similar_but_opposite_not_duplicate():
    provider = DeterministicRelationshipProvider()
    analysis = provider.classify(
        candidate="User does not prefer Python.",
        existing_memory="User prefers Python.",
        candidate_type=MemoryType.preference,
        existing_type=MemoryType.preference,
    )
    assert analysis.relationship == RelationshipType.NEW


def test_similar_but_opposite_integration(client, db_session):
    _store_memory(client, "User prefers Python.", memory_type="preference")
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="User does not prefer Python.",
            )
        )
        svc = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content="User does not prefer Python.",
            memory_type=MemoryType.preference,
            importance=0.8,
            confidence=0.9,
        )
        session.commit()
        assert result.relationship == RelationshipType.NEW
        assert result.created_new_memory is True
        assert session.scalar(select(func.count()).select_from(Memory)) == 2


def test_different_memory_type(client, db_session):
    _store_memory(client, "User is building Munin.", memory_type="project")
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="User wants to finish Munin this month.",
            )
        )
        svc = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content="User wants to finish Munin this month.",
            memory_type=MemoryType.goal,
            importance=0.9,
            confidence=0.9,
        )
        session.commit()
        assert result.relationship == RelationshipType.NEW
        assert result.created_new_memory is True


def test_namespace_isolation(client, db_session):
    _store_memory(client, "User is building RagParser.", namespace="ns-a")
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="ns-b",
                user_id="user-1",
                role=EventRole.user,
                content="User is building RagParser.",
            )
        )
        svc = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content="User is building RagParser.",
            memory_type=MemoryType.project,
            importance=0.9,
            confidence=0.9,
        )
        session.commit()
        assert result.relationship == RelationshipType.NEW
        assert result.created_new_memory is True
        assert session.scalar(select(func.count()).select_from(Memory)) == 2


def test_user_isolation(client, db_session):
    _store_memory(
        client,
        "User is building RagParser.",
        user_id="user-a",
    )
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-b",
                role=EventRole.user,
                content="User is building RagParser.",
            )
        )
        svc = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content="User is building RagParser.",
            memory_type=MemoryType.project,
            importance=0.9,
            confidence=0.9,
        )
        session.commit()
        assert result.relationship == RelationshipType.NEW
        assert result.created_new_memory is True
        assert session.scalar(select(func.count()).select_from(Memory)) == 2


def test_low_similarity_defaults_new(client, db_session):
    _store_memory(client, "User is building RagParser.")
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="User prefers dark mode themes.",
            )
        )
        svc = DeduplicationService(session, embedding_provider=FakeEmbeddingProvider())
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content="User prefers dark mode themes.",
            memory_type=MemoryType.preference,
            importance=0.7,
            confidence=0.9,
        )
        session.commit()
        assert result.relationship == RelationshipType.NEW
        assert result.created_new_memory is True


def test_low_relationship_confidence_defaults_new(client, db_session):
    class LowConfProvider(RelationshipProvider):
        @property
        def provider_name(self) -> str:
            return "low"

        @property
        def model_name(self) -> str:
            return "low"

        def classify(self, **kwargs):  # noqa: ANN003
            return RelationshipAnalysis(
                relationship=RelationshipType.DUPLICATE,
                confidence=0.2,
                explanation="uncertain",
            )

    _store_memory(client, "User is building RagParser.")
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="RagParser is a project the user is currently working on.",
            )
        )
        svc = DeduplicationService(
            session,
            relationship_provider=LowConfProvider(),
            embedding_provider=FakeEmbeddingProvider(),
            policy=DedupPolicyConfig(min_relationship_confidence=0.70),
        )
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content="RagParser is a project the user is currently working on.",
            memory_type=MemoryType.project,
            importance=0.9,
            confidence=0.9,
        )
        session.commit()
        assert result.relationship == RelationshipType.NEW
        assert result.created_new_memory is True
        assert "LOW_CONFIDENCE" in result.reason_codes or "RELATIONSHIP_UNCERTAIN" in result.reason_codes


def test_provider_error_defaults_new(client, db_session):
    class BoomProvider(RelationshipProvider):
        @property
        def provider_name(self) -> str:
            return "boom"

        @property
        def model_name(self) -> str:
            return "boom"

        def classify(self, **kwargs):  # noqa: ANN003
            raise RelationshipError("down")

    _store_memory(client, "User is building RagParser.")
    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="RagParser is a project the user is currently working on.",
            )
        )
        svc = DeduplicationService(
            session,
            relationship_provider=BoomProvider(),
            embedding_provider=FakeEmbeddingProvider(),
        )
        result = svc.process_candidate(
            event=evt,
            admission_id=None,
            content="RagParser is a project the user is currently working on.",
            memory_type=MemoryType.project,
            importance=0.9,
            confidence=0.9,
        )
        session.commit()
        assert result.relationship == RelationshipType.NEW
        assert result.created_new_memory is True
        assert "PROVIDER_UNAVAILABLE" in result.reason_codes


def test_duplicate_audit_endpoint(client, db_session):
    first = _create_event(client, "I'm building RagParser.")
    _admit(client, first.json()["id"])
    second = _create_event(client, "I'm building RagParser.")
    admitted = _admit(client, second.json()["id"])
    store = [r for r in admitted.json()["results"] if r["decision"] == "STORE"][0]
    assert store["deduplication"]["relationship"] == "DUPLICATE"

    rows = client.get(f"/api/v1/events/{second.json()['id']}/deduplication")
    assert rows.status_code == 200
    body = rows.json()
    assert body
    assert body[0]["relationship"] == "DUPLICATE"
    assert body[0]["matched_memory_id"] is not None


def test_idempotent_event_replay_no_extra_dedup(client, db_session):
    event = _create_event(client, "I'm building RagParser.")
    first = _admit(client, event.json()["id"])
    second = _admit(client, event.json()["id"])
    assert second.json()["idempotent_replay"] is True
    assert first.json()["results"][0]["deduplication"]["relationship"] == "NEW"

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Memory)) == 1
        assert session.scalar(select(func.count()).select_from(MemoryDeduplicationDecision)) == 1
        assert session.scalar(select(func.count()).select_from(MemoryReinforcement)) == 0


def test_new_memory_gets_embedding_duplicate_does_not(client, db_session):
    first = _create_event(client, "I'm building RagParser.")
    a1 = _admit(client, first.json()["id"])
    memory_id = a1.json()["results"][0]["memory_id"]

    second = _create_event(client, "I'm building RagParser.")
    a2 = _admit(client, second.json()["id"])
    assert a2.json()["results"][0]["deduplication"]["created_new_memory"] is False

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        embeddings = list(session.scalars(select(MemoryEmbedding)).all())
        assert len(embeddings) == 1
        assert embeddings[0].memory_id == memory_id


def test_store_worthy_duplicate_keeps_admission_store(client, db_session):
    e1 = _create_event(client, "I'm building RagParser.")
    _admit(client, e1.json()["id"])
    e2 = _create_event(client, "I'm building RagParser.")
    body = _admit(client, e2.json()["id"]).json()
    store = [r for r in body["results"] if r["decision"] == "STORE"]
    assert store
    assert store[0]["decision"] == "STORE"
    assert store[0]["memory_id"] is None
    assert store[0]["deduplication"]["relationship"] == "DUPLICATE"

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        audits = list(
            session.scalars(
                select(MemoryAdmission).where(MemoryAdmission.event_id == e2.json()["id"])
            ).all()
        )
        assert audits
        assert audits[0].decision == "STORE"
        assert audits[0].created_memory_id is None


def test_transaction_rollback_on_new_memory_failure(engine):
    class BoomEmbed(FakeEmbeddingProvider):
        def embed_text(self, text: str) -> list[float]:
            raise EmbeddingError("embed fail")

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with Session() as session:
        # Seed an unrelated memory so path isn't short-circuited oddly
        MemoryService(session, embedding_provider=FakeEmbeddingProvider()).create(
            MemoryCreate(
                namespace="personal",
                user_id="user-1",
                content="Unrelated seed about cats.",
                memory_type=MemoryType.fact,
            )
        )
        session.commit()

    with Session() as session:
        evt = EventService(session).create(
            EventCreate(
                namespace="personal",
                user_id="user-1",
                role=EventRole.user,
                content="Munin uses exotic widgets.",
            )
        )
        svc = DeduplicationService(session, embedding_provider=BoomEmbed())
        try:
            svc.process_candidate(
                event=evt,
                admission_id=None,
                content="Munin uses exotic widgets.",
                memory_type=MemoryType.fact,
                importance=0.8,
                confidence=0.9,
            )
            session.commit()
            raise AssertionError("expected failure")
        except Exception:
            session.rollback()

    with Session() as session:
        # Only the seed memory should remain; no orphaned dedup audit for failed NEW
        memories = list(session.scalars(select(Memory)).all())
        assert len(memories) == 1
        assert "cats" in memories[0].content
        assert list(session.scalars(select(MemoryDeduplicationDecision)).all()) == []
        assert list(session.scalars(select(MemoryReinforcement)).all()) == []


def test_policy_low_confidence_helper():
    outcome = apply_relationship_policy(
        RelationshipAnalysis(
            relationship=RelationshipType.DUPLICATE,
            confidence=0.4,
        ),
        config=DedupPolicyConfig(min_relationship_confidence=0.70),
    )
    assert outcome.relationship == RelationshipType.NEW


def test_dedup_evaluation_fixture_quality():
    metrics = evaluate_cases()
    assert metrics["total"] >= 25
    assert metrics["false_merge_count"] == 0
    assert metrics["accuracy"] >= 0.85
