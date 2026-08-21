"""Context assembly pipeline: candidate retrieval → ranking → formatting."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.context.budget import (
    CONFLICT_HEADER,
    CONTEXT_HEADER,
    format_memory_line,
    format_section,
    select_within_budget,
)
from app.context.models import (
    AssemblyTrace,
    ConflictPair,
    ContextConfig,
    ScoredCandidate,
    SelectedMemory,
    SkipReason,
)
from app.context.scoring import score_candidate, sort_candidates
from app.context.tokenization.simple import SimpleTokenEstimator
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.embeddings.vector_utils import cosine_similarity, deserialize_vector
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.repositories.deduplication_repository import DeduplicationRepository
from app.repositories.embedding_repository import EmbeddingRepository

if TYPE_CHECKING:
    pass

logger = logging.getLogger("munin.context")

# Memory type display names for formatted output
_TYPE_LABELS: dict[MemoryType, str] = {
    MemoryType.project: "Project",
    MemoryType.goal: "Goals",
    MemoryType.decision: "Current decisions",
    MemoryType.procedure: "Procedures",
    MemoryType.fact: "Facts",
    MemoryType.preference: "Preferences",
    MemoryType.relationship: "Relationships",
    MemoryType.event: "Recent events",
    MemoryType.other: "Other",
}


class ContextAssembler:
    """
    Assembles an ordered, budget-constrained set of memories for agent context.

    Pipeline:
        1. Embed query (once)
        2. Retrieve candidates from embedding store (namespace/user/agent/type filtered)
        3. Apply temporal validity filter (valid_from / valid_until at as_of)
        4. Apply superseded filter (unless include_superseded=True)
        5. Score each candidate (semantic + importance + confidence + recency + type + reinforcement)
        6. Sort deterministically
        7. Suppress redundant near-duplicates
        8. Select within token budget
        9. Detect conflict pairs among selected memories
        10. Format output text
    """

    def __init__(
        self,
        db: Session,
        config: ContextConfig,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self.db = db
        self.config = config
        self.provider = provider or get_embedding_provider()
        self.estimator = SimpleTokenEstimator()
        self._embedding_repo = EmbeddingRepository(db)
        self._dedup_repo = DeduplicationRepository(db)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def assemble(
        self,
        *,
        query: str,
        namespace: str,
        user_id: str | None,
        agent_id: str | None,
        as_of: datetime,
        include_superseded: bool,
        memory_types: list[MemoryType] | None,
        max_candidates: int,
        max_memories: int,
        token_budget: int,
    ) -> tuple[list[SelectedMemory], str, int, bool, AssemblyTrace]:
        """
        Run the full pipeline.

        Returns:
            selected      — memories chosen for context
            context_text  — LLM-ready formatted string
            used_tokens   — estimated token count for context_text
            truncated     — True if budget or max_memories cut off candidates
            trace         — assembly decisions for explainability
        """
        t_start = datetime.now(UTC)

        # 1. Embed query once
        query_vector = self.provider.embed_text(query)

        # 2. Retrieve candidates
        statuses = self._build_status_filter(include_superseded)
        raw_candidates = self._embedding_repo.list_search_candidates(
            namespace=namespace,
            provider=self.provider.provider_name,
            model_name=self.provider.model_name,
            dimension=self.provider.dimension,
            user_id=user_id,
            agent_id=agent_id,
            memory_types=memory_types,
            statuses=statuses,
        )

        # 3+4. Score while applying temporal validity + superseded filters
        skip_map: dict[str, list[str]] = {}
        scored: list[ScoredCandidate] = []
        reinforcement_counts = self._load_reinforcement_counts(
            [m.id for m, _ in raw_candidates]
        )

        for memory, embedding_row in raw_candidates:
            # Temporal validity filter
            skip_reason = self._temporal_validity_skip(memory, as_of, include_superseded)
            if skip_reason:
                skip_map.setdefault(memory.id, []).append(skip_reason.value)
                continue

            stored_vec = deserialize_vector(embedding_row.embedding)
            sem_score = float(cosine_similarity(query_vector, stored_vec))

            candidate = score_candidate(
                memory=memory,
                semantic_score=sem_score,
                reinforcement_count=reinforcement_counts.get(memory.id, 0),
                query=query,
                as_of=as_of,
                config=self.config,
            )
            scored.append(candidate)

        # Limit to max_candidates before expensive steps
        scored = sort_candidates(scored)[:max_candidates]

        # 5. Redundancy suppression
        deduplicated, redundant_skipped = self._suppress_redundant(
            scored, threshold=self.config.redundancy_threshold
        )
        skip_map.update(redundant_skipped)

        # 6. Select within budget
        selected, used_tokens, truncated, budget_skipped = select_within_budget(
            ranked=deduplicated,
            max_memories=max_memories,
            token_budget=token_budget,
            estimator=self.estimator,
            header=CONTEXT_HEADER,
        )
        skip_map.update(budget_skipped)

        # 7. Detect conflicts among selected
        conflict_pairs = self._detect_conflicts(selected)

        # 8. Format
        context_text = self._format_context(selected, conflict_pairs, used_tokens, token_budget)

        # Re-estimate tokens on the actual final string
        final_tokens = self.estimator.count(context_text)

        trace = AssemblyTrace(
            candidate_count=len(raw_candidates),
            selected_count=len(selected),
            skipped=skip_map,
            conflict_pairs=conflict_pairs,
        )

        elapsed = (datetime.now(UTC) - t_start).total_seconds()
        logger.info(
            "context assembly namespace=%s candidates=%d scored=%d selected=%d tokens=%d truncated=%s elapsed=%.3fs",
            namespace,
            len(raw_candidates),
            len(scored),
            len(selected),
            final_tokens,
            truncated,
            elapsed,
        )

        return selected, context_text, final_tokens, truncated, trace

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_status_filter(self, include_superseded: bool) -> list[MemoryStatus]:
        if include_superseded:
            return [MemoryStatus.active, MemoryStatus.superseded]
        return [MemoryStatus.active]

    def _temporal_validity_skip(
        self,
        memory: Memory,
        as_of: datetime,
        include_superseded: bool,
    ) -> SkipReason | None:
        """Return a SkipReason if this memory should be excluded, else None."""
        # Superseded filter (belt-and-suspenders — the DB query already filters
        # when include_superseded=False, but we guard in-process too).
        if not include_superseded and memory.status == MemoryStatus.superseded:
            return SkipReason.SUPERSEDED

        # Temporal validity window
        # Ensure both datetimes are comparable (make as_of timezone-aware if needed)
        as_of_aware = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)

        if memory.valid_from is not None:
            vf = memory.valid_from if memory.valid_from.tzinfo is not None else memory.valid_from.replace(tzinfo=UTC)
            if vf > as_of_aware:
                return SkipReason.NOT_VALID_AT_AS_OF

        if memory.valid_until is not None:
            vu = memory.valid_until if memory.valid_until.tzinfo is not None else memory.valid_until.replace(tzinfo=UTC)
            if vu < as_of_aware:
                return SkipReason.NOT_VALID_AT_AS_OF

        return None

    def _load_reinforcement_counts(self, memory_ids: list[str]) -> dict[str, int]:
        """
        Load reinforcement counts for all candidates in one batch.

        Avoids N+1 queries by querying in bulk via the dedup repo.
        """
        if not memory_ids:
            return {}
        from sqlalchemy import func, select
        from app.models.deduplication import MemoryReinforcement

        stmt = (
            select(MemoryReinforcement.memory_id, func.count(MemoryReinforcement.id))
            .where(MemoryReinforcement.memory_id.in_(memory_ids))
            .group_by(MemoryReinforcement.memory_id)
        )
        rows = self.db.execute(stmt).all()
        return {row[0]: row[1] for row in rows}

    def _suppress_redundant(
        self,
        ranked: list[ScoredCandidate],
        threshold: float,
    ) -> tuple[list[ScoredCandidate], dict[str, list[str]]]:
        """
        Remove near-duplicate candidates using cosine similarity on stored vectors.

        Keeps the highest-ranked candidate; skips any that are too similar to
        already-selected items. Does NOT delete or mutate memories.
        """
        skipped: dict[str, list[str]] = {}
        selected: list[ScoredCandidate] = []
        selected_vectors: list[list[float]] = []

        for candidate in ranked:
            emb_row = self._embedding_repo.get_by_memory_id(candidate.memory.id)
            if emb_row is None:
                # No embedding: include it (can't compare)
                selected.append(candidate)
                selected_vectors.append([])
                continue

            current_vec = deserialize_vector(emb_row.embedding)

            too_similar = False
            for sel_vec in selected_vectors:
                if not sel_vec:
                    continue
                sim = cosine_similarity(current_vec, sel_vec)
                if sim >= threshold:
                    too_similar = True
                    break

            if too_similar:
                skipped.setdefault(candidate.memory.id, []).append(SkipReason.REDUNDANT.value)
            else:
                selected.append(candidate)
                selected_vectors.append(current_vec.tolist())

        return selected, skipped

    def _detect_conflicts(
        self, selected: list[SelectedMemory]
    ) -> list[ConflictPair]:
        """
        Identify pairs of selected active memories that contradict each other.

        Uses temporal decision audit data: if memory A was superseded when memory B
        was created (relationship=SUPERSEDES or CONTRADICTS), but both remain active
        (unresolved contradiction), mark them as a conflict pair.
        """
        from app.models.temporal import MemoryTemporalDecision

        if len(selected) < 2:
            return []

        id_set = {m.memory_id for m in selected}
        pairs: list[ConflictPair] = []
        seen: set[frozenset] = set()

        for mem in selected:
            decisions = self._get_temporal_decisions_for_memory(mem.memory_id)
            for dec in decisions:
                # Look for CONTRADICTS relationships where both memories are selected
                if dec.relationship not in ("CONTRADICTS", "SUPERSEDES"):
                    continue
                other_id = (
                    dec.matched_memory_id
                    if dec.created_memory_id == mem.memory_id
                    else dec.created_memory_id
                )
                if other_id is None or other_id not in id_set:
                    continue
                pair_key = frozenset({mem.memory_id, other_id})
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                other = next((m for m in selected if m.memory_id == other_id), None)
                if other is None:
                    continue

                pairs.append(
                    ConflictPair(
                        memory_id_a=mem.memory_id,
                        content_a=mem.content,
                        memory_id_b=other.memory_id,
                        content_b=other.content,
                    )
                )

        return pairs

    def _get_temporal_decisions_for_memory(self, memory_id: str):
        from app.repositories.temporal_repository import TemporalRepository

        repo = TemporalRepository(self.db)
        return repo.list_for_memory(memory_id)

    def _format_context(
        self,
        selected: list[SelectedMemory],
        conflict_pairs: list[ConflictPair],
        used_tokens: int,
        token_budget: int,
    ) -> str:
        """Produce LLM-friendly formatted context grouped by memory type."""
        if not selected and not conflict_pairs:
            return ""

        # IDs involved in conflicts — format them separately
        conflict_ids: set[str] = set()
        for pair in conflict_pairs:
            conflict_ids.add(pair.memory_id_a)
            conflict_ids.add(pair.memory_id_b)

        # Group non-conflict memories by type
        by_type: dict[MemoryType, list[str]] = {}
        for mem in selected:
            if mem.memory_id in conflict_ids:
                continue
            by_type.setdefault(mem.memory_type, []).append(mem.content)

        sections: list[str] = [CONTEXT_HEADER]

        # Emit each type section in a stable priority order
        type_order = [
            MemoryType.project,
            MemoryType.goal,
            MemoryType.decision,
            MemoryType.procedure,
            MemoryType.fact,
            MemoryType.preference,
            MemoryType.relationship,
            MemoryType.event,
            MemoryType.other,
        ]
        for mtype in type_order:
            contents = by_type.get(mtype)
            if not contents:
                continue
            label = _TYPE_LABELS.get(mtype, mtype.value.capitalize())
            lines = [format_memory_line(c) for c in contents]
            sec = format_section(label, lines)
            if sec:
                sections.append("")
                sections.append(sec)

        # Conflict section
        if conflict_pairs:
            conflict_lines: list[str] = []
            seen_conflicts: set[frozenset] = set()
            for pair in conflict_pairs:
                key = frozenset({pair.memory_id_a, pair.memory_id_b})
                if key in seen_conflicts:
                    continue
                seen_conflicts.add(key)
                conflict_lines.append(format_memory_line(pair.content_a))
                conflict_lines.append(format_memory_line(pair.content_b))
            sec = format_section("Unresolved conflicts", conflict_lines)
            if sec:
                sections.append("")
                sections.append(sec)

        return "\n".join(sections)
