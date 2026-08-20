"""Regression evaluation for admission decisions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.admission.providers.deterministic import DeterministicAdmissionProvider
from app.admission.rules import AdmissionPolicyConfig, apply_admission_policy

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "admission_cases.json"


def load_cases() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def evaluate_cases(
    cases: list[dict] | None = None,
    *,
    config: AdmissionPolicyConfig | None = None,
) -> dict:
    """Compute simple STORE/IGNORE regression metrics against fixtures."""
    cases = cases or load_cases()
    provider = DeterministicAdmissionProvider()
    policy = config or AdmissionPolicyConfig()

    tp = fp = tn = fn = 0
    details: list[dict] = []

    for case in cases:
        analysis = provider.analyze_event(role=case.get("role", "user"), content=case["content"])
        decisions = [
            apply_admission_policy(item, source_event_content=case["content"], config=policy)
            for item in analysis.candidates
        ]

        expected = case["expected_decision"]
        expected_type = case.get("expected_memory_type")

        if expected == "STORE":
            stored = [d for d in decisions if d.decision == "STORE"]
            ok = bool(stored)
            if ok and expected_type:
                ok = any(
                    d.candidate.memory_type.value == expected_type for d in stored
                )
            if ok:
                tp += 1
            else:
                fn += 1
            predicted = "STORE" if stored else "IGNORE"
        else:
            # IGNORE expected: no STORE decisions (or only IGNORE)
            stored = [d for d in decisions if d.decision == "STORE"]
            if not stored:
                tn += 1
                predicted = "IGNORE"
                ok = True
            else:
                fp += 1
                predicted = "STORE"
                ok = False

        details.append(
            {
                "id": case.get("id"),
                "ok": ok,
                "expected": expected,
                "predicted": predicted,
                "content": case["content"][:80],
            }
        )

    total = tp + tn + fp + fn
    accuracy = (tp + tn) / total if total else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    return {
        "total": total,
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
        "accuracy": round(accuracy, 4),
        "precision_store": round(precision, 4),
        "recall_store": round(recall, 4),
        "details": details,
    }


def main() -> None:
    metrics = evaluate_cases()
    print(
        "Admission evaluation\n"
        f"  total={metrics['total']}\n"
        f"  accuracy={metrics['accuracy']}\n"
        f"  precision_store={metrics['precision_store']}\n"
        f"  recall_store={metrics['recall_store']}\n"
        f"  TP={metrics['true_positive']} FP={metrics['false_positive']} "
        f"TN={metrics['true_negative']} FN={metrics['false_negative']}"
    )
    failed = [d for d in metrics["details"] if not d["ok"]]
    if failed:
        print("\nFailures:")
        for item in failed:
            print(f"  - {item['id']}: expected={item['expected']} predicted={item['predicted']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
    sys.exit(0)
