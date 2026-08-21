"""
M6 Decay evaluation harness.

Usage:
    python -m app.decay.evaluate

Reads tests/fixtures/decay_cases.json, runs pure-function checks on the
decay calculator, and reports metrics.

Required safety targets:
    no_mutation_count          = 0
    historical_determinism_failures = 0
    ranking_regression_count   = 0
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.context.models import ContextConfig
from app.context.scoring import score_candidate
from app.decay.calculator import (
    compute_decay_multiplier,
    compute_effective_importance,
    compute_reinforcement_modifier,
)
from app.decay.profiles import profile_for_type
from app.models.memory import Memory, MemoryStatus, MemoryType

FIXTURE_PATH = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "decay_cases.json"
)

PASS = "✓"
FAIL = "✗"


def _now() -> datetime:
    return datetime.now(UTC)


def _age(days: float) -> datetime:
    return _now() - timedelta(days=days)


def _multiplier(memory_type: str, age_days: float) -> float:
    return compute_decay_multiplier(
        memory_type=MemoryType(memory_type),
        created_at=_age(age_days),
        as_of=_now(),
    )


def _effective(memory_type: str, stored: float, age_days: float, reinforcement: int = 0) -> float:
    return compute_effective_importance(
        stored_importance=stored,
        memory_type=MemoryType(memory_type),
        created_at=_age(age_days),
        as_of=_now(),
        reinforcement_count=reinforcement,
    )


def _make_memory(memory_type: str, importance: float, age_days: float) -> Memory:
    now = _now()
    return Memory(
        id=f"eval-{memory_type}-{age_days}",
        namespace="eval",
        content=f"eval content {memory_type} {age_days}",
        memory_type=MemoryType(memory_type),
        importance=importance,
        confidence=1.0,
        status=MemoryStatus.active,
        created_at=_age(age_days),
        updated_at=now,
    )


def _score(memory_type: str, importance: float, age_days: float, semantic: float) -> float:
    m = _make_memory(memory_type, importance, age_days)
    cfg = ContextConfig(decay_enabled=True)
    candidate = score_candidate(
        memory=m,
        semantic_score=semantic,
        reinforcement_count=0,
        query="eval query",
        as_of=_now(),
        config=cfg,
    )
    return candidate.final_score


def _run_case(case: dict) -> dict:
    result = {
        "id": case["id"],
        "category": case["category"],
        "description": case["description"],
        "passed": True,
        "failures": [],
    }
    checks = case.get("checks", {})

    try:
        cat = case["category"]

        # -- profile_order --
        if cat == "profile_order":
            m_slow = case["memory_type_slow"]
            m_norm = case["memory_type_normal"]
            age = case["age_days"]
            mult_slow = _multiplier(m_slow, age)
            mult_norm = _multiplier(m_norm, age)
            if checks.get("slow_gt_normal") and not (mult_slow > mult_norm):
                result["failures"].append(
                    f"slow({m_slow})={mult_slow:.4f} not > normal({m_norm})={mult_norm:.4f}"
                )
                result["passed"] = False
            if "ratio_gt" in checks:
                ratio = mult_slow / max(mult_norm, 1e-10)
                if ratio < checks["ratio_gt"]:
                    result["failures"].append(
                        f"ratio {ratio:.2f} < required {checks['ratio_gt']}"
                    )
                    result["passed"] = False

        # -- zero_age --
        elif cat == "zero_age":
            mtype = case.get("memory_type", "event")
            mult = _multiplier(mtype, 0.0)
            tol = checks.get("tolerance", 0.001)
            if checks.get("multiplier_approx_one") and abs(mult - 1.0) > tol:
                result["failures"].append(f"zero-age multiplier={mult:.6f} not ≈ 1.0")
                result["passed"] = False

        # -- old_episodic --
        elif cat == "old_episodic":
            mtype = case.get("memory_type", "event")
            if "age_days" in case and "stored_importance" in case:
                eff = _effective(mtype, case["stored_importance"], case["age_days"])
                if "effective_lt" in checks and not (eff < checks["effective_lt"]):
                    result["failures"].append(
                        f"eff={eff:.4f} not < {checks['effective_lt']}"
                    )
                    result["passed"] = False
            elif "age_days_a" in case and "age_days_b" in case:
                mult_a = _multiplier(mtype, case["age_days_a"])
                mult_b = _multiplier(mtype, case["age_days_b"])
                if checks.get("a_lt_b") and not (mult_a < mult_b):
                    result["failures"].append(
                        f"mult_a={mult_a:.4f} not < mult_b={mult_b:.4f}"
                    )
                    result["passed"] = False
            elif "multiplier_lt" in checks:
                mult = _multiplier(mtype, case["age_days"])
                if not (mult < checks["multiplier_lt"]):
                    result["failures"].append(
                        f"mult={mult:.4f} not < {checks['multiplier_lt']}"
                    )
                    result["passed"] = False

        # -- stable_project --
        elif cat == "stable_project":
            mtype = case.get("memory_type", "project")
            eff = _effective(mtype, case["stored_importance"], case["age_days"])
            if "effective_gt" in checks and not (eff > checks["effective_gt"]):
                result["failures"].append(
                    f"eff={eff:.4f} not > {checks['effective_gt']}"
                )
                result["passed"] = False

        # -- no_mutation --
        elif cat == "no_mutation":
            mtype = case.get("memory_type", "event")
            stored = case.get("stored_importance", 0.75)
            age = case.get("age_days", 30)
            m = _make_memory(mtype, stored, age)
            original = m.importance
            _ = compute_effective_importance(
                stored_importance=m.importance,
                memory_type=m.memory_type,
                created_at=m.created_at,
                as_of=_now(),
            )
            if m.importance != original:
                result["failures"].append(
                    f"importance mutated: {original} → {m.importance}"
                )
                result["passed"] = False

        # -- historical_determinism --
        elif cat == "historical_determinism":
            mtype = case.get("memory_type", "project")
            if "as_of_fixed" in case and "created_at_fixed" in case:
                fixed_as_of = datetime.fromisoformat(case["as_of_fixed"])
                fixed_created = datetime.fromisoformat(case["created_at_fixed"])
                m1 = compute_decay_multiplier(
                    memory_type=MemoryType(mtype),
                    created_at=fixed_created,
                    as_of=fixed_as_of,
                )
                m2 = compute_decay_multiplier(
                    memory_type=MemoryType(mtype),
                    created_at=fixed_created,
                    as_of=fixed_as_of,
                )
                if checks.get("deterministic") and m1 != m2:
                    result["failures"].append(f"non-deterministic: {m1} != {m2}")
                    result["passed"] = False
            elif "earlier_as_of_higher_multiplier" in checks:
                if checks["earlier_as_of_higher_multiplier"] is False:
                    pass  # Documented non-check — fixture exists for documentation only
                else:
                    base_created = _age(case.get("created_at_days_ago", 60))
                    as_of_options = case.get("as_of_options", [30, 60])
                    mult_early = compute_decay_multiplier(
                        memory_type=MemoryType(mtype),
                        created_at=base_created,
                        as_of=_age(as_of_options[0]),
                    )
                    mult_late = compute_decay_multiplier(
                        memory_type=MemoryType(mtype),
                        created_at=base_created,
                        as_of=_age(as_of_options[1]),
                    )
                    if not (mult_early > mult_late):
                        result["failures"].append(
                            f"early={mult_early:.4f} not > late={mult_late:.4f}"
                        )
                        result["passed"] = False
            elif "created_at_days_from_now" in case:
                future_created = _now() + timedelta(days=case["created_at_days_from_now"])
                mult = compute_decay_multiplier(
                    memory_type=MemoryType(mtype),
                    created_at=future_created,
                    as_of=_now(),
                )
                tol = checks.get("tolerance", 0.001)
                if checks.get("multiplier_approx_one") and abs(mult - 1.0) > tol:
                    result["failures"].append(f"future created_at mult={mult:.6f} not ≈ 1")
                    result["passed"] = False

        # -- bounds --
        elif cat == "bounds":
            if "memory_types" in case:
                for mtype in case["memory_types"]:
                    mult = _multiplier(mtype, case["age_days"])
                    if not (0.0 <= mult <= 1.0):
                        result["failures"].append(f"{mtype} mult={mult} out of [0,1]")
                        result["passed"] = False
            if "effective_in_zero_one" in checks:
                mtype = case.get("memory_type", "event")
                stored = case.get("stored_importance", 1.0)
                age = case.get("age_days", 0)
                reinf = case.get("reinforcement_count", 0)
                eff = _effective(mtype, stored, age, reinf)
                if not (0.0 <= eff <= 1.0):
                    result["failures"].append(f"eff={eff} out of [0,1]")
                    result["passed"] = False

        # -- ranking_regression --
        elif cat == "ranking_regression":
            memories = case["memories"]
            if len(memories) >= 2:
                s0 = _score(
                    memories[0]["type"],
                    memories[0]["importance"],
                    memories[0]["age_days"],
                    memories[0]["semantic_score"],
                )
                s1 = _score(
                    memories[1]["type"],
                    memories[1]["importance"],
                    memories[1]["age_days"],
                    memories[1]["semantic_score"],
                )
                first_wins = s0 > s1
                if checks.get("first_wins") is True and not first_wins:
                    result["failures"].append(
                        f"expected first to win: s0={s0:.4f} s1={s1:.4f}"
                    )
                    result["passed"] = False
                if checks.get("first_wins") is False and first_wins:
                    result["failures"].append(
                        f"expected second to win: s0={s0:.4f} s1={s1:.4f}"
                    )
                    result["passed"] = False

        # -- reinforcement_modifier --
        elif cat == "reinforcement_modifier":
            if "modifier_is_one" in checks:
                mod = compute_reinforcement_modifier(
                    case.get("reinforcement_count", 0)
                )
                if mod != 1.0:
                    result["failures"].append(f"modifier={mod} not 1.0 for zero reinforcement")
                    result["passed"] = False
            if "effective_in_zero_one" in checks:
                mtype = case.get("memory_type", "project")
                stored = case.get("stored_importance", 1.0)
                age = case.get("age_days", 0)
                reinf = case.get("reinforcement_count", 1000)
                eff = _effective(mtype, stored, age, reinf)
                if not (0.0 <= eff <= 1.0):
                    result["failures"].append(f"eff={eff} out of [0,1] with high reinforcement")
                    result["passed"] = False

    except Exception as exc:  # noqa: BLE001
        result["failures"].append(f"exception: {exc}")
        result["passed"] = False

    return result


def _compute_metrics(results: list[dict], cases: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    no_mutation_count = sum(
        1 for r in results
        if any("mutated" in f for f in r["failures"])
    )
    det_failures = sum(
        1 for r in results
        if any("non-deterministic" in f for f in r["failures"])
    )
    ranking_regression = sum(
        1 for r in results
        if r["category"] == "ranking_regression" and not r["passed"]
    )

    # Profile order accuracy
    profile_cases = [r for r in results if r["category"] == "profile_order"]
    profile_accuracy = (
        sum(1 for r in profile_cases if r["passed"]) / len(profile_cases)
        if profile_cases else 1.0
    )

    return {
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "profile_order_accuracy": profile_accuracy,
        "no_mutation_count": no_mutation_count,
        "historical_determinism_failures": det_failures,
        "ranking_regression_count": ranking_regression,
    }


def run_evaluation(fixture_path: Path = FIXTURE_PATH) -> int:
    print(f"\n{'=' * 60}")
    print("  Munin M6 Decay Evaluation")
    print(f"{'=' * 60}\n")

    with open(fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)

    cases = fixture["cases"]
    print(f"Loaded {len(cases)} decay cases\n")

    results: list[dict] = []
    for case in cases:
        result = _run_case(case)
        status = PASS if result["passed"] else FAIL
        print(f"  [{status}] {case['id']:35s}  {case['description'][:50]}")
        for failure in result["failures"]:
            print(f"         ✗ {failure}")
        results.append(result)

    metrics = _compute_metrics(results, cases)

    print(f"\n{'=' * 60}")
    print("  Aggregate Metrics")
    print(f"{'=' * 60}")
    print(f"  total_cases                   : {metrics['total_cases']}")
    print(f"  passed                        : {metrics['passed']}")
    print(f"  failed                        : {metrics['failed']}")
    print(f"  profile_order_accuracy        : {metrics['profile_order_accuracy']:.2%}")
    print()

    targets = [
        ("no_mutation_count",               metrics["no_mutation_count"],               0),
        ("historical_determinism_failures", metrics["historical_determinism_failures"], 0),
        ("ranking_regression_count",        metrics["ranking_regression_count"],        0),
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
