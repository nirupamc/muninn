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
from app.retrieval.models import HybridRetrievalResult, RetrievalMode
from app.retrieval.service import HybridRetriever

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
        # M11: Hybrid retriever (lazy init on first use)
        self._hybrid_retriever: HybridRetriever | None = None
        self._retrieval_mode: RetrievalMode | None = None

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

        # M11: Use hybrid retrieval if configured
        hybrid_result: HybridRetrievalResult | None = None
        if self._retrieval_mode and self._retrieval_mode != RetrievalMode.DENSE:
            hybrid_result = self._run_hybrid_retrieval(
                query=query,
                namespace=namespace,
                user_id=user_id,
                agent_id=agent_id,
                memory_types=memory_types,
                include_superseded=include_superseded,
                limit=max_candidates,
            )

        # 1. Embed query once (always needed for dense component or fallback)
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

        # M11: Build a lookup for hybrid scores if available
        hybrid_score_lookup: dict[str, float] = {}
        hybrid_channel_lookup: dict[str, int] = {}
        if hybrid_result and hybrid_result.candidates:
            for fc in hybrid_result.candidates:
                hybrid_score_lookup[fc.memory_id] = fc.rrf_score
                hybrid_channel_lookup[fc.memory_id] = fc.channel_count

        for memory, embedding_row in raw_candidates:
            # Temporal validity filter
            skip_reason = self._temporal_validity_skip(memory, as_of, include_superseded)
            if skip_reason:
                skip_map.setdefault(memory.id, []).append(skip_reason.value)
                continue

            stored_vec = deserialize_vector(embedding_row.embedding)
            sem_score = float(cosine_similarity(query_vector, stored_vec))

            # M11: Blend semantic score with hybrid RRF score if available
            effective_semantic = sem_score
            if memory.id in hybrid_score_lookup:
                # Combine: 70% original semantic + 30% RRF boost
                rrf_boost = hybrid_score_lookup[memory.id]
                effective_semantic = min(1.0, sem_score * 0.7 + rrf_boost * 0.3)

            candidate = score_candidate(
                memory=memory,
                semantic_score=effective_semantic,
                reinforcement_count=reinforcement_counts.get(memory.id, 0),
                query=query,
                as_of=as_of,
                config=self.config,
            )
            scored.append(candidate)

        # M11: Also add candidates that came ONLY from lexical/graph (not in dense)
        if hybrid_result and hybrid_result.candidates:
            dense_ids = {m.id for m, _ in raw_candidates}
            for fc in hybrid_result.candidates:
                if fc.memory_id not in dense_ids:
                    # This candidate came only from lexical/graph — load it
                    from app.models.memory import Memory as MemoryModel

                    mem = self.db.get(MemoryModel, fc.memory_id)
                    if mem is not None:
                        # Apply temporal filter
                        skip_reason = self._temporal_validity_skip(mem, as_of, include_superseded)
                        if skip_reason:
                            skip_map.setdefault(mem.id, []).append(skip_reason.value)
                            continue

                        # Score with hybrid RRF as semantic proxy
                        candidate = score_candidate(
                            memory=mem,
                            semantic_score=fc.rrf_score,
                            reinforcement_count=reinforcement_counts.get(mem.id, 0),
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

        # 6. Select within budget (M10: hierarchical representation selection)
        selected, used_tokens, truncated, budget_skipped = select_within_budget(
            ranked=deduplicated,
            max_memories=max_memories,
            token_budget=token_budget,
            estimator=self.estimator,
            header=CONTEXT_HEADER,
            hierarchical=True,
        )
        skip_map.update(budget_skipped)

        # 7. Detect conflicts among selected
        conflict_pairs = self._detect_conflicts(selected)

        # 8. Format
        context_text = self._format_context(selected, conflict_pairs, used_tokens, token_budget)

        # Re-estimate tokens on the actual final string
        final_tokens = self.estimator.count(context_text)

        # Build M10 representation trace
        from app.context.models import RepresentationTraceEntry
        from app.memory.representations.models import RepresentationLevel

        rep_trace: list[RepresentationTraceEntry] = []
        for rank, mem in enumerate(selected, start=1):
            available_levels: list[RepresentationLevel] = [RepresentationLevel.L2_FULL]
            if mem.representation_level == RepresentationLevel.L0_GIST:
                available_levels = [RepresentationLevel.L0_GIST, RepresentationLevel.L2_FULL]
            elif mem.representation_level == RepresentationLevel.L1_SUMMARY:
                available_levels = [RepresentationLevel.L1_SUMMARY, RepresentationLevel.L2_FULL]

            rep_trace.append(
                RepresentationTraceEntry(
                    memory_id=mem.memory_id,
                    selected_level=mem.representation_level,
                    available_levels=available_levels,
                    token_cost=mem.estimated_tokens,
                    importance=mem.importance,
                    final_rank=rank,
                    selection_reason=mem.selection_reason,
                )
            )

        # M11: Build retrieval trace from hybrid result
        from app.context.models import RetrievalTraceEntry

        retrieval_trace_entries: list[RetrievalTraceEntry] = []
        if hybrid_result:
            for rt in hybrid_result.traces:
                retrieval_trace_entries.append(
                    RetrievalTraceEntry(
                        source=rt.source.value,
                        candidate_count=rt.candidate_count,
                        hit_count=len(rt.hits),
                        elapsed_seconds=rt.elapsed_seconds,
                        error=rt.error,
                    )
                )

        trace = AssemblyTrace(
            candidate_count=len(raw_candidates),
            selected_count=len(selected),
            skipped=skip_map,
            conflict_pairs=conflict_pairs,
            representation_trace=rep_trace,
            retrieval_trace=retrieval_trace_entries,
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
    # M11: Hybrid retrieval
    # ------------------------------------------------------------------

    def set_retrieval_mode(self, mode: RetrievalMode) -> None:
        """Set the retrieval mode for this assembler instance."""
        self._retrieval_mode = mode
        if mode != RetrievalMode.DENSE and self._hybrid_retriever is None:
            self._hybrid_retriever = HybridRetriever(self.db, self.provider, mode=mode)

    def _run_hybrid_retrieval(
        self,
        *,
        query: str,
        namespace: str,
        user_id: str | None,
        agent_id: str | None,
        memory_types: list[MemoryType] | None,
        include_superseded: bool,
        limit: int,
    ) -> HybridRetrievalResult:
        """Run hybrid retrieval and return the result."""
        if self._hybrid_retriever is None:
            self._hybrid_retriever = HybridRetriever(self.db, self.provider, mode=self._retrieval_mode)

        return self._hybrid_retriever.search(
            query=query,
            namespace=namespace,
            user_id=user_id,
            agent_id=agent_id,
            memory_types=memory_types,
            include_superseded=include_superseded,
            limit=limit,
        )

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
