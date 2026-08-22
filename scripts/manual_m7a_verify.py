"""Manual M7A verification script (finalization).

Exercises the full AgentService pipeline (remember/get_context) against
SQLite and verifies the required M7A behaviors A-J, the A->B->C continuity
demo, project/user isolation, idempotency, and file-backed restart
persistence.

Run:
    python scripts/manual_m7a_verify.py
"""

from __future__ import annotations

import sys
import tempfile
import pathlib
from sqlalchemy import create_engine, event as sqla_event
from sqlalchemy.orm import Session, sessionmaker

from app.admission.providers.deterministic import DeterministicAdmissionProvider
from app.admission.service import AdmissionService
from app.admission.privacy import contains_secret_like_data, REDACTED_PLACEHOLDER
from app.agent.models import AgentRememberRequest, AgentContextRequest
from app.agent.service import AgentService
from app.database import Base
from app.deduplication.providers.deterministic import DeterministicRelationshipProvider
from app.embeddings.fake import FakeEmbeddingProvider
from app.models.event import Event, EventRole
from app.models.memory import Memory, MemoryStatus
from app.models.deduplication import MemoryReinforcement

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = PASS if ok else FAIL
    print(f"  [{mark}] {name}" + (f" -- {detail}" if detail else ""))


def make_engine(url: str | None = None):
    eng = create_engine(url or "sqlite://", connect_args={"check_same_thread": False})
    _pragma(eng)
    Base.metadata.create_all(eng)
    return eng


def make_engine_file(path: pathlib.Path):
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    _pragma(eng)
    Base.metadata.create_all(eng)
    return eng


def _pragma(eng):
    @sqla_event.listens_for(eng, "connect")
    def _p(conn, _rec):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def agent_service(db: Session) -> AgentService:
    return AgentService(
        db,
        admission_provider=DeterministicAdmissionProvider(),
        embedding_provider=FakeEmbeddingProvider(),
        relationship_provider=DeterministicRelationshipProvider(),
    )


def mem_count(db: Session, namespace: str) -> int:
    return db.query(Memory).filter(Memory.namespace == namespace).count()


def mem_like(db: Session, namespace: str, like: str) -> int:
    return db.query(Memory).filter(
        Memory.namespace == namespace, Memory.content.like(f"%{like}%")
    ).count()


def ev_count(db: Session, namespace: str) -> int:
    return db.query(Event).filter(Event.namespace == namespace).count()


def lower_has(text: str | None, sub: str) -> bool:
    return bool(text) and sub.lower() in (text or "").lower()


def _create_event(db, ns, uid, aid, content):
    from app.services.event_service import EventService
    from app.schemas.event import EventCreate
    return EventService(db).create(EventCreate(
        namespace=ns, user_id=uid, agent_id=aid,
        role=EventRole.user, content=content))


# ---------------------------------------------------------------------------
# Section 1: behaviors A-J on an isolated in-memory project scope
# ---------------------------------------------------------------------------

def section_behaviors() -> None:
    print("\n== Behaviors A-J ==")
    eng = make_engine()
    Session_ = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    db = Session_()
    svc = agent_service(db)

    NS = "project:munin"

    # A. Explicit remember substantive
    r = svc.remember(AgentRememberRequest(
        namespace=NS, user_id="user-1", agent_id="cursor",
        content="Munin M0 through M6 are complete."))
    check("A explicit remember (substantive) -> STORE",
          r.decision == "STORE" and r.remembered, f"decision={r.decision}")

    # B. Trivial explicit remember -> IGNORE
    r = svc.remember(AgentRememberRequest(
        namespace=NS, user_id="user-1", agent_id="cursor", content="hello"))
    check("B trivial explicit remember -> IGNORE",
          r.decision == "IGNORE" and not r.remembered, f"decision={r.decision}")

    # C. Secret-like explicit remember -> IGNORE + redacted
    priv = contains_secret_like_data("My API key is sk-abcdefgh1234")
    check("C privacy module flags SECRET_LIKE_DATA",
          priv.is_sensitive and priv.reason == "SECRET_LIKE_DATA", str(priv))
    r = svc.remember(AgentRememberRequest(
        namespace=NS, user_id="user-1", agent_id="cursor",
        content="My API key is sk-abcdefgh1234"))
    check("C secret explicit remember -> IGNORE",
          r.decision == "IGNORE" and not r.remembered, f"decision={r.decision}")

    evt = _create_event(db, NS, "user-1", "cursor", "My API key is sk-abcdefgh1234")
    adm = AdmissionService(db, admission_provider=DeterministicAdmissionProvider(),
                           embedding_provider=FakeEmbeddingProvider())
    admit = adm.admit_event(evt.id)
    redacted_ok = any(
        (d.decision == "IGNORE" and d.content == REDACTED_PLACEHOLDER)
        for d in admit.results
    )
    check("C candidate content redacted to [REDACTED]", redacted_ok,
          "admission redacts secret candidate")

    # D. Duplicate paraphrase -> DUPLICATE, no second memory (isolated ns)
    NS_D = "project:dup"
    r1 = svc.remember(AgentRememberRequest(
        namespace=NS_D, user_id="user-1", agent_id="cursor",
        content="Munin uses SQLite for its store."))
    r2 = svc.remember(AgentRememberRequest(
        namespace=NS_D, user_id="user-1", agent_id="cursor",
        content="Munin uses SQLite as the database."))
    check("D paraphrase -> DUPLICATE",
          r2.dedup_relationship == "DUPLICATE", f"dedup={r2.dedup_relationship}")
    check("D no second canonical memory",
          mem_count(db, NS_D) == 1, f"memories={mem_count(db, NS_D)}")

    # E. Reinforcement -> REINFORCES, no second memory, provenance exists
    NS_E = "project:reinf"
    r1 = svc.remember(AgentRememberRequest(
        namespace=NS_E, user_id="user-1", agent_id="cursor",
        content="User is building Munin."))
    r2 = svc.remember(AgentRememberRequest(
        namespace=NS_E, user_id="user-1", agent_id="cursor",
        content="Yes, still building Munin."))
    check("E reinforcement -> REINFORCES",
          r2.dedup_relationship == "REINFORCES", f"dedup={r2.dedup_relationship}")
    check("E no second canonical memory",
          mem_count(db, NS_E) == 1, f"memories={mem_count(db, NS_E)}")
    reinf = db.query(MemoryReinforcement).count()
    check("E reinforcement provenance row exists", reinf >= 1,
          f"reinforcements={reinf}")

    # F. Temporal SQLite -> PostgreSQL through wrapper (isolated ns)
    NS_F = "project:temporal"
    r1 = svc.remember(AgentRememberRequest(
        namespace=NS_F, user_id="user-1", agent_id="cursor",
        content="Munin uses SQLite."))
    r2 = svc.remember(AgentRememberRequest(
        namespace=NS_F, user_id="user-1", agent_id="cursor",
        content="Munin switched from SQLite to PostgreSQL."))
    check("F temporal -> SUPERSEDES/UPDATES",
          r2.temporal_relationship in ("SUPERSEDES", "UPDATES"),
          f"temporal={r2.temporal_relationship}")
    old_mem = db.get(Memory, r1.memory_id) if r1.memory_id else None
    check("F old SQLite memory superseded",
          old_mem is not None and old_mem.status == MemoryStatus.superseded,
          f"status={old_mem.status if old_mem else None}")
    pg_active = db.query(Memory).filter(
        Memory.namespace == NS_F, Memory.content.like("%PostgreSQL%"),
        Memory.status == MemoryStatus.active).count()
    check("F PostgreSQL active", pg_active == 1, f"pg_active={pg_active}")

    # G. Cross-agent continuity (qwen writes, qwen reads; deepseek reads same scope)
    NS_G = "project:gcross"
    svc.remember(AgentRememberRequest(
        namespace=NS_G, user_id="user-1", agent_id="qwen",
        content="Next task is M7 agent integration."))
    ctx_deep = svc.get_context(AgentContextRequest(
        query="agent integration milestone", namespace=NS_G,
        user_id="user-1", agent_id="deepseek"))
    check("G cross-agent (deepseek) retrieves qwen memory",
          lower_has(ctx_deep.text, "agent integration"),
          f"text={ (ctx_deep.text or '')[:60]!r}")

    # H. Project isolation
    svc.remember(AgentRememberRequest(
        namespace="project:ragparser", user_id="user-1", agent_id="cursor",
        content="RagParser uses Tesseract for OCR."))
    ctx_munin = svc.get_context(AgentContextRequest(
        query="OCR tooling?", namespace=NS, user_id="user-1", agent_id="cursor"))
    check("H project:munin does NOT leak RagParser",
          not lower_has(ctx_munin.text, "tesseract"), "no leak")

    # I. User isolation
    svc.remember(AgentRememberRequest(
        namespace=NS, user_id="user-1", agent_id="cursor",
        content="User one private preference."))
    ctx_user2 = svc.get_context(AgentContextRequest(
        query="private preference", namespace=NS, user_id="user-2",
        agent_id="cursor"))
    check("I user-2 does NOT read user-1 memory",
          not lower_has(ctx_user2.text, "private preference"), "no leak")

    # J. Idempotency
    events_before = ev_count(db, NS)
    svc.remember(AgentRememberRequest(
        namespace=NS, user_id="user-1", agent_id="cursor",
        content="Munin adds agent integration.", idempotency_key="ik-final"))
    r2 = svc.remember(AgentRememberRequest(
        namespace=NS, user_id="user-1", agent_id="cursor",
        content="Munin adds agent integration.", idempotency_key="ik-final"))
    check("J idempotent replay flagged", r2.idempotent_replay is True,
          f"replay={r2.idempotent_replay}")
    check("J one event only (no duplicate write)",
          ev_count(db, NS) == events_before + 1,
          f"before={events_before} after={ev_count(db, NS)}")

    db.close()
    eng.dispose()


# ---------------------------------------------------------------------------
# Section 2: A -> B -> C continuity demo
# ---------------------------------------------------------------------------

def section_continuity() -> None:
    print("\n== A -> B -> C continuity ==")
    eng = make_engine()
    Session_ = sessionmaker(bind=eng, autocommit=False, autoflush=False)
    db = Session_()
    svc = agent_service(db)
    NS = "project:munin"

    for c in [
        "Munin M0 through M6 are complete.",
        "Current milestone is M7A Agent Integration.",
        "Frontend must not start until M7A is verified.",
    ]:
        svc.remember(AgentRememberRequest(
            namespace=NS, user_id="user-1", agent_id="cursor",
            content=c, session_id="sess-a"))

    ctx_b = svc.get_context(AgentContextRequest(
        query="Continue where we left off on Munin.",
        namespace=NS, user_id="user-1", agent_id="qwen", session_id="sess-b"))
    text_b = ctx_b.text or ""
    check("B retrieves milestone complete", lower_has(text_b, "complete")
          or lower_has(text_b, "m6"), f"text={text_b[:50]!r}")
    check("B retrieves M7A milestone", lower_has(text_b, "m7a"), "M7A present")
    check("B retrieves frontend gate", lower_has(text_b, "frontend"),
          "frontend gate present")

    svc.remember(AgentRememberRequest(
        namespace=NS, user_id="user-1", agent_id="qwen",
        content="M7A agent continuity verification passed.",
        session_id="sess-b"))

    ctx_c = svc.get_context(AgentContextRequest(
        query="What is the current Munin project state?",
        namespace=NS, user_id="user-1", agent_id="deepseek", session_id="sess-c"))
    text_c = ctx_c.text or ""
    check("C retrieves updated state (continuity passed)",
          lower_has(text_c, "continuity") or lower_has(text_c, "verification")
          or lower_has(text_c, "m7a"), f"text={text_c[:60]!r}")

    db.close()
    eng.dispose()


# ---------------------------------------------------------------------------
# Section 3: restart verification (file-backed SQLite)
# ---------------------------------------------------------------------------

def section_restart() -> None:
    print("\n== Restart verification (file-backed SQLite) ==")
    tmp = pathlib.Path(tempfile.gettempdir()) / "munin_m7a_restart.db"
    if tmp.exists():
        tmp.unlink()

    NS = "project:munin"
    eng1 = make_engine_file(tmp)
    S1 = sessionmaker(bind=eng1, autocommit=False, autoflush=False)
    db1 = S1()
    svc1 = agent_service(db1)
    svc1.remember(AgentRememberRequest(
        namespace=NS, user_id="user-1", agent_id="cursor",
        content="Munin uses FastAPI.", session_id="sess-r1"))
    svc1.remember(AgentRememberRequest(
        namespace=NS, user_id="user-1", agent_id="qwen",
        content="We chose PostgreSQL for Munin persistence.",
        session_id="sess-r2", idempotency_key="ik-restart"))
    ctx1 = svc1.get_context(AgentContextRequest(
        query="fastapi framework", namespace=NS,
        user_id="user-1", agent_id="deepseek"))
    check("restart: pre-close context works",
          lower_has(ctx1.text, "fastapi"), f"text={ (ctx1.text or '')[:50]!r}")
    db1.close()
    eng1.dispose()

    eng2 = make_engine_file(tmp)
    S2 = sessionmaker(bind=eng2, autocommit=False, autoflush=False)
    db2 = S2()
    svc2 = agent_service(db2)
    ctx2 = svc2.get_context(AgentContextRequest(
        query="fastapi framework", namespace=NS,
        user_id="user-1", agent_id="deepseek"))
    check("restart: context retrieval still works",
          lower_has(ctx2.text, "fastapi"), "fastapi present after reopen")

    prov = db2.query(Event).filter(
        Event.namespace == NS, Event.agent_id == "cursor").count()
    check("restart: agent provenance persists", prov >= 1, f"cursor_events={prov}")
    sess = db2.query(Event).filter(
        Event.namespace == NS, Event.session_id == "sess-r1").count()
    check("restart: session provenance persists", sess >= 1, f"sess_events={sess}")

    r_replay = svc2.remember(AgentRememberRequest(
        namespace=NS, user_id="user-1", agent_id="qwen",
        content="We chose PostgreSQL for Munin persistence.",
        idempotency_key="ik-restart"))
    check("restart: idempotency replay after reopen",
          r_replay.idempotent_replay is True, f"replay={r_replay.idempotent_replay}")

    ctx3 = svc2.get_context(AgentContextRequest(
        query="Munin persistence postgresql", namespace=NS,
        user_id="user-1", agent_id="deepseek"))
    check("restart: cross-agent retrieval works",
          lower_has(ctx3.text, "postgresql"), "postgres present")

    db2.close()
    eng2.dispose()
    if tmp.exists():
        tmp.unlink()


def main() -> int:
    section_behaviors()
    section_continuity()
    section_restart()

    print("\n" + "=" * 60)
    failed = [r for r in results if not r[1]]
    print(f"Manual M7A checks: {len(results) - len(failed)}/{len(results)} passed")
    for name, ok, detail in results:
        if not ok:
            print(f"  [FAIL] {name} -- {detail}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
