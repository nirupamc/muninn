"""M10 — Representation service.

Core responsibilities:
1. Generate representations (L0 gist, L1 summary) for a memory
2. Select appropriate representation level for context assembly
3. Backfill existing memories that lack representations

Design:
- Generation failures never prevent memory storage
- Representations are generated after memory persistence (non-blocking)
- Backfill is idempotent and batch-safe
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.memory.representations.models import (
    ContextState,
    RepresentationLevel,
    RepresentationResult,
    RepresentationSelection,
)
from app.memory.representations.providers import generate_representations
from app.models.memory import Memory, MemoryStatus
from app.repositories.memory_repository import MemoryRepository

if TYPE_CHECKING:
    from app.context.tokenization.base import TokenEstimator

logger = logging.getLogger("munin.representations")


class RepresentationService:
    """Service for generating and selecting hierarchical representations."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.memory_repo = MemoryRepository(db)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate_for_memory(self, memory: Memory) -> RepresentationResult:
        """Generate representations for a single memory.

        Updates the memory's gist and summary fields if the memory exists.
        Returns the generation result for inspection/logging.

        Failure-safe: exceptions are caught and logged; memory is never lost.
        """
        try:
            result = generate_representations(memory.content)
        except Exception as exc:
            logger.warning(
                "Representation generation failed for memory %s: %s",
                memory.id,
                exc,
            )
            return RepresentationResult(
                gist=None,
                summary=None,
                provider="deterministic",
                generated=False,
            )

        if not result.generated:
            logger.debug(
                "No representations generated for memory %s (empty content?)",
                memory.id,
            )
            return result

        # Update memory in-place (caller commits)
        memory.gist = result.gist
        memory.summary = result.summary
        self.db.add(memory)

        logger.debug(
            "Generated representations for memory %s: gist=%d chars, summary=%d chars",
            memory.id,
            len(result.gist) if result.gist else 0,
            len(result.summary) if result.summary else 0,
        )

        return result

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    @staticmethod
    def select_representation(
        memory: Memory,
        context_state: ContextState,
        estimator: TokenEstimator | None = None,
    ) -> RepresentationSelection:
        """Select the appropriate representation level for a memory.

        Selection logic:
        1. Determine which levels are available (gist/summary/content always available)
        2. Estimate token costs for each available level
        3. Choose the best level based on budget constraints and importance

        This is a static method to keep it testable without DB dependencies.
        """
        from app.context.tokenization.simple import SimpleTokenEstimator

        if estimator is None:
            estimator = SimpleTokenEstimator()

        # Build available levels with their text and token costs
        available: list[tuple[RepresentationLevel, str, int]] = []

        # L0 — gist (if available)
        if memory.gist:
            l0_text = f"- {memory.gist}"
            l0_cost = estimator.count(l0_text)
            available.append((RepresentationLevel.L0_GIST, l0_text, l0_cost))

        # L1 — summary (if available)
        if memory.summary:
            l1_text = f"- {memory.summary}"
            l1_cost = estimator.count(l1_text)
            available.append((RepresentationLevel.L1_SUMMARY, l1_text, l1_cost))

        # L2 — full content (always available)
        l2_text = f"- {memory.content}"
        l2_cost = estimator.count(l2_text)
        available.append((RepresentationLevel.L2_FULL, l2_text, l2_cost))

        if not available:
            # Should never happen (L2 is always available)
            return RepresentationSelection(
                level=RepresentationLevel.L2_FULL,
                text=f"- {memory.content}",
                token_cost=estimator.count(f"- {memory.content}"),
                selection_reason="fallback_no_representations",
            )

        # Selection strategy:
        # 1. If remaining budget is very tight, prefer smaller representations
        # 2. If remaining budget is comfortable, prefer larger representations
        # 3. Use importance to influence the choice

        remaining = context_state.remaining_budget
        total_available = len(available)

        # Tight budget: fit more memories by using smaller representations
        # Threshold: if remaining budget can't fit 3 full L2 memories, start downsizing
        avg_l2_cost = l2_cost  # Use this memory's L2 cost as reference
        if remaining < avg_l2_cost * 3 and memory.importance < 0.7:
            # Very tight budget + low importance → use smallest available
            best = available[0]  # Sorted by size (L0 < L1 < L2)
            reason = "tight_budget_low_importance"
        elif remaining < avg_l2_cost * 2 and memory.importance < 0.5:
            # Tight budget + medium importance → prefer L1 if available
            if len(available) >= 2 and available[1][0] == RepresentationLevel.L1_SUMMARY:
                best = available[1]
                reason = "tight_budget_medium_importance"
            else:
                best = available[0]
                reason = "tight_budget_fallback"
        else:
            # Comfortable budget → use full L2 (most informative)
            best = available[-1]  # L2 (last in list)
            reason = "sufficient_budget"

        return RepresentationSelection(
            level=best[0],
            text=best[1],
            token_cost=best[2],
            selection_reason=reason,
        )

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------

    def backfill(
        self,
        *,
        batch_size: int = 100,
        dry_run: bool = False,
        skip_existing: bool = True,
    ) -> dict[str, int]:
        """Backfill representations for existing memories.

        Idempotent: memories with gist+summary already set are skipped by default.

        Returns a summary dict with counts:
        - scanned: total memories examined
        - updated: memories that received new representations
        - skipped: memories already having representations
        - failed: memories where generation failed
        """
        stats = {"scanned": 0, "updated": 0, "skipped": 0, "failed": 0}

        offset = 0
        while True:
            memories = self.memory_repo.list(
                status=MemoryStatus.active,
                limit=batch_size,
                offset=offset,
            )

            if not memories:
                break

            for memory in memories:
                stats["scanned"] += 1

                # Skip if already has representations
                if skip_existing and memory.gist is not None and memory.summary is not None:
                    stats["skipped"] += 1
                    continue

                if dry_run:
                    stats["updated"] += 1
                    continue

                result = self.generate_for_memory(memory)
                if result.generated:
                    stats["updated"] += 1
                else:
                    stats["failed"] += 1

            offset += batch_size

            # Commit after each batch (except dry run)
            if not dry_run:
                try:
                    self.db.commit()
                except Exception as exc:
                    logger.error("Backfill batch commit failed: %s", exc)
                    self.db.rollback()

        return stats
