"""Admission debug/inspection endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.admission.base import AdmissionProvider
from app.admission.factory import get_admission_provider
from app.admission.service import AdmissionService
from app.database import get_db
from app.deduplication.base import RelationshipProvider
from app.deduplication.factory import get_relationship_provider
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.schemas.admission import AnalyzeAdmissionRequest, AnalyzeAdmissionResponse

router = APIRouter(prefix="/admission", tags=["admission"])


def get_admission_service(
    db: Session = Depends(get_db),
    admission_provider: AdmissionProvider = Depends(get_admission_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
    relationship_provider: RelationshipProvider = Depends(get_relationship_provider),
) -> AdmissionService:
    return AdmissionService(
        db,
        admission_provider=admission_provider,
        embedding_provider=embedding_provider,
        relationship_provider=relationship_provider,
    )


@router.post("/analyze", response_model=AnalyzeAdmissionResponse)
def analyze_admission(
    payload: AnalyzeAdmissionRequest,
    service: AdmissionService = Depends(get_admission_service),
) -> AnalyzeAdmissionResponse:
    """Inspect admission decisions without creating memories or audits."""
    return service.analyze_only(payload)
