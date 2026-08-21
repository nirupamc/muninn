"""Regression evaluation for deduplication relationship decisions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.deduplication.models import RelationshipType
from app.deduplication.policy import DedupPolicyConfig, apply_relationship_policy
from app.deduplication.providers.deterministic import DeterministicRelationshipProvider
from app.deduplication.state_change import contains_state_change_signal
from app.models.memory import MemoryType

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "dedup_cases.json"
BOUNDARY_FIXTURES = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "dedup_boundary_cases.json"
)


def load_cases() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def load_boundary_cases() -> list[dict]:
    return json.loads(BOUNDARY_FIXTURES.read_text(encoding="utf-8"))


def _parse_type(value: str | None) -> MemoryType:
    if not value:
        return MemoryType.other
    return MemoryType(value)


def evaluate_cases(
    cases: list[dict] | None = None,
    *,
    config: DedupPolicyConfig | None = None,
) -> dict:
    """
    Score relationship classification against fixtures.

    False merges (predicting DUPLICATE/REINFORCES when expected NEW) are the
    most important failure mode — they destroy distinct information.
    """
    cases = cases or load_cases()
    provider = DeterministicRelationshipProvider()
    policy = config or DedupPolicyConfig()

    labels = [RelationshipType.NEW, RelationshipType.DUPLICATE, RelationshipType.REINFORCES]
    counts = {
        label.value: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for label in labels
    }
    false_merge = 0
    missed_duplicate = 0
    details: list[dict] = []

    for case in cases:
        # Skip isolation-only cases that are not pure pairwise classifications
        if case.get("skip_pairwise"):
            continue

        analysis = provider.classify(
            candidate=case["candidate"],
            existing_memory=case["existing"],
            candidate_type=_parse_type(case.get("candidate_type")),
            existing_type=_parse_type(case.get("existing_type")),
        )
        outcome = apply_relationship_policy(analysis, config=policy)
        predicted = outcome.relationship
        expected = RelationshipType(case["expected_relationship"])

        for label in labels:
            if expected == label:
                counts[label.value]["support"] += 1
            if predicted == label and expected == label:
                counts[label.value]["tp"] += 1
            elif predicted == label and expected != label:
                counts[label.value]["fp"] += 1
            elif predicted != label and expected == label:
                counts[label.value]["fn"] += 1

        # False merge: predicted merge when truth is NEW
        if expected == RelationshipType.NEW and predicted in {
            RelationshipType.DUPLICATE,
            RelationshipType.REINFORCES,
        }:
            false_merge += 1

        # Missed duplicate: truth DUPLICATE but predicted NEW
        if expected == RelationshipType.DUPLICATE and predicted == RelationshipType.NEW:
            missed_duplicate += 1

        details.append(
            {
                "id": case.get("id"),
                "ok": predicted == expected,
                "expected": expected.value,
                "predicted": predicted.value,
                "confidence": outcome.confidence,
            }
        )

    evaluated = len(details)
    correct = sum(1 for d in details if d["ok"])
    accuracy = correct / evaluated if evaluated else 0.0

    def _prf(label: str) -> dict:
        tp = counts[label]["tp"]
        fp = counts[label]["fp"]
        fn = counts[label]["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "support": counts[label]["support"],
        }

    return {
        "total": evaluated,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "false_merge_count": false_merge,
        "missed_duplicate_count": missed_duplicate,
        "NEW": _prf("NEW"),
        "DUPLICATE": _prf("DUPLICATE"),
        "REINFORCES": _prf("REINFORCES"),
        "details": details,
    }


def evaluate_boundary_cases(
    cases: list[dict] | None = None,
    *,
    config: DedupPolicyConfig | None = None,
) -> dict:
    """Score M3 boundary cases where state-change candidates must not become DUPLICATE."""
    cases = cases or load_boundary_cases()
    provider = DeterministicRelationshipProvider()
    policy = config or DedupPolicyConfig()

    false_duplicate_on_temporal_change = 0
    state_change_swallowed = 0
    details: list[dict] = []

    for case in cases:
        analysis = provider.classify(
            candidate=case["candidate"],
            existing_memory=case["existing"],
            candidate_type=_parse_type(case.get("candidate_type")),
            existing_type=_parse_type(case.get("existing_type")),
        )
        outcome = apply_relationship_policy(analysis, config=policy)
        predicted = outcome.relationship
        expected = RelationshipType(case["expected_relationship"])
        is_state_change = contains_state_change_signal(case["candidate"])

        if is_state_change and predicted == RelationshipType.DUPLICATE:
            false_duplicate_on_temporal_change += 1
            state_change_swallowed += 1

        details.append(
            {
                "id": case.get("id"),
                "ok": predicted == expected,
                "expected": expected.value,
                "predicted": predicted.value,
                "state_change_candidate": is_state_change,
            }
        )

    evaluated = len(details)
    correct = sum(1 for d in details if d["ok"])
    return {
        "total": evaluated,
        "correct": correct,
        "accuracy": round(correct / evaluated, 4) if evaluated else 0.0,
        "false_duplicate_on_temporal_change_count": false_duplicate_on_temporal_change,
        "state_change_swallowed_count": state_change_swallowed,
        "details": details,
    }


def main() -> None:
    metrics = evaluate_cases()
    boundary = evaluate_boundary_cases()
    print(
        "Deduplication evaluation\n"
        f"  total={metrics['total']}\n"
        f"  accuracy={metrics['accuracy']}\n"
        f"  false_merge_count={metrics['false_merge_count']}  (most important)\n"
        f"  missed_duplicate_count={metrics['missed_duplicate_count']}\n"
        f"  DUPLICATE precision={metrics['DUPLICATE']['precision']} "
        f"recall={metrics['DUPLICATE']['recall']}\n"
        f"  REINFORCES precision={metrics['REINFORCES']['precision']} "
        f"recall={metrics['REINFORCES']['recall']}\n"
        f"  NEW precision={metrics['NEW']['precision']} "
        f"recall={metrics['NEW']['recall']}\n"
        f"Boundary cases total={boundary['total']} accuracy={boundary['accuracy']}\n"
        f"  false_duplicate_on_temporal_change_count="
        f"{boundary['false_duplicate_on_temporal_change_count']}\n"
        f"  state_change_swallowed_count={boundary['state_change_swallowed_count']}"
    )
    # Fail CI-style if false merges appear on fixtures
    if metrics["false_merge_count"] > 0:
        print("ERROR: false merges detected", file=sys.stderr)
        raise SystemExit(1)
    if boundary["false_duplicate_on_temporal_change_count"] > 0:
        print("ERROR: state-change candidates swallowed as DUPLICATE", file=sys.stderr)
        raise SystemExit(1)
    if boundary["state_change_swallowed_count"] > 0:
        print("ERROR: state-change candidates swallowed as DUPLICATE", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
