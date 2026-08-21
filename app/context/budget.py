"""Token budget selection for context assembly."""

from __future__ import annotations

from app.context.models import ScoredCandidate, SelectedMemory, SkipReason
from app.context.tokenization.base import TokenEstimator


CONTEXT_HEADER = "Relevant durable memory:"
CONFLICT_HEADER = "[Unresolved conflicts]"


def format_memory_line(content: str) -> str:
    return f"- {content.strip()}"


def format_section(title: str, lines: list[str]) -> str:
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"[{title}]\n{body}"


def estimate_context_tokens(text: str, estimator: TokenEstimator) -> int:
    return estimator.count(text)


def select_within_budget(
    *,
    ranked: list[ScoredCandidate],
    max_memories: int,
    token_budget: int,
    estimator: TokenEstimator,
    header: str = CONTEXT_HEADER,
) -> tuple[list[SelectedMemory], int, bool, dict[str, list[str]]]:
    """
    Select complete memories that fit within the token budget.

    Prefers fewer complete memories over truncating content mid-fact.
    """
    skipped: dict[str, list[str]] = {}
    selected: list[SelectedMemory] = []
    header_tokens = estimator.count(header)
    used_tokens = header_tokens
    truncated = False

    if token_budget < header_tokens:
        return [], 0, True, skipped

    for candidate in ranked:
        if len(selected) >= max_memories:
            skipped.setdefault(candidate.memory.id, []).append(SkipReason.MAX_MEMORIES.value)
            truncated = True
            continue

        line = format_memory_line(candidate.memory.content)
        line_tokens = estimator.count(line)

        if used_tokens + line_tokens > token_budget:
            skipped.setdefault(candidate.memory.id, []).append(SkipReason.OUT_OF_BUDGET.value)
            truncated = True
            continue

        selected.append(
            SelectedMemory(
                memory_id=candidate.memory.id,
                memory_type=candidate.memory.memory_type,
                content=candidate.memory.content,
                semantic_score=candidate.semantic_score,
                importance=candidate.importance,
                confidence=candidate.confidence,
                recency_score=candidate.recency_score,
                type_relevance=candidate.type_relevance,
                reinforcement_score=candidate.reinforcement_score,
                final_score=candidate.final_score,
                estimated_tokens=line_tokens,
                reason_codes=list(candidate.reason_codes),
            )
        )
        used_tokens += line_tokens

    return selected, used_tokens, truncated, skipped
