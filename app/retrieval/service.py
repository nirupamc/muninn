"""M11 — Hybrid retriever service.

Orchestrates dense, lexical, and graph retrieval channels with RRF
fusion. Replaces the direct dense-only retrieval in ContextAssembler.

Design:
- Channels are independently testable
- Missing/failed channels degrade gracefully
- Temporal truth is preserved (RRF is candidate fusion, not truth)
- Namespace isolation enforced within each channel
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.embeddings.base import EmbeddingProvider
from app.models.memory import MemoryType
from app.retrieval.dense import DenseRetriever
from app.retrieval.fusion import build_hybrid_result
from app.retrieval.graph import GraphRetriever
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.models import (
    HybridRetrievalResult,
    RetrievalMode,
)

logger = logging.getLogger("munin.retrieval")


class HybridRetriever:
    """Hybrid retrieval orchestrator.

    Runs dense, lexical, and (optionally) graph retrieval, fuses
    results with RRF, and returns a unified candidate list with trace.
    """

    def __init__(
        self,
        db: Session,
        provider: EmbeddingProvider,
        *,
        mode: RetrievalMode | None = None,
        rrf_k: int | None = None,
        graph_enabled: bool | None = None,
    ) -> None:
        self.db = db
        settings = get_settings()

        self.mode = mode or RetrievalMode(settings.retrieval_mode)
        self.rrf_k = rrf_k if rrf_k is not None else settings.retrieval_rrf_k
        self.graph_enabled = (
            graph_enabled if graph_enabled is not None else settings.retrieval_graph_enabled
        )

        self.dense = DenseRetriever(db, provider)
        self.lexical = LexicalRetriever(db)
        self.graph = GraphRetriever(db)

    def search(
        self,
        *,
        query: str,
        namespace: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        memory_types: list[MemoryType] | None = None,
        include_superseded: bool = False,
        limit: int = 50,
    ) -> HybridRetrievalResult:
        """Run hybrid retrieval and return fused candidates + traces.

        Each channel is run independently; failures are logged and
        do not prevent other channels from returning results.
        """
        t_start = datetime.now()

        # --- Dense retrieval ---
        dense_hits = []
        dense_trace = None
        try:
            dense_hits, dense_trace = self.dense.search(
                query=query,
                namespace=namespace,
                user_id=user_id,
                agent_id=agent_id,
                memory_types=memory_types,
                include_superseded=include_superseded,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Dense retrieval failed: %s", exc)
            from app.retrieval.models import RetrieverTrace, RetrievalSource

            dense_trace = RetrieverTrace(
                source=RetrievalSource.DENSE,
                candidate_count=0,
                error=str(exc),
            )

        # --- Lexical retrieval ---
        lexical_hits = []
        lexical_trace = None
        try:
            lexical_hits, lexical_trace = self.lexical.search(
                query=query,
                namespace=namespace,
                user_id=user_id,
                agent_id=agent_id,
                memory_types=memory_types,
                include_superseded=include_superseded,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Lexical retrieval failed: %s", exc)
            from app.retrieval.models import RetrieverTrace, RetrievalSource

            lexical_trace = RetrieverTrace(
                source=RetrievalSource.LEXICAL,
                candidate_count=0,
                error=str(exc),
            )

        # --- Graph retrieval (only in hybrid mode, seeded from dense/lexical) ---
        graph_hits = []
        graph_trace = None
        if self.graph_enabled and self.mode == RetrievalMode.HYBRID:
            # Use top dense + lexical hits as seeds
            seed_ids = []
            for h in dense_hits[:10]:
                seed_ids.append(h.memory_id)
            for h in lexical_hits[:10]:
                if h.memory_id not in seed_ids:
                    seed_ids.append(h.memory_id)

            if seed_ids:
                try:
                    graph_hits, graph_trace = self.graph.search(
                        seed_memory_ids=seed_ids[:20],
                        namespace=namespace,
                        include_superseded=include_superseded,
                        limit=limit,
                    )
                except Exception as exc:
                    logger.warning("Graph retrieval failed: %s", exc)
                    from app.retrieval.models import RetrieverTrace, RetrievalSource

                    graph_trace = RetrieverTrace(
                        source=RetrievalSource.GRAPH,
                        candidate_count=0,
                        error=str(exc),
                    )

        # Ensure all traces exist (even if empty)
        from app.retrieval.models import RetrieverTrace, RetrievalSource

        if dense_trace is None:
            dense_trace = RetrieverTrace(
                source=RetrievalSource.DENSE, candidate_count=0
            )
        if lexical_trace is None:
            lexical_trace = RetrieverTrace(
                source=RetrievalSource.LEXICAL, candidate_count=0
            )
        if graph_trace is None:
            graph_trace = RetrieverTrace(
                source=RetrievalSource.GRAPH, candidate_count=0
            )

        # --- RRF Fusion ---
        result = build_hybrid_result(
            dense_hits=dense_hits,
            lexical_hits=lexical_hits,
            graph_hits=graph_hits,
            dense_trace=dense_trace,
            lexical_trace=lexical_trace,
            graph_trace=graph_trace,
            k=self.rrf_k,
            mode=self.mode,
        )

        elapsed = (datetime.now() - t_start).total_seconds()
        logger.info(
            "Hybrid retrieval mode=%s namespace=%s dense=%d lexical=%d graph=%d fused=%d elapsed=%.3fs",
            self.mode.value,
            namespace,
            len(dense_hits),
            len(lexical_hits),
            len(graph_hits),
            result.total_unique_candidates,
            elapsed,
        )

        return result

    def reset_lexical_index(self) -> None:
        """Reset the lexical index (for testing)."""
        self.lexical.reset()
