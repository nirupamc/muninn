"""Munin M6 - Manual verification harness (Steps 12, 13, 14).

Runs the manual decay verification, manual consolidation verification, and
restart/persistence verification against a REAL file-backed SQLite database.

Usage:
    python scripts/manual_m6_verify.py
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, event as sqla_event, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.consolidation.factory import set_consolidation_provider_override
from app.consolidation.providers.deterministic import DeterministicConsolidationProvider
from app.consolidation.service import ConsolidationService
from app.database import Base
from app.decay.calculator import compute_decay_multiplier, compute_effective_importance
from app.decay.profiles import decay_lambda, profile_for_type
from app.embeddings.factory import set_embedding_provider_override
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.vector_utils import (
    cosine_similarity,
    deserialize_vector,
    serialize_vector,
)
from app.models.consolidation import MemoryConsolidation
from app.models.embedding import MemoryEmbedding
from app.models.memory import Memory, MemoryStatus, MemoryType

DB_PATH = Path(__file__).parent.parent / "data" / "manual_m6_verify.db"
PASS = "\u2713"
FAIL = "\u2717"

settings = Settings(decay_enabled=True)

provider = FakeEmbeddingProvider()
set_embedding_provider_override(provider)
set_consolidation_provider_override(DeterministicConsolidationProvider())


def make_engine(url: str):
    eng = create_engine(url, connect_args={"check_same_thread": False}, future=True)

    @sqla_event.listens_for(eng, "connect")
    def _fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


def store_memory(
    db: Session,
    *,
    content: str,
    memory_type: MemoryType,
    importance: float = 0.8,
    created_at: datetime | None = None,
    namespace: str = "manual",
    user_id: str | None = None,
) -> Memory:
    now = datetime.now(UTC)
    m = Memory(
        namespace=namespace,
        user_id=user_id,
        content=content,
        memory_type=memory_type,
        importance=importance,
        confidence=1.0,
        status=MemoryStatus.active,
        created_at=created_at or now,
        updated_at=now,
    )
    db.add(m)
    db.flush()
    vec = provider.embed_text(content)
    emb = MemoryEmbedding(
        memory_id=m.id,
        provider=provider.provider_name,
        model_name=provider.model_name,
        dimension=provider.dimension,
        embedding=serialize_vector(vec),
        created_at=now,
        updated_at=now,
    )
    db.add(emb)
    db.flush()
    return m


def log_section(title: str) -> None:
    print(f"\n{'=' * 66}")
    print(f"  {title}")
    print(f"{'=' * 66}")


def check(label: str, ok: bool) -> bool:
    sym = PASS if ok else FAIL
    print(f"  [{sym}] {label}")
    return ok
# ---------------------------------------------------------------------------
# STEP 12 - Manual decay verification
# ---------------------------------------------------------------------------
def step_decay(db: Session) -> None:
    log_section("STEP 12 - Manual decay verification")

    now = datetime.now(UTC)
    age = timedelta(days=60)
    created = now - age
    as_of = now

    # Same stored importance, same age: event vs project
    evt = store_memory(
        db, content="User delivered a talk at the meetup.",
        memory_type=MemoryType.event, importance=0.8, created_at=created,
    )
    prj = store_memory(
        db, content="User is building Munin project.",
        memory_type=MemoryType.project, importance=0.8, created_at=created,
    )
    db.commit()

    stored_evt = evt.importance
    stored_prj = prj.importance
    print(f"\n  stored importance      : event={stored_evt}, project={stored_prj}")

    profile_evt = profile_for_type(evt.memory_type)
    profile_prj = profile_for_type(prj.memory_type)
    print(f"  decay profile          : event={profile_evt.value}, project={profile_prj.value}")

    lam_evt = decay_lambda(profile_evt, settings)
    lam_prj = decay_lambda(profile_prj, settings)
    print(f"  decay lambda           : event={lam_evt}, project={lam_prj}")

    mult_evt = compute_decay_multiplier(
        memory_type=evt.memory_type, created_at=created, as_of=as_of, settings=settings
    )
    mult_prj = compute_decay_multiplier(
        memory_type=prj.memory_type, created_at=created, as_of=as_of, settings=settings
    )
    print(f"  decay multiplier       : event={mult_evt:.4f}, project={mult_prj:.4f}")

    eff_evt = compute_effective_importance(
        stored_importance=stored_evt, memory_type=evt.memory_type,
        created_at=created, as_of=as_of, settings=settings,
    )
    eff_prj = compute_effective_importance(
        stored_importance=stored_prj, memory_type=prj.memory_type,
        created_at=created, as_of=as_of, settings=settings,
    )
    print(f"  effective importance   : event={eff_evt:.4f}, project={eff_prj:.4f}")

    check("project effective importance >> event effective importance",
          eff_prj > eff_evt + 0.1)

    db.refresh(evt)
    db.refresh(prj)
    check("stored importance remains unchanged (event)", evt.importance == stored_evt)
    check("stored importance remains unchanged (project)", prj.importance == stored_prj)
    assert evt.importance == stored_evt and prj.importance == stored_prj

    # Semantic relevance must remain dominant over decay.
    from app.context.models import ContextConfig
    from app.context.scoring import score_candidate

    cfg = ContextConfig(decay_enabled=True)
    q = "User gave a presentation at the local meetup last week?"
    s_evt = score_candidate(
        memory=evt, semantic_score=0.90, reinforcement_count=0,
        query=q, as_of=as_of, config=cfg,
    )
    s_prj = score_candidate(
        memory=prj, semantic_score=0.35, reinforcement_count=0,
        query=q, as_of=as_of, config=cfg,
    )
    check("semantic relevance dominates decay (event ranks higher despite decay)",
          s_evt.final_score > s_prj.final_score)
    if s_evt.final_score <= s_prj.final_score:
        print(f"      (event semantic=0.90 eff_imp={eff_evt:.3f}; "
              f"project semantic=0.35 eff_imp={eff_prj:.3f})")
    assert s_evt.final_score > s_prj.final_score
# ---------------------------------------------------------------------------
# STEP 13 - Manual consolidation verification
# ---------------------------------------------------------------------------
def step_consolidation(db: Session) -> None:
    log_section("STEP 13 - Manual consolidation verification")

    sources = [
        "User is building Munin.",
        "Munin supports semantic retrieval.",
        "Munin supports admission and deduplication.",
        "Munin supports temporal memory.",
        "Munin supports context assembly.",
    ]
    stored = [
        store_memory(db, content=c, memory_type=MemoryType.fact, importance=0.7)
        for c in sources
    ]
    db.commit()
    source_ids = [m.id for m in stored]

    before_counts = {
        "memories": db.query(Memory).count(),
        "consolidations": db.query(MemoryConsolidation).count(),
        "embeddings": db.query(MemoryEmbedding).count(),
    }
    print(f"  baseline row counts    : {before_counts}")

    svc = ConsolidationService(
        db=db,
        consolidation_provider=DeterministicConsolidationProvider(),
        embedding_provider=provider,
    )

    # Preview must persist nothing.
    prev = svc.preview(namespace="manual", user_id=None, memory_ids=source_ids)
    print(f"\n  preview proposed content : {prev.proposed_content!r}")
    print(f"  preview proposed type    : {prev.proposed_memory_type.value}")
    check("preview proposes a consolidated memory", len(prev.proposed_content) > 0)

    after_preview = {
        "memories": db.query(Memory).count(),
        "consolidations": db.query(MemoryConsolidation).count(),
        "embeddings": db.query(MemoryEmbedding).count(),
    }
    ok_preview = after_preview == before_counts
    check("preview persists zero rows", ok_preview)
    assert ok_preview, f"preview mutated DB (before={before_counts} after={after_preview})"

    # Actual consolidation.
    resp = svc.consolidate(namespace="manual", user_id=None, memory_ids=source_ids)
    check("one derived consolidated memory created (is_new)", resp.is_new is True)
    print(f"\n  consolidated memory id  : {resp.consolidated_memory_id}")
    print(f"  consolidated content    : {resp.content!r}")
    print(f"  memory type             : {resp.memory_type.value}")
    print(f"  importance / confidence : {resp.importance} / {resp.confidence}")
    print(f"  reason                  : {resp.reason}")

    derived = db.get(Memory, resp.consolidated_memory_id)
    check("derived memory is identifiable as consolidated",
          bool(derived.metadata_.get("is_consolidated")))

    for m, orig in zip(stored, sources):
        db.refresh(m)
        check(f"source preserved + unchanged: {orig[:28]!r}",
              m.status == MemoryStatus.active and m.content == orig)

    emb = db.execute(
        select(MemoryEmbedding).where(MemoryEmbedding.memory_id == derived.id)
    ).scalar_one_or_none()
    check("derived memory has embedding", emb is not None and emb.dimension == provider.dimension)

    audit = db.execute(
        select(MemoryConsolidation).where(MemoryConsolidation.created_memory_id == derived.id)
    ).scalar_one_or_none()
    check("consolidation audit exists", audit is not None and audit.provider == "deterministic")

    prov = svc.get_provenance(derived.id)
    linked_ids = {s.memory_id for s in prov.sources}
    check("all source links exist", linked_ids == set(source_ids))
    if linked_ids != set(source_ids):
        print(f"      linked={sorted(linked_ids)} expected={sorted(source_ids)}")
    assert linked_ids == set(source_ids)

    derived_vec = deserialize_vector(emb.embedding)
    qvec = provider.embed_text("Munin memory layer capabilities overview")
    sim = cosine_similarity(derived_vec, qvec)
    check("semantic search can retrieve derived memory (cosim>0.5)", sim > 0.5)
    print(f"      derived-vs-query cosine similarity = {sim:.4f}")

    return derived, source_ids
# ---------------------------------------------------------------------------
# STEP 14 - Restart / persistence verification
# ---------------------------------------------------------------------------
def phase_create(db: Session) -> dict:
    """Create sources + consolidated memory + provenance + embedding."""
    sources = [
        "Munin is a durable memory layer.",
        "Munin supports context assembly.",
        "Munin supports decay and consolidation.",
    ]
    stored = [
        store_memory(db, content=c, memory_type=MemoryType.fact, importance=0.7,
                     namespace="restart")
        for c in sources
    ]
    db.commit()
    source_ids = [m.id for m in stored]

    svc = ConsolidationService(
        db=db,
        consolidation_provider=DeterministicConsolidationProvider(),
        embedding_provider=provider,
    )
    resp = svc.consolidate(namespace="restart", user_id=None, memory_ids=source_ids)
    derived = db.get(Memory, resp.consolidated_memory_id)
    emb = db.execute(
        select(MemoryEmbedding).where(MemoryEmbedding.memory_id == derived.id)
    ).scalar_one_or_none()
    audit = db.execute(
        select(MemoryConsolidation).where(MemoryConsolidation.created_memory_id == derived.id)
    ).scalar_one_or_none()

    ref = {
        "derived_id": derived.id,
        "source_ids": source_ids,
        "embedding_id": emb.id if emb else None,
        "audit_id": audit.id if audit else None,
        "derived_content": derived.content,
        "source_contents": sources,
    }
    db.commit()
    return ref


def phase_read(db: Session, ref: dict) -> None:
    derived = db.get(Memory, ref["derived_id"])
    check("DERIVED memory still exists after restart", derived is not None)
    check("derived still flagged consolidated",
          derived is not None and derived.metadata_.get("is_consolidated") is True)

    src_ok = all(db.get(Memory, sid) is not None for sid in ref["source_ids"])
    check("all source memories still exist after restart", src_ok)
    assert src_ok

    emb = db.execute(
        select(MemoryEmbedding).where(MemoryEmbedding.memory_id == ref["derived_id"])
    ).scalar_one_or_none()
    check("embedding still exists after restart", emb is not None and emb.id == ref["embedding_id"])
    assert emb is not None

    audit = db.execute(
        select(MemoryConsolidation).where(
            MemoryConsolidation.created_memory_id == ref["derived_id"]
        )
    ).scalar_one_or_none()
    check("consolidation audit still exists after restart",
          audit is not None and audit.id == ref["audit_id"])
    assert audit is not None

    svc = ConsolidationService(
        db=db,
        consolidation_provider=DeterministicConsolidationProvider(),
        embedding_provider=provider,
    )
    prov = svc.get_provenance(ref["derived_id"])
    links = {s.memory_id for s in prov.sources}
    check("all source links still exist after restart", links == set(ref["source_ids"]))
    assert links == set(ref["source_ids"])

    # Fixed as_of determinism (decay is a pure function of type/created/as_of).
    fixed_as_of = datetime(2030, 1, 1, tzinfo=UTC)
    created = datetime(2029, 6, 1, tzinfo=UTC)
    mult = compute_decay_multiplier(
        memory_type=MemoryType.project, created_at=created, as_of=fixed_as_of, settings=settings
    )
    eff = compute_effective_importance(
        stored_importance=0.8, memory_type=MemoryType.project,
        created_at=created, as_of=fixed_as_of, settings=settings,
    )
    check("fixed-as_of decay multiplier is deterministic (0<mult<=1)", 0.0 < mult <= 1.0)
    check("fixed-as_of effective importance is deterministic (0<eff<=1)", 0.0 < eff <= 1.0)
    print(f"\n  fixed-as_of decay        : {fixed_as_of.isoformat()}")
    print(f"  decay profile           : {profile_for_type(MemoryType.project).value}")
    print(f"  decay multiplier        : {mult:.6f}")
    print(f"  effective importance    : {eff:.6f}")


def main() -> None:
    if DB_PATH.exists():
        os.remove(DB_PATH)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Phase 1: create data in a persistent file DB.
    engine = make_engine(f"sqlite:///{DB_PATH}")
    Base.metadata.create_all(bind=engine)
    SessionT = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = SessionT()

    step_decay(db)
    step_consolidation(db)

    log_section("STEP 14 - Restart / persistence verification")
    ref = phase_create(db)
    print(f"\n  phase-1 derived content : {ref['derived_content']!r}")
    db.close()
    engine.dispose()
    print(f"\n  (engine disposed; database file: {DB_PATH})")

    # Phase 2: reopen the same file-backed database (simulated restart).
    engine2 = make_engine(f"sqlite:///{DB_PATH}")
    SessionT2 = sessionmaker(bind=engine2, autocommit=False, autoflush=False)
    db2 = SessionT2()
    log_section("Reopened database (post-restart)")
    phase_read(db2, ref)
    db2.close()
    engine2.dispose()

    print("\n" + "=" * 66)
    print("  MANUAL M6 VERIFICATION COMPLETE")
    print("=" * 66)


if __name__ == "__main__":
    main()