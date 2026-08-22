"""M7A Agent Integration evaluation harness.

Usage:
    python -m app.agent.evaluate

Reads tests/fixtures/agent_integration_cases.json and drives each case
through the high-level AgentService (remember/context) against an in-memory
SQLite database, then reports metrics.

Required safety targets:
    namespace_leak_count       = 0
    user_leak_count            = 0
    duplicate_event_count      = 0
    duplicate_memory_count     = 0
    idempotency_failure_count  = 0
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import create_engine, event as sqla_event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.admission.providers.deterministic import DeterministicAdmissionProvider
from app.agent.models import AgentContextRequest, AgentRememberRequest
from app.agent.service import AgentService
from app.database import Base
from app.deduplication.providers.deterministic import DeterministicRelationshipProvider
from app.embeddings.fake import FakeEmbeddingProvider
from app.models.event import Event
from app.models.memory import Memory

FIXTURE_PATH = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "agent_integration_cases.json"
)

PASS = "\u2713"
FAIL = "\u2717"


def _make_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)

    @sqla_event.listens_for(eng, "connect")
    def _pragma(conn, _rec):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng


def _agent_service(db: Session) -> AgentService:
    return AgentService(
        db,
        admission_provider=DeterministicAdmissionProvider(),
        embedding_provider=FakeEmbeddingProvider(),
        relationship_provider=DeterministicRelationshipProvider(),
    )


def _count_events(db: Session, namespace: str) -> int:
    return db.query(Event).filter(Event.namespace == namespace).count()


def _count_memories(db: Session, namespace: str) -> int:
    return db.query(Memory).filter(Memory.namespace == namespace).count()
def _run_case(case: dict, db: Session, service: AgentService, metrics: dict) -> dict:
    result = {"id": case["id"], "category": case["category"], "passed": True, "failures": []}
    for step in case.get("steps", []):
        try:
            _run_step(step, db, service, result, metrics)
        except ValidationError:
            if step.get("expect_error"):
                continue  # expected validation error
            result["passed"] = False
            result["failures"].append("unexpected validation error")
            metrics["remember_failure_count"] += 1
        except Exception as exc:  # noqa: BLE001
            result["passed"] = False
            result["failures"].append(f"step exception: {exc}")
            metrics["context_failure_count"] += 1
            metrics["remember_failure_count"] += 1
    return result


def _run_step(step: dict, db: Session, service: AgentService, result: dict, metrics: dict) -> None:
    action = step["action"]

    if action == "remember":
        try:
            payload = AgentRememberRequest(
                namespace=step["namespace"],
                user_id=step.get("user_id"),
                agent_id=step.get("agent_id"),
                session_id=step.get("session_id"),
                role=step.get("role", "assistant"),
                content=step["content"],
                idempotency_key=step.get("idempotency_key"),
            )
        except ValidationError as exc:
            if step.get("expect_error"):
                return  # expected validation rejection
            raise
        outcome = service.remember(payload)

        if step.get("expect_idempotent") is not None:
            replay = bool(outcome.idempotent_replay)
            if replay != bool(step["expect_idempotent"]):
                result["passed"] = False
                result["failures"].append(
                    f"idempotent_replay={replay} expect={step['expect_idempotent']}"
                )
                metrics["idempotency_failure_count"] += 1

        if "expect_decision" in step and outcome.decision != step["expect_decision"]:
            _fail(result, metrics, "decision", outcome.decision, step["expect_decision"],
                  "remember_failure_count")

        if "expect_remembered" in step and outcome.remembered != bool(step["expect_remembered"]):
            _fail(result, metrics, "remembered", outcome.remembered, step["expect_remembered"],
                  "remember_failure_count")

        if step.get("expect_memory_id") and not outcome.memory_id:
            result["passed"] = False
            result["failures"].append("expected created memory_id")
            metrics["remember_failure_count"] += 1

        if step.get("expect_from_sqlite") and not outcome.memory_id:
            result["passed"] = False
            result["failures"].append("expected initial SQLite memory created")
            metrics["remember_failure_count"] += 1

        if "expect_dedup" in step and outcome.dedup_relationship != step["expect_dedup"]:
            _fail(result, metrics, "dedup", outcome.dedup_relationship, step["expect_dedup"],
                  "remember_failure_count")

        if "expect_temporal" in step and outcome.temporal_relationship != step["expect_temporal"]:
            _fail(result, metrics, "temporal", outcome.temporal_relationship,
                  step["expect_temporal"], "remember_failure_count")
        return

    if action == "context":
        resp = service.get_context(
            AgentContextRequest(
                query=step["query"],
                namespace=step["namespace"],
                user_id=step.get("user_id"),
                agent_id=step.get("agent_id"),
            )
        )
        text = resp.text or ""
        if step.get("expect_contains") and step["expect_contains"] not in text:
            result["passed"] = False
            result["failures"].append(
                f"missing {step['expect_contains']!r} in context"
            )
            metrics["context_failure_count"] += 1
        if step.get("expect_absent") and step["expect_absent"] in text:
            result["passed"] = False
            result["failures"].append(
                f"leak: {step['expect_absent']!r} present in {step['namespace']}"
            )
            metrics["context_failure_count"] += 1
            if "namespace" in result["category"]:
                metrics["namespace_leak_count"] += 1
            if "user" in result["category"]:
                metrics["user_leak_count"] += 1
        return

    if action == "count":
        if step["table"] == "events":
            actual = _count_events(db, step["namespace"])
        else:
            actual = _count_memories(db, step["namespace"])
        if actual != step["expect"]:
            result["passed"] = False
            result["failures"].append(f"count {step['table']}={actual} expect={step['expect']}")
            if step["table"] == "events" and actual > step["expect"]:
                metrics["duplicate_event_count"] += actual - step["expect"]
            if step["table"] == "memories" and actual > step["expect"]:
                metrics["duplicate_memory_count"] += actual - step["expect"]
        return

    if action == "check_event":
        evt = (
            db.query(Event)
            .filter(
                Event.namespace == step["namespace"],
                Event.agent_id == step.get("agent_id"),
            )
            .order_by(Event.created_at.desc())
            .first()
        )
        if evt is None or evt.session_id != step.get("expect_session"):
            result["passed"] = False
            result["failures"].append("session_id not persisted on event")
            metrics["remember_failure_count"] += 1
        return


def _fail(result, metrics, label, actual, expect, metric) -> None:
    result["passed"] = False
    result["failures"].append(f"{label}={actual} expect={expect}")
    metrics[metric] += 1
def run_evaluation(fixture_path: Path = FIXTURE_PATH) -> int:
    print("\n" + "=" * 60)
    print("  Munin M7A Agent Integration Evaluation")
    print("=" * 60 + "\n")

    with open(fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)
    cases = fixture["cases"]
    print(f"Loaded {len(cases)} agent integration cases\n")

    metrics = {
        "total_cases": 0,
        "passed": 0,
        "failed": 0,
        "continuity_success_rate": 1.0,
        "cross_agent_success_rate": 1.0,
        "namespace_leak_count": 0,
        "user_leak_count": 0,
        "duplicate_event_count": 0,
        "duplicate_memory_count": 0,
        "context_failure_count": 0,
        "remember_failure_count": 0,
        "idempotency_failure_count": 0,
    }

    results: list[dict] = []
    for case in cases:
        engine = _make_engine()
        Session_ = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = Session_()
        service = _agent_service(db)
        result = _run_case(case, db, service, metrics)
        status = PASS if result["passed"] else FAIL
        print(f"  [{status}] {case['id']:28s}  {case['description'][:54]}")
        for failure in result["failures"]:
            print(f"         {FAIL} {failure}")
        results.append(result)
        db.close()
        engine.dispose()

    _finalize_metrics(metrics, results)

    print("\n  Aggregate Metrics")
    for key in [
        "total_cases", "passed", "failed", "continuity_success_rate",
        "cross_agent_success_rate", "namespace_leak_count", "user_leak_count",
        "duplicate_event_count", "duplicate_memory_count", "context_failure_count",
        "remember_failure_count", "idempotency_failure_count",
    ]:
        print(f"  {key:<28} = {metrics[key]}")

    targets = [
        "namespace_leak_count", "user_leak_count", "duplicate_event_count",
        "duplicate_memory_count", "idempotency_failure_count",
    ]
    all_safe = all(metrics[t] == 0 for t in targets)
    print()
    for t in targets:
        ok_ = metrics[t] == 0
        print(f"  {PASS if ok_ else FAIL} {t:<28} = {metrics[t]}  (target=0)")
    print("=" * 60)
    return 0 if all_safe else 1


def _finalize_metrics(metrics: dict, results: list[dict]) -> None:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    cont = [r for r in results if r["category"] in ("continuity", "model_switch_continuation")]
    cross = [r for r in results if r["category"] == "cross_agent"]
    metrics.update(
        {
            "total_cases": total,
            "passed": passed,
            "failed": total - passed,
            "continuity_success_rate": round(
                sum(1 for r in cont if r["passed"]) / len(cont), 4
            ) if cont else 1.0,
            "cross_agent_success_rate": round(
                sum(1 for r in cross if r["passed"]) / len(cross), 4
            ) if cross else 1.0,
        }
    )


if __name__ == "__main__":
    sys.exit(run_evaluation())