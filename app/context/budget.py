"""Token budget selection for context assembly."""

from __future__ import annotations

from app.context.models import (
    ContextConfig,
    ScoredCandidate,
    SelectedMemory,
    SkipReason,
)
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
    hierarchical: bool = False,
) -> tuple[list[SelectedMemory], int, bool, dict[str, list[str]]]:
    """
    Select complete memories that fit within the token budget.

    When hierarchical=False (default), uses full L2 content — original behavior.
    When hierarchical=True, uses M10 representation selection to choose
    the best representation level (L0/L1/L2) for each memory based on
    remaining budget and importance.
    """
    from app.memory.representations.models import ContextState, RepresentationLevel
    from app.memory.representations.service import RepresentationService

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

        # M10: Hierarchical representation selection
        if hierarchical:
            context_state = ContextState(
                token_budget=token_budget,
                remaining_budget=token_budget - used_tokens,
                memories_selected=len(selected),
                max_memories=max_memories,
                query="",  # Not needed for current selection logic
            )
            selection = RepresentationService.select_representation(
                memory=candidate.memory,
                context_state=context_state,
                estimator=estimator,
            )
            line = selection.text
            line_tokens = selection.token_cost
            representation_level = selection.level
            selection_reason = selection.selection_reason
        else:
            line = format_memory_line(candidate.memory.content)
            line_tokens = estimator.count(line)
            representation_level = RepresentationLevel.L2_FULL
            selection_reason = "flat_l2"

        if used_tokens + line_tokens > token_budget:
            # M10: If full content doesn't fit, try a smaller representation
            if hierarchical and candidate.memory.gist:
                from app.memory.representations.models import RepresentationLevel
                l0_line = format_memory_line(candidate.memory.gist)
                l0_tokens = estimator.count(l0_line)
                if used_tokens + l0_tokens <= token_budget:
                    line = l0_line
                    line_tokens = l0_tokens
                    representation_level = RepresentationLevel.L0_GIST
                    selection_reason = "downgraded_to_l0_for_budget"
                else:
                    skipped.setdefault(candidate.memory.id, []).append(SkipReason.OUT_OF_BUDGET.value)
                    truncated = True
                    continue
            elif hierarchical and candidate.memory.summary:
                from app.memory.representations.models import RepresentationLevel
                l1_line = format_memory_line(candidate.memory.summary)
                l1_tokens = estimator.count(l1_line)
                if used_tokens + l1_tokens <= token_budget:
                    line = l1_line
                    line_tokens = l1_tokens
                    representation_level = RepresentationLevel.L1_SUMMARY
                    selection_reason = "downgraded_to_l1_for_budget"
                else:
                    skipped.setdefault(candidate.memory.id, []).append(SkipReason.OUT_OF_BUDGET.value)
                    truncated = True
                    continue
            else:
                skipped.setdefault(candidate.memory.id, []).append(SkipReason.OUT_OF_BUDGET.value)
                truncated = True
                continue

        # Build the display content for the selected representation
        display_content = line[2:] if line.startswith("- ") else line

        selected.append(
            SelectedMemory(
                memory_id=candidate.memory.id,
                memory_type=candidate.memory.memory_type,
                content=display_content,
                semantic_score=candidate.semantic_score,
                importance=candidate.importance,
                confidence=candidate.confidence,
                recency_score=candidate.recency_score,
                type_relevance=candidate.type_relevance,
                reinforcement_score=candidate.reinforcement_score,
                final_score=candidate.final_score,
                estimated_tokens=line_tokens,
                reason_codes=list(candidate.reason_codes),
                representation_level=representation_level or RepresentationLevel.L2_FULL,
                selection_reason=selection_reason,
            )
        )
        used_tokens += line_tokens

    return selected, used_tokens, truncated, skipped
