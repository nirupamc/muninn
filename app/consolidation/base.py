"""Abstract consolidation provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.consolidation.models import ConsolidationProposal
from app.models.memory import Memory


class ConsolidationProvider(ABC):
    """Produce a consolidated summary from a group of related memories."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def consolidate(
        self,
        memories: list[Memory],
        *,
        namespace: str,
    ) -> ConsolidationProposal | None:
        """
        Return a ConsolidationProposal or None if consolidation is unsafe.

        Rules for ALL implementations:
        - Only summarise facts present in the supplied memories.
        - Do not add inferred facts.
        - If memories contain unresolved contradictions, return None.
        - Preserve negation, uncertainty, and entity names.
        - source_memory_ids must be the IDs of the supplied memories (caller validates).
        """
