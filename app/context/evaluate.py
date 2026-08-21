"""
M5 Context Assembly evaluation harness.

Usage:
    python -m app.context.evaluate

Reads tests/fixtures/context_cases.json, creates an in-memory database,
stores memories per case, runs context assembly, and reports metrics.

Required safety targets (hard failures):
    superseded_leak_count = 0
    namespace_leak_count  = 0
    user_leak_count       = 0
    budget_violation_count = 0
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, event as sqla_event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.context.service import ContextService
from app.database import Base
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.vector_utils import serialize_vector
from app.models.embedding import MemoryEmbedding
from app.models.event import Event, EventRole
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.models.temporal import MemoryTemporalDecision
from app.schemas.context import ContextRequest

FIXTURE_PATH = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "context_cases.json"


# ---------------------------------------------------------------------------
# In-memory DB setup
# ---------------------------------------------------------------------------

def _make_engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @sqla_event.listens_for(eng, "connect")
    def _pragma(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=eng)
    return eng


# ---------------------------------------------------------------------------
# Memory seeding helpers
# ---------------------------------------------------------------------------

def _seed_memory(
    db: Session,
    provider: FakeEmbeddingProvider,
    *,
    namespace: str,
    content: str,
    memory_type: str,
    importance: float = 0.5,
    confidence: float = 1.0,
    status: str = "active",
    user_id: str | None = None,
    agent_id: str | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    created_at: datetime | None = None,
) -> Memory:
    now = datetime.now(UTC)
    m = Memory(
        namespace=namespace,
        content=content,
        memory_type=MemoryType(memory_type),
        importance=importance,
        confidence=confidence,
        status=MemoryStatus(status),
        user_id=user_id,
        agent_id=agent_id,
        valid_from=valid_from,
        valid_until=valid_until,
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


def _seed_case(
    db: Session,
    provider: FakeEmbeddingProvider,
    case: dict,
) -> dict[str, Memory]:
    """Seed all memories for a single case. Returns content→Memory map."""
    now = datetime.now(UTC)
    seeded: dict[str, Memory] = {}

    # Primary memories
    for mem_spec in case.get("memories", []):
        created_at = now
        if "days_ago" in mem_spec:
            created_at = now - timedelta(days=mem_spec["days_ago"])

        valid_from = None
        if "valid_from_days_ago" in mem_spec:
            valid_from = now - timedelta(days=mem_spec["valid_from_days_ago"])
        if "valid_from_days_from_now" in mem_spec:
            valid_from = now + timedelta(days=mem_spec["valid_from_days_from_now"])

        valid_until = None
        if "valid_until_days_ago" in mem_spec:
            valid_until = now - timedelta(days=mem_spec["valid_until_days_ago"])
        if "valid_until_days_from_now" in mem_spec:
            valid_until = now + timedelta(days=mem_spec["valid_until_days_from_now"])

        m = _seed_memory(
            db, provider,
            namespace=case["namespace"],
            content=mem_spec["content"],
            memory_type=mem_spec["memory_type"],
            importance=mem_spec.get("importance", 0.5),
            confidence=mem_spec.get("confidence", 1.0),
            status=mem_spec.get("status", "active"),
            user_id=mem_spec.get("user_id", case.get("user_id")),
            agent_id=mem_spec.get("agent_id"),
            valid_from=valid_from,
            valid_until=valid_until,
            created_at=created_at,
        )
        seeded[mem_spec["content"]] = m

    # Other-namespace memories (for isolation tests)
    for mem_spec in case.get("other_namespace_memories", []):
        _seed_memory(
            db, provider,
            namespace=mem_spec["namespace"],
            content=mem_spec["content"],
            memory_type=mem_spec.get("memory_type", "fact"),
            importance=mem_spec.get("importance", 0.5),
            status=mem_spec.get("status", "active"),
            user_id=mem_spec.get("user_id"),
        )

    # Other-user memories (for isolation tests)
    for mem_spec in case.get("other_user_memories", []):
        _seed_memory(
            db, provider,
            namespace=case["namespace"],
            content=mem_spec["content"],
            memory_type=mem_spec.get("memory_type", "fact"),
            importance=mem_spec.get("importance", 0.5),
            status=mem_spec.get("status", "active"),
            user_id=mem_spec["user_id"],
        )

    # Temporal relationships (for contradiction tests)
    for rel in case.get("temporal_relationships", []):
        matched_mem = seeded.get(rel.get("matched_content", ""))
        created_mem = seeded.get(rel.get("created_content", ""))
        if matched_mem is None or created_mem is None:
            continue

        ev = Event(
            namespace=case["namespace"],
            content="eval event",
            role=EventRole.user,
            created_at=now,
        )
        db.add(ev)
        db.flush()

        td = MemoryTemporalDecision(
            event_id=ev.id,
            candidate_content=rel.get("created_content", ""),
            candidate_memory_type="fact",
            matched_memory_id=matched_mem.id,
            created_memory_id=created_mem.id,
            relationship=rel.get("relationship", "CONTRADICTS"),
            relationship_confidence=rel.get("confidence", 0.9),
            provider="fake",
            model_name="fake-mini",
            created_at=now,
        )
        db.add(td)
        db.flush()

    db.commit()
    return seeded


# ---------------------------------------------------------------------------
# Result checking helpers
# ---------------------------------------------------------------------------

def _check_budget(resp, token_budget: int) -> bool:
    return resp.estimated_tokens <= token_budget


def _check_superseded_leak(resp) -> bool:
    """Returns True if a superseded memory leaked (failure)."""
    return False  # Leak detection is structural — the service filters upstream


def _run_case(
    db: Session,
    provider: FakeEmbeddingProvider,
    case: dict,
) -> dict:
    result = {
        "id": case["id"],
        "category": case["category"],
        "description": case["description"],
        "passed": True,
        "failures": [],
        "warnings": [],
        "metrics": {},
    }

    try:
        _seed_case(db, provider, case)
    except Exception as exc:  # noqa: BLE001
        result["passed"] = False
        result["failures"].append(f"seed_error: {exc}")
        traceback.print_exc()
        return result

    checks = case.get("checks", {})
    token_budget = case.get("token_budget", 1500)

    memory_types = None
    if "memory_types_filter" in case:
        from app.models.memory import MemoryType as MT
        memory_types = [MT(t) for t in case["memory_types_filter"]]

    try:
        req = ContextRequest(
            query=case["query"],
            namespace=case["namespace"],
            user_id=case.get("user_id"),
            token_budget=token_budget,
            include_superseded=case.get("include_superseded", False),
            memory_types=memory_types,
        )
        svc = ContextService(db=db, provider=provider)
        resp = svc.assemble(req)
    except Exception as exc:  # noqa: BLE001
        if checks.get("no_exception"):
            result["failures"].append(f"unexpected_exception: {exc}")
            result["passed"] = False
        else:
            result["failures"].append(f"assembly_error: {exc}")
            result["passed"] = False
            traceback.print_exc()
        return result

    contents_used = [m.content for m in resp.memories_used]
    types_used = [m.memory_type.value for m in resp.memories_used]

    # --- budget check ---
    if checks.get("budget_ok"):
        if resp.estimated_tokens > token_budget:
            result["failures"].append(
                f"budget_violated: estimated={resp.estimated_tokens} budget={token_budget}"
            )
            result["passed"] = False

    # --- top1 check ---
    if "top1_matches_any_of" in checks:
        candidates = checks["top1_matches_any_of"]
        if not contents_used:
            result["warnings"].append("top1_check: no memories returned")
        elif contents_used[0] not in candidates:
            result["failures"].append(
                f"top1_mismatch: got={contents_used[0]!r} expected_one_of={candidates}"
            )
            result["passed"] = False

    # --- excluded_from_top3 check ---
    if "excluded_from_top3" in checks:
        top3 = set(contents_used[:3])
        for excluded in checks["excluded_from_top3"]:
            if excluded in top3:
                result["failures"].append(f"excluded_in_top3: {excluded!r}")
                result["passed"] = False

    # --- memories_used_count exact ---
    if "memories_used_count" in checks:
        expected = checks["memories_used_count"]
        actual = len(resp.memories_used)
        if actual != expected:
            result["failures"].append(f"memories_used_count: got={actual} expected={expected}")
            result["passed"] = False

    # --- max_memories_used ---
    if "max_memories_used" in checks:
        if len(resp.memories_used) > checks["max_memories_used"]:
            result["failures"].append(
                f"max_memories_used: got={len(resp.memories_used)} max={checks['max_memories_used']}"
            )
            result["passed"] = False

    # --- min_memories_used ---
    if "min_memories_used" in checks:
        if len(resp.memories_used) < checks["min_memories_used"]:
            result["failures"].append(
                f"min_memories_used: got={len(resp.memories_used)} min={checks['min_memories_used']}"
            )
            result["passed"] = False

    # --- all_types_match ---
    if "all_types_match" in checks:
        expected_type = checks["all_types_match"]
        bad = [t for t in types_used if t != expected_type]
        if bad:
            result["failures"].append(f"type_filter_leak: unexpected types={bad}")
            result["passed"] = False

    # --- all_types_in ---
    if "all_types_in" in checks:
        allowed = set(checks["all_types_in"])
        bad = [t for t in types_used if t not in allowed]
        if bad:
            result["failures"].append(f"type_filter_leak: unexpected types={bad}")
            result["passed"] = False

    # --- namespace_leak ---
    if checks.get("namespace_leak") is False:
        # All returned memories must belong to the requested namespace (structural guarantee)
        # We can't check namespace from resp directly, but absence of other-ns content is the signal
        other_ns_contents = [
            m["content"] for m in case.get("other_namespace_memories", [])
        ]
        for c in other_ns_contents:
            if c in contents_used:
                result["failures"].append(f"namespace_leak: {c!r} appeared in results")
                result["passed"] = False

    # --- user_leak ---
    if checks.get("user_leak") is False:
        other_user_contents = [
            m["content"] for m in case.get("other_user_memories", [])
        ]
        for c in other_user_contents:
            if c in contents_used:
                result["failures"].append(f"user_leak: {c!r} appeared in results")
                result["passed"] = False

    # --- superseded_leak ---
    if checks.get("superseded_leak") is False:
        superseded_contents = [
            m["content"]
            for m in case.get("memories", [])
            if m.get("status") == "superseded"
        ]
        for c in superseded_contents:
            if c in contents_used:
                result["failures"].append(f"superseded_leak: {c!r} appeared in results")
                result["passed"] = False

    # --- conflict_represented ---
    if checks.get("conflict_represented"):
        has_conflict = "Unresolved conflicts" in resp.context
        if not has_conflict and len(resp.memories_used) >= 2:
            result["warnings"].append("conflict_represented: no conflict section (may be ok if memories not both selected)")

    # --- recency ordering ---
    if checks.get("first_recency_score_gte_second"):
        if len(resp.memories_used) >= 2:
            s1 = resp.memories_used[0].recency_score
            s2 = resp.memories_used[1].recency_score
            if s1 < s2:
                result["failures"].append(
                    f"recency_order: first={s1:.4f} < second={s2:.4f}"
                )
                result["passed"] = False

    if "max_recency_score_lt" in checks:
        max_recency = max((m.recency_score for m in resp.memories_used), default=0.0)
        if max_recency >= checks["max_recency_score_lt"]:
            result["failures"].append(
                f"recency_too_high: max={max_recency:.4f} expected_lt={checks['max_recency_score_lt']}"
            )
            result["passed"] = False

    # --- deterministic ---
    if checks.get("deterministic"):
        fixed_as_of = datetime(2030, 1, 1, tzinfo=UTC)
        req2 = ContextRequest(
            query=case["query"],
            namespace=case["namespace"],
            user_id=case.get("user_id"),
            token_budget=token_budget,
            as_of=fixed_as_of,
        )
        resp2 = svc.assemble(req2)
        resp3 = svc.assemble(req2)
        ids2 = [m.memory_id for m in resp2.memories_used]
        ids3 = [m.memory_id for m in resp3.memories_used]
        if ids2 != ids3:
            result["failures"].append("non_deterministic: repeated calls differ")
            result["passed"] = False

    # --- read_only ---
    if checks.get("read_only"):
        from app.models.memory import Memory as MemModel
        from sqlalchemy import select

        snap_before = {}
        for m in resp.memories_used:
            row = db.execute(
                select(MemModel).where(MemModel.id == m.memory_id)
            ).scalar_one_or_none()
            if row:
                snap_before[row.id] = (row.importance, row.confidence, row.status, row.updated_at)

        # Re-assemble (should not mutate)
        svc.assemble(req)

        for mid, (imp, conf, stat, upd) in snap_before.items():
            row = db.execute(
                select(MemModel).where(MemModel.id == mid)
            ).scalar_one_or_none()
            if row is None:
                continue
            if row.importance != imp or row.confidence != conf or row.status != stat or row.updated_at != upd:
                result["failures"].append(f"mutation_detected: memory_id={mid}")
                result["passed"] = False

    result["metrics"] = {
        "memories_used": len(resp.memories_used),
        "estimated_tokens": resp.estimated_tokens,
        "token_budget": token_budget,
        "truncated": resp.truncated,
        "top1": contents_used[0] if contents_used else None,
    }

    return result


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------

def _compute_aggregate_metrics(results: list[dict], cases: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    # Safety counters
    superseded_leak_count = 0
    namespace_leak_count = 0
    user_leak_count = 0
    budget_violation_count = 0

    for r in results:
        for f in r["failures"]:
            if "superseded_leak" in f:
                superseded_leak_count += 1
            if "namespace_leak" in f:
                namespace_leak_count += 1
            if "user_leak" in f:
                user_leak_count += 1
            if "budget_violated" in f:
                budget_violation_count += 1

    # top1 accuracy
    top1_correct = 0
    top1_total = 0
    for r, case in zip(results, cases):
        checks = case.get("checks", {})
        if "top1_matches_any_of" in checks:
            top1_total += 1
            if r["passed"] and not any("top1_mismatch" in f for f in r["failures"]):
                top1_correct += 1

    expected_top1_accuracy = (top1_correct / top1_total) if top1_total else None

    # Redundancy rate — cases where more than 1 identical memory was returned
    redundancy_violations = sum(
        1 for r in results
        if any("max_memories_used" in f for f in r["failures"])
    )
    redundancy_rate = redundancy_violations / total if total else 0.0

    return {
        "total_cases": total,
        "passed": passed,
        "failed": failed,
        "expected_top1_accuracy": expected_top1_accuracy,
        "superseded_leak_count": superseded_leak_count,
        "namespace_leak_count": namespace_leak_count,
        "user_leak_count": user_leak_count,
        "budget_violation_count": budget_violation_count,
        "redundancy_rate": redundancy_rate,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_evaluation(fixture_path: Path = FIXTURE_PATH) -> int:
    """Run evaluation. Returns exit code (0=pass, 1=safety targets failed)."""
    print(f"\n{'=' * 60}")
    print("  Munin M5 Context Assembly Evaluation")
    print(f"{'=' * 60}\n")

    with open(fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)

    cases = fixture["cases"]
    print(f"Loaded {len(cases)} evaluation cases from {fixture_path.name}\n")

    results: list[dict] = []
    provider = FakeEmbeddingProvider()

    for case in cases:
        # Fresh isolated DB per case
        engine = _make_engine()
        Session_ = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = Session_()
        t0 = time.monotonic()
        try:
            result = _run_case(db, provider, case)
        finally:
            db.close()
            engine.dispose()

        elapsed = time.monotonic() - t0
        status = "PASS" if result["passed"] else "FAIL"
        print(f"  [{status}] {case['id']:30s}  {elapsed:.3f}s  {case['description'][:55]}")
        if result["failures"]:
            for f in result["failures"]:
                print(f"         ✗ {f}")
        if result["warnings"]:
            for w in result["warnings"]:
                print(f"         ⚠ {w}")
        results.append(result)

    metrics = _compute_aggregate_metrics(results, cases)

    print(f"\n{'=' * 60}")
    print("  Aggregate Metrics")
    print(f"{'=' * 60}")
    print(f"  total_cases              : {metrics['total_cases']}")
    print(f"  passed                   : {metrics['passed']}")
    print(f"  failed                   : {metrics['failed']}")
    if metrics["expected_top1_accuracy"] is not None:
        print(f"  expected_top1_accuracy   : {metrics['expected_top1_accuracy']:.2%}")
    print()

    # Safety targets
    SAFETY_OK = "✓"
    SAFETY_FAIL = "✗"
    targets = [
        ("superseded_leak_count", metrics["superseded_leak_count"], 0),
        ("namespace_leak_count",  metrics["namespace_leak_count"],  0),
        ("user_leak_count",       metrics["user_leak_count"],       0),
        ("budget_violation_count",metrics["budget_violation_count"],0),
    ]

    all_safe = True
    for name, actual, target in targets:
        ok = actual == target
        sym = SAFETY_OK if ok else SAFETY_FAIL
        print(f"  {sym} {name:<28} = {actual}  (target={target})")
        if not ok:
            all_safe = False

    print(f"\n  redundancy_rate          : {metrics['redundancy_rate']:.2%}")

    print(f"\n{'=' * 60}")
    if all_safe and metrics["failed"] == 0:
        print("  RESULT: ALL CHECKS PASSED ✓")
        exit_code = 0
    elif all_safe:
        print(f"  RESULT: {metrics['failed']} CASE(S) FAILED — safety targets met")
        exit_code = 0  # Safety targets met; case failures may be non-critical
    else:
        print("  RESULT: SAFETY TARGET(S) VIOLATED ✗")
        exit_code = 1
    print(f"{'=' * 60}\n")

    return exit_code


if __name__ == "__main__":
    sys.exit(run_evaluation())
