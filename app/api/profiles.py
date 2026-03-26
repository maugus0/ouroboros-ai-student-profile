"""Profile API endpoints — called by the orchestrator only."""

from fastapi import APIRouter, Depends, Query

from app.middleware.service_auth import require_service_token
from app.models.common_models import StandardResponse
from app.models.profile_models import ParseRequest, ProfileUpdate
from app.services.gap_analysis_service import GapAnalysisService
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/profiles", tags=["Profiles"], dependencies=[Depends(require_service_token)])

_profile_service = ProfileService()
_gap_service = GapAnalysisService()


@router.post("/parse")
async def parse_document(body: ParseRequest):
    """Accept a document from the orchestrator, parse it, and create a profile."""
    result = await _profile_service.parse_and_create_profile(
        user_id=body.user_id,
        file_name=body.file_name,
        file_content_base64=body.file_content_base64,
        document_type=body.document_type,
        target_degree_hint=body.target_degree_hint,
    )
    return StandardResponse(message="Profile created", data=result)


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    """Retrieve a single student profile."""
    profile = await _profile_service.get_profile(profile_id)
    return StandardResponse(data=profile)


@router.get("")
async def list_profiles(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    """List profiles with pagination."""
    result = await _profile_service.list_profiles(page=page, page_size=page_size)
    return StandardResponse(data=result)


@router.patch("/{profile_id}")
async def update_profile(profile_id: str, body: ProfileUpdate):
    """Update specific fields on a profile."""
    updates = body.model_dump(exclude_unset=True)
    profile = await _profile_service.update_profile(profile_id, updates)
    return StandardResponse(message="Profile updated", data=profile)


@router.post("/{profile_id}/gap-analysis")
async def run_gap_analysis(profile_id: str):
    """Trigger a gap analysis on an existing profile."""
    result = await _gap_service.analyze(profile_id)
    return StandardResponse(data=result)
