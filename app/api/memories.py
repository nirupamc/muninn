"""Memory HTTP endpoints."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.models.memory import MemoryStatus, MemoryType
from app.schemas.memory import (
    MemoryCreate,
    MemoryRead,
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryUpdate,
)
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/memories", tags=["memories"])


def _to_read(memory) -> MemoryRead:
    return MemoryRead.model_validate(memory)


def get_memory_service(
    db: Session = Depends(get_db),
    provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> MemoryService:
    return MemoryService(db, embedding_provider=provider)


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def create_memory(
    payload: MemoryCreate,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryRead:
    memory = service.create(payload)
    return _to_read(memory)


@router.post("/search", response_model=MemorySearchResponse)
def search_memories(
    payload: MemorySearchRequest,
    service: MemoryService = Depends(get_memory_service),
) -> MemorySearchResponse:
    return service.search(payload)


@router.get("", response_model=list[MemoryRead])
def list_memories(
    namespace: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    memory_type: MemoryType | None = None,
    status: MemoryStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: MemoryService = Depends(get_memory_service),
) -> list[MemoryRead]:
    memories = service.list(
        namespace=namespace,
        user_id=user_id,
        agent_id=agent_id,
        memory_type=memory_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [_to_read(memory) for memory in memories]


@router.get("/{memory_id}", response_model=MemoryRead)
def get_memory(
    memory_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryRead:
    memory = service.get(memory_id)
    return _to_read(memory)


@router.patch("/{memory_id}", response_model=MemoryRead)
def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryRead:
    memory = service.update(memory_id, payload)
    return _to_read(memory)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    memory_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> Response:
    service.delete(memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
