"""M4.1 — M3/M4 boundary regression tests."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.deduplication.evaluate import evaluate_boundary_cases
from app.deduplication.models import DedupReasonCode
from app.deduplication.policy import DedupPolicyConfig, apply_relationship_policy
from app.deduplication.providers.deterministic import DeterministicRelationshipProvider
from app.deduplication.state_change import contains_state_change_signal
from app.models import Memory, MemoryTemporalDecision
from app.models.memory import MemoryStatus, MemoryType


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
        "memory_type": "fact",
        "importance": 0.9,
        "confidence": 1.0,
    }
    payload.update(overrides)
    return client.post("/api/v1/memories", json=payload)


def _classify(candidate: str, existing: str, *, ctype=MemoryType.fact, etype=MemoryType.fact):
    provider = DeterministicRelationshipProvider()
    analysis = provider.classify(
        candidate=candidate,
        existing_memory=existing,
        candidate_type=ctype,
        existing_type=etype,
    )
    return apply_relationship_policy(analysis, config=DedupPolicyConfig())


def test_state_change_signal_helper():
    assert contains_state_change_signal("Munin switched from SQLite to PostgreSQL.")
    assert contains_state_change_signal("User no longer uses SQLite.")
    assert contains_state_change_signal("User now prefers local models.")
    assert not contains_state_change_signal("User still prefers Python.")
    assert not contains_state_change_signal("Munin still uses SQLite.")


def test_switch_database_m3_new():
    outcome = _classify(
        "Munin switched from SQLite to PostgreSQL.",
        "Munin uses SQLite.",
    )
    assert outcome.relationship.value == "NEW"
    assert DedupReasonCode.STATE_CHANGE_REQUIRES_TEMPORAL_ANALYSIS in outcome.reason_codes


def test_migrate_database_m3_new():
    outcome = _classify(
        "Munin migrated from SQLite to PostgreSQL.",
        "Munin uses SQLite.",
    )
    assert outcome.relationship.value == "NEW"


def test_no_longer_m3_new():
    outcome = _classify("User no longer uses SQLite.", "User uses SQLite.")
    assert outcome.relationship.value == "NEW"


def test_stopped_using_m3_new():
    outcome = _classify("User stopped using SQLite.", "User uses SQLite.")
    assert outcome.relationship.value == "NEW"


def test_now_prefers_m3_new():
    outcome = _classify(
        "User now prefers local models.",
        "User prefers OpenAI.",
        ctype=MemoryType.preference,
        etype=MemoryType.preference,
    )
    assert outcome.relationship.value == "NEW"


def test_used_to_prefer_m3_new():
    outcome = _classify(
        "User used to prefer JavaScript.",
        "User prefers JavaScript.",
        ctype=MemoryType.preference,
        etype=MemoryType.preference,
    )
    assert outcome.relationship.value == "NEW"


def test_negated_preference_m3_new():
    outcome = _classify(
        "User does not prefer Python anymore.",
        "User prefers Python.",
        ctype=MemoryType.preference,
        etype=MemoryType.preference,
    )
    assert outcome.relationship.value == "NEW"


def test_replaced_wording_m3_new():
    outcome = _classify(
        "PostgreSQL replaced SQLite in Munin.",
        "Munin uses SQLite.",
    )
    assert outcome.relationship.value == "NEW"


def test_still_prefers_m3_reinforces():
    outcome = _classify(
        "User still prefers Python.",
        "User prefers Python.",
        ctype=MemoryType.preference,
        etype=MemoryType.preference,
    )
    assert outcome.relationship.value == "REINFORCES"


def test_paraphrase_still_duplicates():
    outcome = _classify(
        "RagParser is a project the user is working on.",
        "User is building RagParser.",
        ctype=MemoryType.project,
        etype=MemoryType.project,
    )
    assert outcome.relationship.value == "DUPLICATE"


def test_related_new_fact_m3_new():
    outcome = _classify(
        "Munin uses FastAPI.",
        "User is building Munin.",
        ctype=MemoryType.fact,
        etype=MemoryType.project,
    )
    assert outcome.relationship.value == "NEW"


def test_boundary_fixture_evaluation():
    metrics = evaluate_boundary_cases()
    assert metrics["false_duplicate_on_temporal_change_count"] == 0
    assert metrics["state_change_swallowed_count"] == 0
    assert metrics["accuracy"] == 1.0


def test_sqlite_to_postgresql_end_to_end(client, db_session):
    """Exact M4 manual failure: switch must reach M4 and supersede SQLite memory."""
    first = _create_event(client, "Munin uses SQLite.")
    a1 = _admit(client, first.json()["id"])
    assert a1.status_code == 200
    sqlite_id = a1.json()["results"][0]["memory_id"]
    assert sqlite_id

    second = _create_event(client, "Munin switched from SQLite to PostgreSQL.")
    a2 = _admit(client, second.json()["id"])
    assert a2.status_code == 200
    store = [r for r in a2.json()["results"] if r["decision"] == "STORE"][0]

    assert store["deduplication"]["relationship"] == "NEW"
    assert "STATE_CHANGE_REQUIRES_TEMPORAL_ANALYSIS" in store["deduplication"]["reason_codes"]
    assert store["temporal"] is not None
    assert store["temporal"]["relationship"] in {"SUPERSEDES", "UPDATES"}

    pg_id = store["memory_id"]
    sqlite = client.get(f"/api/v1/memories/{sqlite_id}").json()
    pg = client.get(f"/api/v1/memories/{pg_id}").json()

    assert sqlite["status"] == "superseded"
    assert sqlite["valid_until"] is not None
    assert pg["status"] == "active"
    assert pg["valid_from"] is not None
    assert pg["valid_from"] == sqlite["valid_until"]


def test_namespace_isolation_state_change(client):
    _store_memory(
        client,
        "Munin uses SQLite.",
        namespace="team-a",
    )
    evt = _create_event(
        client,
        "Munin switched from SQLite to PostgreSQL.",
        namespace="team-b",
    )
    a = _admit(client, evt.json()["id"])
    store = [r for r in a.json()["results"] if r["decision"] == "STORE"][0]
    assert store["deduplication"]["relationship"] == "NEW"
    assert store["temporal"]["relationship"] == "NEW"


def test_m3_reinforces_skips_m4_still_uses(client):
    first = _create_event(client, "Munin uses SQLite.")
    a1 = _admit(client, first.json()["id"])
    old_id = a1.json()["results"][0]["memory_id"]

    second = _create_event(client, "Munin still uses SQLite.")
    a2 = _admit(client, second.json()["id"])
    store = [r for r in a2.json()["results"] if r["decision"] == "STORE"][0]
    assert store["deduplication"]["relationship"] == "REINFORCES"
    assert store["temporal"] is None
    assert client.get(f"/api/v1/memories/{old_id}").json()["status"] == "active"


def test_idempotent_replay_after_boundary_fix(client, db_session):
    evt = _create_event(client, "Munin uses SQLite.")
    event_id = evt.json()["id"]
    _admit(client, event_id)
    switch = _create_event(client, "Munin switched from SQLite to PostgreSQL.")
    switch_id = switch.json()["id"]
    _admit(client, switch_id)

    engine = db_session.get_bind()
    Session = sessionmaker(bind=engine)
    with Session() as session:
        temporal_before = session.scalar(
            select(func.count()).select_from(MemoryTemporalDecision)
        )
        memory_before = session.scalar(select(func.count()).select_from(Memory))

    replay = _admit(client, switch_id)
    assert replay.json()["idempotent_replay"] is True

    with Session() as session:
        temporal_after = session.scalar(
            select(func.count()).select_from(MemoryTemporalDecision)
        )
        memory_after = session.scalar(select(func.count()).select_from(Memory))
    assert temporal_after == temporal_before
    assert memory_after == memory_before
    assert memory_after == 2
    assert temporal_after == 2


def test_user_isolation_state_change(client):
    _store_memory(
        client,
        "Munin uses SQLite.",
        user_id="user-a",
    )
    evt = _create_event(
        client,
        "Munin switched from SQLite to PostgreSQL.",
        user_id="user-b",
    )
    a = _admit(client, evt.json()["id"])
    store = [r for r in a.json()["results"] if r["decision"] == "STORE"][0]
    assert store["deduplication"]["relationship"] == "NEW"
    assert store["temporal"]["relationship"] == "NEW"
