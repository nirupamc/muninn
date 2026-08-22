"""Synchronous Munin client (M7A).

External agents should only need this thin client. It exposes:

- ``health()``          — connectivity check
- ``get_context()``     — assemble LLM-ready durable context
- ``remember()``        — persist one interaction through the full pipeline
- ``search_memories()`` — optional semantic search
- ``get_memory()``      — optional inspect a single memory
- ``consolidate()``     — optional advanced consolidation

The client never talks to the database directly; it talks to the Munin HTTP
API. The backend owns all storage and pipeline logic.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from app.sdk.models import (
    AgentContext,
    AgentHealth,
    MuninMemory,
    RememberResult,
)
from app.sdk.transport import HttpTransport


class MuninClient:
    """Synchronous client for the Munin high-level API."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000",
        namespace: str = "default",
        user_id: str | None = None,
        agent_id: str | None = None,
        api_key: str | None = None,
        timeout: tuple[float, float] = (5.0, 30.0),
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.namespace = namespace
        self.user_id = user_id
        self.agent_id = agent_id
        self._transport = HttpTransport(
            base_url=self.base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )

    def health(self) -> AgentHealth:
        data = self._transport.request("GET", "/health").json()
        return AgentHealth(status=data.get("status", ""), service=data.get("service"))

    def get_context(
        self,
        query: str,
        *,
        namespace: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        token_budget: int = 1500,
        max_memories: int = 20,
    ) -> AgentContext:
        """Assemble durable memory context relevant to ``query``."""
        payload: dict[str, Any] = {
            "query": query,
            "namespace": namespace or self.namespace,
            "token_budget": token_budget,
            "max_memories": max_memories,
        }
        if user_id is not None:
            payload["user_id"] = user_id
        elif self.user_id is not None:
            payload["user_id"] = self.user_id
        if agent_id is not None:
            payload["agent_id"] = agent_id
        elif self.agent_id is not None:
            payload["agent_id"] = self.agent_id
        if session_id is not None:
            payload["session_id"] = session_id

        resp = self._transport.request(
            "POST", "/api/v1/agent/context", json_body=payload
        )
        return self._context_from_json(resp.json())

    def bootstrap(self, query: str, **kwargs: Any) -> AgentContext:
        """Alias for ``get_context`` when bootstrapping an agent task."""
        return self.get_context(query, **kwargs)

    def _context_from_json(self, data: dict[str, Any]) -> AgentContext:
        memories_used = [
            MuninMemory(
                memory_id=m["memory_id"],
                memory_type=m["memory_type"],
                content=m["content"],
                score=m.get("final_score"),
            )
            for m in data.get("memories_used", [])
        ]
        return AgentContext(
            query=data.get("query", ""),
            namespace=data.get("namespace", self.namespace),
            text=data.get("text", ""),
            estimated_tokens=int(data.get("estimated_tokens", 0)),
            truncated=bool(data.get("truncated", False)),
            memories_used=memories_used,
            as_of=data.get("as_of"),
        )

    def remember(
        self,
        content: str,
        *,
        role: str = "assistant",
        namespace: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> RememberResult:
        """Persist a single interaction through the full pipeline."""
        payload: dict[str, Any] = {
            "namespace": namespace or self.namespace,
            "role": role,
            "content": content,
        }
        if session_id is not None:
            payload["session_id"] = session_id
        if user_id is not None:
            payload["user_id"] = user_id
        elif self.user_id is not None:
            payload["user_id"] = self.user_id
        if agent_id is not None:
            payload["agent_id"] = agent_id
        elif self.agent_id is not None:
            payload["agent_id"] = self.agent_id
        if idempotency_key is not None:
            payload["idempotency_key"] = idempotency_key

        resp = self._transport.request(
            "POST", "/api/v1/agent/remember", json_body=payload
        )
        data = resp.json()
        return RememberResult(
            event_id=data["event_id"],
            remembered=bool(data["remembered"]),
            decision=data["decision"],
            memory_id=data.get("memory_id"),
            dedup_relationship=data.get("dedup_relationship"),
            temporal_relationship=data.get("temporal_relationship"),
            idempotent_replay=bool(data.get("idempotent_replay", False)),
        )

    def search_memories(
        self,
        query: str,
        *,
        namespace: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[MuninMemory]:
        """Semantic memory search (read-only)."""
        payload: dict[str, Any] = {
            "query": query,
            "namespace": namespace or self.namespace,
            "limit": limit,
            "min_score": min_score,
        }
        if user_id is not None:
            payload["user_id"] = user_id
        elif self.user_id is not None:
            payload["user_id"] = self.user_id
        if agent_id is not None:
            payload["agent_id"] = agent_id
        elif self.agent_id is not None:
            payload["agent_id"] = self.agent_id

        resp = self._transport.request(
            "POST", "/api/v1/memories/search", json_body=payload
        )
        data = resp.json()
        return [
            MuninMemory(
                memory_id=item["memory"]["id"],
                memory_type=item["memory"]["memory_type"],
                content=item["memory"]["content"],
                score=float(item["score"]),
            )
            for item in data.get("results", [])
        ]

    def get_memory(self, memory_id: str) -> dict[str, Any]:
        """Fetch a single memory by id."""
        resp = self._transport.request("GET", f"/api/v1/memories/{memory_id}")
        return resp.json()

    def consolidate(
        self,
        memory_ids: list[str],
        *,
        namespace: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Consolidate a group of memories (advanced)."""
        payload: dict[str, Any] = {
            "namespace": namespace or self.namespace,
            "memory_ids": memory_ids,
        }
        if user_id is not None:
            payload["user_id"] = user_id
        elif self.user_id is not None:
            payload["user_id"] = self.user_id

        resp = self._transport.request(
            "POST", "/api/v1/memories/consolidate", json_body=payload
        )
        return resp.json()

    @contextmanager
    def session(self, session_id: str):
        """Return a scoped session with context/remember convenience."""
        yield AgentSession(
            client=self,
            session_id=session_id,
            namespace=self.namespace,
            agent_id=self.agent_id,
        )

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "MuninClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class AgentSession:
    """A named working session bound to one project scope."""

    def __init__(
        self,
        *,
        client: MuninClient,
        session_id: str,
        namespace: str,
        agent_id: str | None,
    ) -> None:
        self.client = client
        self.session_id = session_id
        self.namespace = namespace
        self.agent_id = agent_id

    def context(self, query: str, **kwargs: Any) -> AgentContext:
        return self.client.get_context(
            query,
            namespace=self.namespace,
            agent_id=self.agent_id,
            session_id=self.session_id,
            **kwargs,
        )

    def remember(self, content: str, **kwargs: Any) -> RememberResult:
        kwargs.pop("session_id", None)
        return self.client.remember(
            content,
            namespace=self.namespace,
            agent_id=self.agent_id,
            session_id=self.session_id,
            **kwargs,
        )