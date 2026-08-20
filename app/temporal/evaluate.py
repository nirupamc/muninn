"""Regression evaluation for temporal relationship decisions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.models.memory import MemoryType
from app.temporal.models import TemporalRelationshipType
from app.temporal.policy import TemporalPolicyConfig, apply_temporal_policy
from app.temporal.providers.deterministic import DeterministicTemporalProvider

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "temporal_cases.json"


def load_cases() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _parse_type(value: str | None) -> MemoryType:
    if not value:
        return MemoryType.other
    return MemoryType(value)


def evaluate_cases(
    cases: list[dict] | None = None,
    *,
    config: TemporalPolicyConfig | None = None,
) -> dict:
    """
    Score temporal classification against fixtures.

    false_supersede_count is the most important safety metric — incorrectly
    superseding active truth destroys current knowledge.
    """
    cases = cases or load_cases()
    provider = DeterministicTemporalProvider()
    policy = config or TemporalPolicyConfig()

    labels = [
        TemporalRelationshipType.NEW,
        TemporalRelationshipType.UPDATES,
        TemporalRelationshipType.CONTRADICTS,
        TemporalRelationshipType.SUPERSEDES,
    ]
    counts = {
        label.value: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for label in labels
    }
    false_supersede = 0
    missed_supersede = 0
    false_contradiction = 0
    details: list[dict] = []

    for case in cases:
        if case.get("skip_pairwise"):
            continue

        analysis = provider.classify(
            candidate=case["candidate"],
            existing_memory=case["existing"],
            candidate_type=_parse_type(case.get("candidate_type")),
            existing_type=_parse_type(case.get("existing_type")),
        )
        outcome = apply_temporal_policy(analysis, config=policy)
        predicted = outcome.relationship
        expected = TemporalRelationshipType(case["expected_relationship"])

        for label in labels:
            if expected == label:
                counts[label.value]["support"] += 1
            if predicted == label and expected == label:
                counts[label.value]["tp"] += 1
            elif predicted == label and expected != label:
                counts[label.value]["fp"] += 1
            elif predicted != label and expected == label:
                counts[label.value]["fn"] += 1

        if expected != TemporalRelationshipType.SUPERSEDES and predicted == TemporalRelationshipType.SUPERSEDES:
            false_supersede += 1

        if expected == TemporalRelationshipType.SUPERSEDES and predicted != TemporalRelationshipType.SUPERSEDES:
            missed_supersede += 1

        if expected != TemporalRelationshipType.CONTRADICTS and predicted == TemporalRelationshipType.CONTRADICTS:
            false_contradiction += 1

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
        "false_supersede_count": false_supersede,
        "missed_supersede_count": missed_supersede,
        "false_contradiction_count": false_contradiction,
        "NEW": _prf("NEW"),
        "UPDATES": _prf("UPDATES"),
        "CONTRADICTS": _prf("CONTRADICTS"),
        "SUPERSEDES": _prf("SUPERSEDES"),
        "details": details,
    }


def main() -> None:
    metrics = evaluate_cases()
    print(
        "Temporal evaluation\n"
        f"  total={metrics['total']}\n"
        f"  accuracy={metrics['accuracy']}\n"
        f"  false_supersede_count={metrics['false_supersede_count']}  (most important)\n"
        f"  missed_supersede_count={metrics['missed_supersede_count']}\n"
        f"  false_contradiction_count={metrics['false_contradiction_count']}\n"
        f"  SUPERSEDES precision={metrics['SUPERSEDES']['precision']} "
        f"recall={metrics['SUPERSEDES']['recall']}\n"
        f"  CONTRADICTS precision={metrics['CONTRADICTS']['precision']} "
        f"recall={metrics['CONTRADICTS']['recall']}\n"
        f"  UPDATES precision={metrics['UPDATES']['precision']} "
        f"recall={metrics['UPDATES']['recall']}\n"
        f"  NEW precision={metrics['NEW']['precision']} "
        f"recall={metrics['NEW']['recall']}"
    )
    if metrics["false_supersede_count"] > 0:
        print("ERROR: false supersedes detected", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
