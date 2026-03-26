"""Document retrieval endpoints — called by the orchestrator only."""

from fastapi import APIRouter, Depends

from app.middleware.service_auth import require_service_token
from app.models.common_models import StandardResponse
from app.repositories.mysql_document_repo import DocumentRepository
from app.utils.exceptions import NotFoundError

router = APIRouter(prefix="/documents", tags=["Documents"], dependencies=[Depends(require_service_token)])

_doc_repo = DocumentRepository()


@router.get("/{document_id}")
async def get_document(document_id: str):
    """Retrieve a document metadata record."""
    doc = await _doc_repo.get_document_by_id(document_id)
    if not doc:
        raise NotFoundError("Document")
    return StandardResponse(data=doc)


@router.get("/profile/{profile_id}")
async def get_documents_by_profile(profile_id: str):
    """Retrieve all documents belonging to a profile."""
    docs = await _doc_repo.get_documents_by_profile(profile_id)
    return StandardResponse(data=docs)
