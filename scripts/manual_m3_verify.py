"""Manual M3 verification sequence against a temporary SQLite DB."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import sessionmaker

# Use a fresh file DB for restart simulation
tmp = Path(tempfile.mkdtemp()) / "munin_m3_verify.db"
os.environ["DATABASE_URL"] = f"sqlite:///{tmp.as_posix()}"

from app.config import get_settings

get_settings.cache_clear()

from app.admission.factory import get_admission_provider, set_admission_provider_override
from app.admission.providers.deterministic import DeterministicAdmissionProvider
from app.database import Base, get_db, engine as app_engine
from app.deduplication.factory import get_relationship_provider, set_relationship_provider_override
from app.deduplication.providers.deterministic import DeterministicRelationshipProvider
from app.embeddings.factory import get_embedding_provider, set_embedding_provider_override
from app.embeddings.fake import FakeEmbeddingProvider
from app.main import create_app
from app.models import Memory, MemoryDeduplicationDecision, MemoryReinforcement
from app.deduplication.service import DeduplicationService
from app.models.event import EventRole
from app.models.memory import MemoryType
from app.schemas.event import EventCreate
from app.services.event_service import EventService

# Recreate schema on the temp DB
from app import database as dbmod

dbmod.engine = create_engine(
    f"sqlite:///{tmp.as_posix()}",
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(dbmod.engine, "connect")
def _fk(conn, _):  # noqa: ARG001
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


dbmod.SessionLocal.configure(bind=dbmod.engine)
Base.metadata.create_all(bind=dbmod.engine)

fake = FakeEmbeddingProvider()
adm = DeterministicAdmissionProvider()
rel = DeterministicRelationshipProvider()
set_embedding_provider_override(fake)
set_admission_provider_override(adm)
set_relationship_provider_override(rel)

app = create_app()
TestingSessionLocal = sessionmaker(bind=dbmod.engine, autocommit=False, autoflush=False)


def _override_db():
    s = TestingSessionLocal()
    try:
        yield s
    finally:
        s.close()


app.dependency_overrides[get_db] = _override_db
app.dependency_overrides[get_embedding_provider] = lambda: fake
app.dependency_overrides[get_admission_provider] = lambda: adm
app.dependency_overrides[get_relationship_provider] = lambda: rel

utterances = [
    "I'm building RagParser.",
    "RagParser is the document parser I'm working on.",
    "I'm still working on RagParser.",
    "RagParser uses Python.",
    "I prefer Python.",
    "Python remains my default backend language.",
    "I do not prefer Python anymore.",
]

print(f"DB={tmp}")
with TestClient(app) as client:
    results = []
    for text in utterances:
        ev = client.post(
            "/api/v1/events",
            json={
                "namespace": "personal",
                "user_id": "user-1",
                "role": "user",
                "content": text,
            },
        )
        eid = ev.json()["id"]
        adm_resp = client.post(f"/api/v1/events/{eid}/admit").json()
        for r in adm_resp["results"]:
            if r["decision"] != "STORE":
                continue
            dedup = r.get("deduplication") or {}
            results.append(
                {
                    "utterance": text,
                    "candidate": r.get("content"),
                    "relationship": dedup.get("relationship"),
                    "created": dedup.get("created_new_memory"),
                    "memory_id": r.get("memory_id"),
                    "matched": dedup.get("matched_memory_id"),
                }
            )
            print(
                f"- {text!r}\n"
                f"  candidate={r.get('content')!r}\n"
                f"  relationship={dedup.get('relationship')} "
                f"created={dedup.get('created_new_memory')}"
            )

    # Supplement: force paraphrase/reinforcement/opposite candidates via service
    # when M2 extraction normalizes away the intended wording.
    with TestingSessionLocal() as session:
        svc = DeduplicationService(session, embedding_provider=fake, relationship_provider=rel)

        def run(content: str, mtype: MemoryType):
            evt = EventService(session).create(
                EventCreate(
                    namespace="personal",
                    user_id="user-1",
                    role=EventRole.user,
                    content=content,
                )
            )
            out = svc.process_candidate(
                event=evt,
                admission_id=None,
                content=content,
                memory_type=mtype,
                importance=0.85,
                confidence=0.9,
            )
            session.commit()
            print(
                f"[direct] {content!r} -> {out.relationship.value} "
                f"created={out.created_new_memory}"
            )
            return out

        # Ensure paraphrase duplicate against existing RagParser memory
        run("RagParser is a project the user is currently working on.", MemoryType.project)
        run("Python is still the user's default backend language.", MemoryType.preference)
        run("User does not prefer Python.", MemoryType.preference)

    search = client.post(
        "/api/v1/memories/search",
        json={"query": "RagParser project", "namespace": "personal", "user_id": "user-1", "limit": 5},
    )
    print("search_count", search.json()["count"])

    with TestingSessionLocal() as session:
        mem_count = session.scalar(select(func.count()).select_from(Memory))
        dedup_count = session.scalar(select(func.count()).select_from(MemoryDeduplicationDecision))
        reinf_count = session.scalar(select(func.count()).select_from(MemoryReinforcement))
        print(f"memories={mem_count} dedup_audits={dedup_count} reinforcements={reinf_count}")
        for m in session.scalars(select(Memory).order_by(Memory.created_at)).all():
            print(f"  MEM {m.memory_type.value}: {m.content!r} source={m.source_event_id}")

print("\n--- RESTART SIMULATION ---")
# Clear app overrides / caches and reopen same DB file
app.dependency_overrides.clear()
set_embedding_provider_override(None)
set_admission_provider_override(None)
set_relationship_provider_override(None)

engine2 = create_engine(f"sqlite:///{tmp.as_posix()}", future=True)
Session2 = sessionmaker(bind=engine2, autocommit=False, autoflush=False)
with Session2() as session:
    mem_count = session.scalar(select(func.count()).select_from(Memory))
    dedup_count = session.scalar(select(func.count()).select_from(MemoryDeduplicationDecision))
    reinf_count = session.scalar(select(func.count()).select_from(MemoryReinforcement))
    print(f"after_restart memories={mem_count} dedup={dedup_count} reinf={reinf_count}")
    assert mem_count >= 1
    assert dedup_count >= 1

print("OK")
print(json.dumps({"db": str(tmp)}, indent=2))
