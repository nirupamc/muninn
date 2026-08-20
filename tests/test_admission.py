"""M2 memory admission tests."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.admission.base import AdmissionError, AdmissionProvider
from app.admission.evaluate import evaluate_cases
from app.admission.models import (
    AdmissionCandidate,
    CandidateAnalysis,
    ReasonCode,
)
from app.admission.privacy import REDACTED_PLACEHOLDER, contains_secret_like_data
from app.admission.rules import AdmissionPolicyConfig, apply_admission_policy
from app.admission.scoring import compute_admission_score
from app.admission.service import AdmissionService
from app.embeddings.base import EmbeddingError
from app.embeddings.fake import FakeEmbeddingProvider
from app.models import Memory, MemoryAdmission, MemoryType
from app.repositories.embedding_repository import EmbeddingRepository


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


def test_project_memory_store(client, db_session):
    event = _create_event(client, "I'm building RagParser.")
    assert event.status_code == 201
    admitted = _admit(client, event.json()["id"])
    assert admitted.status_code == 200
    body = admitted.json()
    assert body["stored"] >= 1
    stored = [r for r in body["results"] if r["decision"] == "STORE"]
    assert stored[0]["memory_type"] == "project"
    memory_id = stored[0]["memory_id"]
    assert memory_id

    mem = client.get(f"/api/v1/memories/{memory_id}")
    assert mem.status_code == 200
    assert mem.json()["source_event_id"] == event.json()["id"]
    assert mem.json()["namespace"] == "personal"

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        emb = EmbeddingRepository(session).get_by_memory_id(memory_id)
        assert emb is not None


def test_preference_goal_decision(client):
    cases = [
        ("I prefer Python for backend development.", "preference"),
        ("My goal is to publish an article about agent memory.", "goal"),
        ("We decided to use SQLite for Munin M0.", "decision"),
    ]
    for content, expected_type in cases:
        event = _create_event(client, content)
        admitted = _admit(client, event.json()["id"])
        assert admitted.status_code == 200
        stored = [r for r in admitted.json()["results"] if r["decision"] == "STORE"]
        assert stored, content
        assert stored[0]["memory_type"] == expected_type


def test_trivial_and_ephemeral_ignored(client, db_session):
    for content in ("I ate a burger today.", "I'm sleepy right now."):
        event = _create_event(client, content)
        admitted = _admit(client, event.json()["id"])
        assert admitted.status_code == 200
        assert admitted.json()["stored"] == 0
        assert all(r["decision"] == "IGNORE" for r in admitted.json()["results"])

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        assert list(session.scalars(select(Memory)).all()) == []


def test_explicit_remember_high_explicitness(client):
    event = _create_event(client, "Remember that I prefer Python.")
    admitted = _admit(client, event.json()["id"])
    stored = [r for r in admitted.json()["results"] if r["decision"] == "STORE"]
    assert stored
    assert stored[0]["explicitness"] >= 0.9
    assert "EXPLICIT_REMEMBER_REQUEST" in stored[0]["reason_codes"] or stored[0][
        "memory_type"
    ] == "preference"


def test_secret_filtering_no_leak(client, db_session):
    secret = "sk-test-secret-12345678"
    event = _create_event(client, f"Remember my API key: {secret}")
    admitted = _admit(client, event.json()["id"])
    assert admitted.status_code == 200
    body = admitted.json()
    assert body["stored"] == 0
    assert any("SECRET_LIKE_DATA" in r["reason_codes"] for r in body["results"])
    blob = str(body)
    assert secret not in blob
    assert any(r["content"] == REDACTED_PLACEHOLDER for r in body["results"])

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        memories = list(session.scalars(select(Memory)).all())
        audits = list(session.scalars(select(MemoryAdmission)).all())
        assert memories == []
        assert audits
        for row in audits:
            assert row.candidate_content in {REDACTED_PLACEHOLDER, None}
            assert secret not in (row.candidate_content or "")


def test_unsupported_inference_not_love(client):
    event = _create_event(client, "I'm debugging FastAPI.")
    admitted = _admit(client, event.json()["id"])
    texts = " ".join((r.get("content") or "") for r in admitted.json()["results"]).lower()
    assert "love" not in texts
    assert admitted.json()["stored"] == 0


def test_multiple_candidates(client):
    event = _create_event(
        client,
        "I'm building Munin in Python and using SQLite for the first version.",
    )
    admitted = _admit(client, event.json()["id"])
    assert admitted.json()["processed"] >= 2


def test_mixed_relevance(client, db_session):
    event = _create_event(client, "I'm building Munin, and I ate pizza.")
    admitted = _admit(client, event.json()["id"])
    body = admitted.json()
    assert body["stored"] >= 1
    assert body["ignored"] >= 1
    stored_text = " ".join(
        r["content"] for r in body["results"] if r["decision"] == "STORE"
    )
    ignored_text = " ".join(
        (r["content"] or "") for r in body["results"] if r["decision"] == "IGNORE"
    )
    assert "Munin" in stored_text
    assert "pizza" in ignored_text.lower() or body["ignored"] >= 1


def test_idempotency(client, db_session):
    event = _create_event(client, "I'm building RagParser.")
    first = _admit(client, event.json()["id"])
    second = _admit(client, event.json()["id"])
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert first.json()["stored"] == second.json()["stored"]

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        memories = list(session.scalars(select(Memory)).all())
        assert len(memories) == first.json()["stored"]


def test_namespace_user_agent_provenance(client):
    event = _create_event(
        client,
        "I'm building Munin.",
        namespace="ns-a",
        user_id="u-9",
        agent_id="agent-z",
    )
    admitted = _admit(client, event.json()["id"])
    memory_id = next(r["memory_id"] for r in admitted.json()["results"] if r["memory_id"])
    mem = client.get(f"/api/v1/memories/{memory_id}").json()
    assert mem["namespace"] == "ns-a"
    assert mem["user_id"] == "u-9"
    assert mem["agent_id"] == "agent-z"
    assert mem["source_event_id"] == event.json()["id"]


def test_get_admissions(client):
    event = _create_event(client, "I prefer Python for backend development.")
    _admit(client, event.json()["id"])
    listed = client.get(f"/api/v1/events/{event.json()['id']}/admissions")
    assert listed.status_code == 200
    assert len(listed.json()) >= 1
    assert "reason_codes" in listed.json()[0]
    assert "admission_score" in listed.json()[0]


def test_analyze_endpoint_no_persist(client, db_session):
    response = client.post(
        "/api/v1/admission/analyze",
        json={"role": "user", "content": "I'm building Munin."},
    )
    assert response.status_code == 200
    assert response.json()["would_store"] >= 1

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        assert list(session.scalars(select(Memory)).all()) == []
        assert list(session.scalars(select(MemoryAdmission)).all()) == []


def test_threshold_and_confidence_policy():
    high = AdmissionCandidate(
        content="User is building Munin.",
        memory_type=MemoryType.project,
        importance=0.9,
        confidence=0.95,
        future_utility=0.9,
        stability=0.8,
        specificity=0.8,
        explicitness=0.9,
        triviality=0.05,
    )
    score = compute_admission_score(high)
    assert score >= 0.65
    store = apply_admission_policy(
        CandidateAnalysis(
            candidate=high,
            provider_recommendation="STORE",
            reason_codes=[ReasonCode.ONGOING_PROJECT],
        ),
        source_event_content="I'm building Munin.",
        config=AdmissionPolicyConfig(store_threshold=0.65, min_confidence=0.60),
    )
    assert store.decision == "STORE"

    uncertain = high.model_copy(update={"confidence": 0.4})
    ignored = apply_admission_policy(
        CandidateAnalysis(
            candidate=uncertain,
            provider_recommendation="STORE",
            reason_codes=[],
        ),
        source_event_content="I'm building Munin.",
        config=AdmissionPolicyConfig(store_threshold=0.65, min_confidence=0.60),
    )
    assert ignored.decision == "IGNORE"
    assert ReasonCode.TOO_UNCERTAIN in ignored.reason_codes

    weak = AdmissionCandidate(
        content="User ate pizza.",
        memory_type=MemoryType.event,
        importance=0.2,
        confidence=0.9,
        future_utility=0.1,
        stability=0.1,
        specificity=0.4,
        explicitness=0.7,
        triviality=0.9,
    )
    below = apply_admission_policy(
        CandidateAnalysis(
            candidate=weak,
            provider_recommendation="IGNORE",
            reason_codes=[ReasonCode.TRIVIAL],
        ),
        source_event_content="I ate pizza.",
        config=AdmissionPolicyConfig(),
    )
    assert below.decision == "IGNORE"
    assert ReasonCode.BELOW_THRESHOLD in below.reason_codes


def test_privacy_helper():
    assert contains_secret_like_data("Remember my API key: sk-abcdefghijklmnop").is_sensitive
    assert not contains_secret_like_data("I prefer Python.").is_sensitive


def test_provider_failure(client, engine, fake_provider):
    class BoomProvider(AdmissionProvider):
        @property
        def provider_name(self) -> str:
            return "boom"

        @property
        def model_name(self) -> str:
            return "boom"

        def analyze_event(self, *, role: str, content: str, context: dict[str, Any] | None = None):
            raise AdmissionError("down")

    from fastapi.testclient import TestClient

    from app.admission.factory import get_admission_provider, set_admission_provider_override
    from app.database import get_db
    from app.embeddings.factory import get_embedding_provider
    from app.main import create_app

    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    app = create_app()
    boom = BoomProvider()
    set_admission_provider_override(boom)

    def _override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_embedding_provider] = lambda: fake_provider
    app.dependency_overrides[get_admission_provider] = lambda: boom

    with TestClient(app) as test_client:
        event = test_client.post(
            "/api/v1/events",
            json={"namespace": "personal", "role": "user", "content": "I'm building Munin."},
        )
        admitted = test_client.post(f"/api/v1/events/{event.json()['id']}/admit")
        assert admitted.status_code == 503

    set_admission_provider_override(None)
    with TestingSessionLocal() as session:
        assert list(session.scalars(select(Memory)).all()) == []
        assert list(session.scalars(select(MemoryAdmission)).all()) == []


def test_transaction_rollback_on_embedding_failure(engine, admission_provider):
    class BoomEmbed(FakeEmbeddingProvider):
        def embed_text(self, text: str) -> list[float]:
            raise EmbeddingError("embed fail")

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with Session() as session:
        from app.services.event_service import EventService
        from app.schemas.event import EventCreate
        from app.models.event import EventRole

        event = EventService(session).create(
            EventCreate(
                namespace="personal",
                role=EventRole.user,
                content="I'm building Munin.",
            )
        )
        service = AdmissionService(
            session,
            admission_provider=admission_provider,
            embedding_provider=BoomEmbed(),
        )
        try:
            service.admit_event(event.id)
            raise AssertionError("expected failure")
        except Exception:
            pass

    with Session() as session:
        assert list(session.scalars(select(Memory)).all()) == []
        # No successful STORE audit should remain
        audits = list(session.scalars(select(MemoryAdmission)).all())
        assert audits == []


def test_admission_evaluation_fixture_quality():
    metrics = evaluate_cases()
    assert metrics["total"] >= 20
    assert metrics["accuracy"] >= 0.85
    assert metrics["false_positive"] <= 2
