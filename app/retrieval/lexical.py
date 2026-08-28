"""M11 — Lexical retriever with local BM25.

Implements lightweight BM25 retrieval over memory content without
requiring an external service or heavy dependency.

Design:
- BM25 index is built from DB memories at search time (per-query for small corpus)
- Optionally cached in-memory with invalidation on write/patch/delete
- Tokenization preserves technical identifiers (snake_case, CamelCase, paths)
- Namespace isolation enforced at query time
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.memory import Memory, MemoryStatus, MemoryType
from app.repositories.memory_repository import MemoryRepository
from app.retrieval.models import RetrievalHit, RetrievalSource, RetrieverTrace

logger = logging.getLogger("munin.retrieval.lexical")

# BM25 parameters
BM25_K1 = 1.5  # Term frequency saturation
BM25_B = 0.75  # Length normalization


def normalize_token(token: str) -> str:
    """Normalize a token for BM25 indexing.

    Preserves technical identifiers while lowering case:
    - snake_case: _load_max_checkpoint → _load_max_checkpoint (preserved)
    - CamelCase: AgentSessionService → agentsessionservice (lowered)
    - paths: app/context/assembler.py → app/context/assembler.py (preserved)
    - numbers: 503, M8.3A (preserved)
    - punctuation within identifiers preserved

    We lowercase but keep the token intact (no stemming, no stop words).
    """
    return token.lower()


def tokenize(text: str) -> list[str]:
    """Tokenize text for BM25 indexing.

    Strategy:
    1. Split on whitespace and punctuation boundaries
    2. Keep tokens with alphanumeric characters
    3. Normalize (lowercase)
    4. Preserve multi-word identifiers that contain underscores or slashes

    Critical: identifiers like _load_max_checkpoint, app/context/assembler.py
    must remain searchable as whole tokens.
    """
    if not text:
        return []

    tokens: list[str] = []

    # Split on whitespace first
    for word in text.split():
        # Try to split CamelCase into components but keep original too
        # e.g., "AgentSessionService" → ["AgentSessionService", "agent", "session", "service"]
        camel_parts = re.split(r'(?<=[a-z])(?=[A-Z])', word)
        if len(camel_parts) > 1:
            # Keep the original CamelCase token
            normalized = normalize_token(word)
            if normalized and len(normalized) >= 2:
                tokens.append(normalized)
            # Also add individual parts
            for part in camel_parts:
                part_norm = normalize_token(part)
                if part_norm and len(part_norm) >= 2:
                    tokens.append(part_norm)
        else:
            # Split punctuation but keep paths and dotted identifiers
            # e.g., "app/context/assembler.py" stays as one token
            # e.g., "M8.3A" stays as one token
            # e.g., "memory_id=" splits into "memory_id" and "="
            sub_tokens = re.split(r'([=/\\(),;:\[\]{}<>!@#$%^&*+|~`"\'?])', word)
            for st in sub_tokens:
                st = st.strip()
                if not st:
                    continue
                # Skip pure punctuation
                if re.match(r'^[^a-zA-Z0-9]+$', st):
                    continue
                normalized = normalize_token(st)
                if normalized and len(normalized) >= 1:
                    tokens.append(normalized)

    return tokens


class BM25Index:
    """Lightweight in-memory BM25 index.

    Built from a collection of (id, text) pairs.
    Supports add/remove/update for incremental maintenance.
    """

    def __init__(self) -> None:
        self._documents: dict[str, list[str]] = {}  # doc_id → tokens
        self._doc_lengths: dict[str, int] = {}  # doc_id → token count
        self._doc_count: int = 0
        self._avg_doc_length: float = 0.0
        self._term_freq: dict[str, dict[str, int]] = {}  # term → {doc_id: count}
        self._doc_freq: dict[str, int] = {}  # term → number of docs containing it

    @property
    def size(self) -> int:
        return self._doc_count

    def add(self, doc_id: str, text: str) -> None:
        """Add or update a document in the index."""
        tokens = tokenize(text)
        self._documents[doc_id] = tokens
        self._doc_lengths[doc_id] = len(tokens)

        # Update term frequencies
        term_counts = Counter(tokens)
        for term, count in term_counts.items():
            if term not in self._term_freq:
                self._term_freq[term] = {}
            self._term_freq[term][doc_id] = count

        self._rebuild_stats()

    def remove(self, doc_id: str) -> None:
        """Remove a document from the index."""
        if doc_id not in self._documents:
            return

        # Remove term frequencies for this document
        tokens = self._documents[doc_id]
        for term in set(tokens):
            if term in self._term_freq and doc_id in self._term_freq[term]:
                del self._term_freq[term][doc_id]
                if not self._term_freq[term]:
                    del self._term_freq[term]

        del self._documents[doc_id]
        del self._doc_lengths[doc_id]
        self._rebuild_stats()

    def _rebuild_stats(self) -> None:
        """Rebuild document count and average length."""
        self._doc_count = len(self._documents)
        if self._doc_count > 0:
            self._avg_doc_length = sum(self._doc_lengths.values()) / self._doc_count
        else:
            self._avg_doc_length = 0.0

        # Rebuild document frequency
        self._doc_freq = {}
        for term, doc_map in self._term_freq.items():
            self._doc_freq[term] = len(doc_map)

    def search(self, query: str, limit: int = 50) -> list[tuple[str, float]]:
        """Search the index and return (doc_id, score) pairs sorted by score desc.

        Uses BM25 scoring: score(q, d) = Σ IDF(qi) * (tf(qi,d) * (k1+1)) / (tf(qi,d) + k1 * (1 - b + b * |d| / avgdl))
        """
        if not self._documents or not query:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores: dict[str, float] = {}

        for term in query_tokens:
            if term not in self._term_freq:
                continue

            # IDF: log((N - n + 0.5) / (n + 0.5) + 1)
            n = self._doc_freq.get(term, 0)
            idf = math.log((self._doc_count - n + 0.5) / (n + 0.5) + 1)

            for doc_id, tf in self._term_freq[term].items():
                # BM25 term score
                doc_len = self._doc_lengths[doc_id]
                numerator = tf * (BM25_K1 + 1)
                denominator = tf + BM25_K1 * (
                    1 - BM25_B + BM25_B * doc_len / max(self._avg_doc_length, 1)
                )
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * numerator / denominator

        # Sort by score descending
        sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:limit]


class LexicalRetriever:
    """Lexical (BM25) retrieval channel.

    Builds a lightweight BM25 index from DB memories and searches it.
    Supports incremental updates for create/patch/delete lifecycle.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._memory_repo = MemoryRepository(db)
        self._index = BM25Index()
        self._built = False

    def _ensure_index(
        self,
        namespace: str,
        user_id: str | None = None,
        memory_types: list[MemoryType] | None = None,
        include_superseded: bool = False,
    ) -> None:
        """Build the BM25 index if not already built for this namespace.

        For small-to-medium Munin corpus sizes, rebuilding per-query is
        acceptable and avoids stale index issues. For larger corpora,
        consider caching with explicit invalidation.
        """
        if self._built:
            return

        # Fetch active memories
        memories_active = self._memory_repo.list(
            namespace=namespace,
            user_id=user_id,
            status=MemoryStatus.active,
            limit=10000,
        )

        memories = list(memories_active)

        # Optionally include superseded
        if include_superseded:
            memories_superseded = self._memory_repo.list(
                namespace=namespace,
                user_id=user_id,
                status=MemoryStatus.superseded,
                limit=10000,
            )
            seen_ids = {m.id for m in memories}
            for m in memories_superseded:
                if m.id not in seen_ids:
                    memories.append(m)

        # Filter by memory types if specified
        if memory_types:
            type_set = set(memory_types)
            memories = [m for m in memories if m.memory_type in type_set]

        for memory in memories:
            # Index content + gist + summary (weighted by inclusion)
            text_parts = [memory.content]
            if memory.gist:
                text_parts.append(memory.gist)
            if memory.summary:
                text_parts.append(memory.summary)
            combined_text = " ".join(text_parts)
            self._index.add(memory.id, combined_text)

        self._built = True
        logger.debug(
            "Built BM25 index: namespace=%s documents=%d",
            namespace,
            self._index.size,
        )

    def on_memory_created(self, memory: Memory) -> None:
        """Incrementally update index when a memory is created."""
        text_parts = [memory.content]
        if memory.gist:
            text_parts.append(memory.gist)
        if memory.summary:
            text_parts.append(memory.summary)
        self._index.add(memory.id, " ".join(text_parts))

    def on_memory_updated(self, memory: Memory) -> None:
        """Incrementally update index when a memory is patched."""
        self._index.remove(memory.id)
        text_parts = [memory.content]
        if memory.gist:
            text_parts.append(memory.gist)
        if memory.summary:
            text_parts.append(memory.summary)
        self._index.add(memory.id, " ".join(text_parts))

    def on_memory_deleted(self, memory_id: str) -> None:
        """Remove a memory from the index."""
        self._index.remove(memory_id)

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
    ) -> tuple[list[RetrievalHit], RetrieverTrace]:
        """Run lexical retrieval and return hits + trace."""
        t_start = datetime.now()

        self._ensure_index(
            namespace=namespace,
            user_id=user_id,
            memory_types=memory_types,
            include_superseded=include_superseded,
        )

        results = self._index.search(query, limit=limit)

        # Normalize scores to 0-1 range (BM25 scores are unbounded)
        max_score = results[0][1] if results else 1.0
        if max_score <= 0:
            max_score = 1.0

        hits: list[RetrievalHit] = []
        for rank, (memory_id, score) in enumerate(results, start=1):
            normalized_score = min(1.0, score / max_score)
            hits.append(
                RetrievalHit(
                    memory_id=memory_id,
                    source=RetrievalSource.LEXICAL,
                    source_rank=rank,
                    source_score=round(normalized_score, 6),
                )
            )

        elapsed = (datetime.now() - t_start).total_seconds()
        trace = RetrieverTrace(
            source=RetrievalSource.LEXICAL,
            candidate_count=self._index.size,
            hits=hits,
            elapsed_seconds=round(elapsed, 4),
        )

        logger.info(
            "Lexical retrieval namespace=%s index_size=%d hits=%d elapsed=%.3fs",
            namespace,
            self._index.size,
            len(hits),
            elapsed,
        )

        return hits, trace

    def reset(self) -> None:
        """Reset the index (for testing or full rebuild)."""
        self._index = BM25Index()
        self._built = False
