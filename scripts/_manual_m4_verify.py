"""Manual M4 verification script (dev only)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.admission.factory import get_admission_provider, set_admission_provider_override
from app.admission.providers.deterministic import DeterministicAdmissionProvider
from app.database import Base, get_db
from app.deduplication.factory import get_relationship_provider, set_relationship_provider_override
from app.deduplication.providers.deterministic import DeterministicRelationshipProvider
from app.embeddings.factory import get_embedding_provider, set_embedding_provider_override
from app.embeddings.fake import FakeEmbeddingProvider
from app.main import create_app
from app.models import Memory  # noqa: F401
from app.models.memory import MemoryStatus
from app.temporal.factory import get_temporal_provider, set_temporal_provider_override
from app.temporal.providers.deterministic import DeterministicTemporalProvider


def main() -> None:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _fk(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=eng)
    session_local = sessionmaker(bind=eng)

    fp = FakeEmbeddingProvider()
    ap = DeterministicAdmissionProvider()
    rp = DeterministicRelationshipProvider()
    tp = DeterministicTemporalProvider()
    app = create_app()
    set_embedding_provider_override(fp)
    set_admission_provider_override(ap)
    set_relationship_provider_override(rp)
    set_temporal_provider_override(tp)

    def override_db():
        session = session_local()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_embedding_provider] = lambda: fp
    app.dependency_overrides[get_admission_provider] = lambda: ap
    app.dependency_overrides[get_relationship_provider] = lambda: rp
    app.dependency_overrides[get_temporal_provider] = lambda: tp

    client = TestClient(app)
    base = {
        "namespace": "personal",
        "user_id": "user-1",
        "agent_id": "cursor",
        "session_id": "s1",
        "role": "user",
    }

    def admit(text: str) -> tuple[str | None, str | None, str | None]:
        event_id = client.post("/api/v1/events", json={**base, "content": text}).json()["id"]
        result = client.post(f"/api/v1/events/{event_id}/admit").json()["results"][0]
        dedup = result.get("deduplication") or {}
        temporal = result.get("temporal") or {}
        return dedup.get("relationship"), temporal.get("relationship"), result.get("memory_id")

    scenarios = [
        ("I prefer OpenAI APIs.", "1 expect NEW"),
        ("I still prefer OpenAI APIs.", "2 expect M3 REINFORCES"),
        ("I now prefer local models.", "3 expect SUPERSEDES"),
        ("I use SQLite for Munin.", "4 expect NEW"),
        ("I switched Munin from SQLite to PostgreSQL.", "5 expect SUPERSEDES/SWITCH"),
        ("I prefer Python.", "6 expect NEW"),
        ("I prefer Rust.", "7 expect CONTRADICTS"),
        ("I do not prefer Python anymore.", "8 expect SUPERSEDES (negated pref)"),
    ]

    for text, label in scenarios:
        m3, m4, memory_id = admit(text)
        print(f"{label}: M3={m3} M4={m4 or '-'} memory_id={memory_id}")

    with session_local() as session:
        active = session.scalars(
            select(Memory).where(Memory.status == MemoryStatus.active)
        ).all()
        superseded = session.scalars(
            select(Memory).where(Memory.status == MemoryStatus.superseded)
        ).all()
        print(f"\nDB: active={len(active)} superseded={len(superseded)}")
        for mem in active + superseded:
            print(
                f"  [{mem.status.value}] {mem.content[:60]} "
                f"valid_from={mem.valid_from} valid_until={mem.valid_until}"
            )


if __name__ == "__main__":
    main()
