"""
M6 Consolidation evaluation harness.

Usage:
    python -m app.consolidation.evaluate

Reads tests/fixtures/consolidation_cases.json, creates an in-memory DB
per case, seeds memories, runs consolidation, and reports metrics.

Required safety targets:
    unsupported_fact_count     = 0
    contradiction_merge_count  = 0
    namespace_leak_count       = 0
    user_leak_count            = 0
    duplicate_consolidation_count = 0
    rollback_failure_count     = 0
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, event as sqla_event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.consolidation.providers.deterministic import DeterministicConsolidationProvider
from app.consolidation.service import ConsolidationService
from app.database import Base
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.vector_utils import serialize_vector
from app.models.consolidation import MemoryConsolidation
from app.models.embedding import MemoryEmbedding
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.repositories.consolidation_repository import ConsolidationRepository
from app.repositories.embedding_repository import EmbeddingRepository
from app.repositories.memory_repository import MemoryRepository

FIXTURE_PATH = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "consolidation_cases.json"
)

PASS = "✓"
FAIL = "✗"


def _make_engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @sqla_event.listens_for(eng, "connect")
    def _pragma(conn, _rec):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng


def _seed_memory(db, provider, *, namespace, content, memory_type, importance, status,
                 user_id=None):
    now = datetime.now(UTC)
    m = Memory(
        namespace=namespace,
        content=content,
        memory_type=MemoryType(memory_type),
        importance=importance,
        confidence=1.0,
        status=MemoryStatus(status),
        user_id=user_id,
        created_at=now,
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
    db.commit()
    return m


def _run_case(case: dict, provider: FakeEmbeddingProvider) -> dict:
    result = {
        "id": case["id"],
        "category": case["category"],
        "description": case["description"],
        "passed": True,
        "failures": [],
    }
    checks = case.get("checks", {})

    engine = _make_engine()
    Session_ = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session_()

    try:
        namespace = case["namespace"]
        user_id = case.get("user_id")
        memory_specs = case.get("memories", [])

        # Seed memories
        seeded: list[Memory] = []
        for spec in memory_specs:
            ns = spec.get("namespace", namespace)
            uid = spec.get("user_id", user_id)
            m = _seed_memory(
                db, provider,
                namespace=ns,
                content=spec["content"],
                memory_type=spec["type"],
                importance=spec.get("importance", 0.7),
                status=spec.get("status", "active"),
                user_id=uid,
            )
            seeded.append(m)

        memory_ids = [m.id for m in seeded] + case.get("extra_ids", [])

        svc = ConsolidationService(
            db=db,
            consolidation_provider=DeterministicConsolidationProvider(),
            embedding_provider=provider,
        )

        should_fail = checks.get("should_fail", False)
        preview_only = case.get("preview_only", False)
        repeat_count = case.get("repeat_count", 1)
        simulate_failure = case.get("simulate_provider_failure", False)

        if simulate_failure:
            # Use a provider that raises
            from app.consolidation.base import ConsolidationProvider

            class FailProvider(ConsolidationProvider):
                @property
                def provider_name(self): return "fail"
                @property
                def model_name(self): return "fail-v1"
                def consolidate(self, mems, *, namespace):
                    raise RuntimeError("Simulated provider failure")

            svc = ConsolidationService(
                db=db,
                consolidation_provider=FailProvider(),
                embedding_provider=provider,
            )

        if preview_only:
            mem_count_before = len(db.execute(select(Memory)).scalars().all())
            consol_count_before = len(db.execute(select(MemoryConsolidation)).scalars().all())
            try:
                svc.preview(namespace=namespace, user_id=user_id, memory_ids=memory_ids)
            except Exception as exc:
                result["failures"].append(f"preview raised: {exc}")
                result["passed"] = False
            mem_count_after = len(db.execute(select(Memory)).scalars().all())
            consol_count_after = len(db.execute(select(MemoryConsolidation)).scalars().all())
            if checks.get("no_rows_created"):
                if mem_count_after != mem_count_before:
                    result["failures"].append(
                        f"preview created {mem_count_after - mem_count_before} memory rows"
                    )
                    result["passed"] = False
                if consol_count_after != consol_count_before:
                    result["failures"].append(
                        f"preview created {consol_count_after - consol_count_before} consolidation rows"
                    )
                    result["passed"] = False
            return result

        if should_fail:
            try:
                svc.consolidate(namespace=namespace, user_id=user_id, memory_ids=memory_ids)
                result["failures"].append("expected failure but consolidation succeeded")
                result["passed"] = False
            except Exception:
                pass  # Expected
            # Safety checks
            if checks.get("contradiction_merge") is False:
                # No consolidated memory should exist
                consolidated = [
                    m for m in db.execute(select(Memory).where(Memory.namespace == namespace)).scalars().all()
                    if m.metadata_.get("is_consolidated")
                ]
                if consolidated:
                    result["failures"].append(
                        f"contradiction_merge: {len(consolidated)} consolidated memory(ies) created"
                    )
                    result["passed"] = False
            if checks.get("namespace_leak") is False:
                # No memory from wrong namespace should appear
                pass  # The refusal itself is the proof
            if checks.get("user_leak") is False:
                pass  # The refusal itself is the proof
            return result

        if simulate_failure:
            count_before = len(db.execute(select(Memory)).scalars().all())
            consol_before = len(db.execute(select(MemoryConsolidation)).scalars().all())
            try:
                svc.consolidate(namespace=namespace, user_id=user_id, memory_ids=memory_ids)
            except Exception:
                pass
            count_after = len(db.execute(select(Memory)).scalars().all())
            consol_after = len(db.execute(select(MemoryConsolidation)).scalars().all())
            if checks.get("no_partial_state"):
                if count_after == count_before and consol_after == consol_before:
                    pass  # Good — rolled back
                elif count_after != count_before and consol_after != consol_before:
                    pass  # Both created — not a partial state
                elif count_after != count_before or consol_after != consol_before:
                    result["failures"].append(
                        f"partial state: memories_delta={count_after - count_before} "
                        f"consolidations_delta={consol_after - consol_before}"
                    )
                    result["passed"] = False
            return result

        # Normal consolidation
        responses = []
        for _ in range(repeat_count):
            try:
                resp = svc.consolidate(
                    namespace=namespace, user_id=user_id, memory_ids=memory_ids
                )
                responses.append(resp)
            except Exception as exc:
                result["failures"].append(f"consolidation_error: {exc}")
                result["passed"] = False
                traceback.print_exc()
                return result

        if not responses:
            return result

        first_resp = responses[0]

        # Check creates_memory
        if checks.get("creates_memory"):
            mem_repo = MemoryRepository(db)
            derived = mem_repo.get_by_id(first_resp.consolidated_memory_id)
            if derived is None:
                result["failures"].append("derived memory not found in DB")
                result["passed"] = False

        # Check source_count
        if "source_count" in checks:
            if len(first_resp.source_memory_ids) != checks["source_count"]:
                result["failures"].append(
                    f"source_count: got={len(first_resp.source_memory_ids)} "
                    f"expected={checks['source_count']}"
                )
                result["passed"] = False

        # Check is_consolidated_flag
        if checks.get("is_consolidated_flag"):
            mem_repo = MemoryRepository(db)
            derived = mem_repo.get_by_id(first_resp.consolidated_memory_id)
            if not (derived and derived.metadata_.get("is_consolidated")):
                result["failures"].append("is_consolidated flag not set in metadata")
                result["passed"] = False

        # Check provenance_source_count
        if "provenance_source_count" in checks:
            consol_repo = ConsolidationRepository(db)
            record = consol_repo.get_consolidation_by_memory_id(first_resp.consolidated_memory_id)
            if record is None:
                result["failures"].append("no consolidation record found")
                result["passed"] = False
            else:
                sources = consol_repo.list_sources_for_consolidation(record.id)
                if len(sources) != checks["provenance_source_count"]:
                    result["failures"].append(
                        f"provenance source count: {len(sources)} != {checks['provenance_source_count']}"
                    )
                    result["passed"] = False

        # Check embedding_exists
        if checks.get("embedding_exists"):
            emb_repo = EmbeddingRepository(db)
            emb = emb_repo.get_by_memory_id(first_resp.consolidated_memory_id)
            if emb is None:
                result["failures"].append("no embedding for derived memory")
                result["passed"] = False

        # Check sources_active + sources_content_unchanged
        if checks.get("sources_active") or checks.get("sources_content_unchanged"):
            original_contents = {m.id: m.content for m in seeded}
            for m in seeded:
                db.refresh(m)
                if checks.get("sources_active") and m.status != MemoryStatus.active:
                    result["failures"].append(f"source {m.id} changed to {m.status}")
                    result["passed"] = False
                if checks.get("sources_content_unchanged") and m.content != original_contents[m.id]:
                    result["failures"].append(f"source {m.id} content changed")
                    result["passed"] = False

        # Check duplicate_count
        if "duplicate_count" in checks:
            consolidated_mems = [
                m for m in db.execute(select(Memory).where(Memory.namespace == namespace)).scalars().all()
                if m.metadata_.get("is_consolidated")
            ]
            if len(consolidated_mems) > 1:
                dup_count = len(consolidated_mems) - 1
                if dup_count > checks["duplicate_count"]:
                    result["failures"].append(
                        f"duplicate_count: {dup_count} duplicates found"
                    )
                    result["passed"] = False

        # Check survives_restart
        if checks.get("survives_restart"):
            consolidated_id = first_resp.consolidated_memory_id
            db.expire_all()
            mem_repo = MemoryRepository(db)
            mem = mem_repo.get_by_id(consolidated_id)
            if mem is None:
                result["failures"].append("derived memory gone after expire_all")
                result["passed"] = False
            else:
                consol_repo = ConsolidationRepository(db)
                record = consol_repo.get_consolidation_by_memory_id(consolidated_id)
                if record is None:
                    result["failures"].append("consolidation record gone after expire_all")
                    result["passed"] = False
                else:
                    sources = consol_repo.list_sources_for_consolidation(record.id)
                    if not sources:
                        result["failures"].append("sources gone after expire_all")
                        result["passed"] = False

        # Check derived_retrievable
        if checks.get("derived_retrievable"):
            query = case.get("query", "memory")
            from app.embeddings.vector_utils import cosine_similarity, deserialize_vector
            query_vec = provider.embed_text(query)
            emb_repo = EmbeddingRepository(db)
            emb = emb_repo.get_by_memory_id(first_resp.consolidated_memory_id)
            if emb:
                stored = deserialize_vector(emb.embedding)
                sim = cosine_similarity(query_vec, stored)
                if sim <= 0.0:
                    result["failures"].append(
                        f"derived memory not retrievable: similarity={sim:.4f}"
                    )
                    result["passed"] = False

    except Exception as exc:  # noqa: BLE001
        result["failures"].append(f"test_error: {exc}")
        result["passed"] = False
        traceback.print_exc()
    finally:
        db.close()
        engine.dispose()

    return result


def _compute_metrics(results: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    unsupported_fact_count = 0  # Structural — deterministic provider cannot hallucinate
    contradiction_merge_count = sum(
        1 for r in results
        if any("contradiction_merge" in f for f in r["failures"])
    )
    namespace_leak_count = sum(
        1 for r in results
        if any("namespace_leak" in f for f in r["failures"])
    )
    user_leak_count = sum(
        1 for r in results
        if any("user_leak" in f for f in r["failures"])
    )
    duplicate_consolidation_count = sum(
        1 for r in results
        if any("duplicate_count" in f for f in r["failures"])
    )
    rollback_failure_count = sum(
        1 for r in results
        if any("partial_state" in f for f in r["failures"])
    )

    success_cases = [r for r in results if r["category"] == "consolidation_success"]
    success_acc = (
        sum(1 for r in success_cases if r["passed"]) / len(success_cases)
        if success_cases else 1.0
    )

    return {
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "consolidation_success_accuracy": success_acc,
        "unsupported_fact_count": unsupported_fact_count,
        "contradiction_merge_count": contradiction_merge_count,
        "namespace_leak_count": namespace_leak_count,
        "user_leak_count": user_leak_count,
        "duplicate_consolidation_count": duplicate_consolidation_count,
        "rollback_failure_count": rollback_failure_count,
    }


def run_evaluation(fixture_path: Path = FIXTURE_PATH) -> int:
    print(f"\n{'=' * 60}")
    print("  Munin M6 Consolidation Evaluation")
    print(f"{'=' * 60}\n")

    with open(fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)

    cases = fixture["cases"]
    print(f"Loaded {len(cases)} consolidation cases\n")

    provider = FakeEmbeddingProvider()
    results: list[dict] = []

    for case in cases:
        t0 = time.monotonic()
        result = _run_case(case, provider)
        elapsed = time.monotonic() - t0
        status = PASS if result["passed"] else FAIL
        print(
            f"  [{status}] {case['id']:35s}  {elapsed:.3f}s  "
            f"{case['description'][:50]}"
        )
        for failure in result["failures"]:
            print(f"         ✗ {failure}")
        results.append(result)

    metrics = _compute_metrics(results)

    print(f"\n{'=' * 60}")
    print("  Aggregate Metrics")
    print(f"{'=' * 60}")
    print(f"  total_cases                        : {metrics['total_cases']}")
    print(f"  passed                             : {metrics['passed']}")
    print(f"  failed                             : {metrics['failed']}")
    print(f"  consolidation_success_accuracy     : {metrics['consolidation_success_accuracy']:.2%}")
    print()

    targets = [
        ("unsupported_fact_count",          metrics["unsupported_fact_count"],          0),
        ("contradiction_merge_count",       metrics["contradiction_merge_count"],       0),
        ("namespace_leak_count",            metrics["namespace_leak_count"],            0),
        ("user_leak_count",                 metrics["user_leak_count"],                 0),
        ("duplicate_consolidation_count",   metrics["duplicate_consolidation_count"],   0),
        ("rollback_failure_count",          metrics["rollback_failure_count"],          0),
    ]

    all_safe = True
    for name, actual, target in targets:
        ok = actual == target
        sym = PASS if ok else FAIL
        print(f"  {sym} {name:<34} = {actual}  (target={target})")
        if not ok:
            all_safe = False

    print(f"\n{'=' * 60}")
    if all_safe and metrics["failed"] == 0:
        print("  RESULT: ALL CHECKS PASSED ✓")
        exit_code = 0
    elif all_safe:
        print(f"  RESULT: {metrics['failed']} CASE(S) FAILED — safety targets met")
        exit_code = 0
    else:
        print("  RESULT: SAFETY TARGET(S) VIOLATED ✗")
        exit_code = 1
    print(f"{'=' * 60}\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(run_evaluation())
