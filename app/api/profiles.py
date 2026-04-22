"""Profile API endpoints — called by the orchestrator only."""

import base64

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.config import settings
from app.middleware.service_auth import get_optional_request_user_id, get_request_user_id, require_service_token
from app.models.common_models import StandardResponse
from app.models.profile_models import (
    ClarificationSubmitRequest,
    CollectFromChatRequest,
    ParseRequest,
    ProfileUpdate,
    SyncUserProfileRequest,
)
from app.services.gap_analysis_service import GapAnalysisService
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/api/v1/profiles", tags=["Profiles"], dependencies=[Depends(require_service_token)])


_profile_service = ProfileService()
_gap_service = GapAnalysisService()


def get_profile_service() -> ProfileService:
    return _profile_service


def get_gap_service() -> GapAnalysisService:
    return _gap_service


@router.post("/parse")
async def parse_document(
    body: ParseRequest,
    request_user_id: str | None = Depends(get_optional_request_user_id),
    profile_service: ProfileService = Depends(get_profile_service),
):
    """Accept a document from the orchestrator, parse it, and create a profile."""
    resolved_user_id = body.user_id or request_user_id
    if not resolved_user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="user_id is required")

    result = await profile_service.parse_and_create_profile(
        user_id=resolved_user_id,
        file_name=body.file_name,
        file_content_base64=body.file_content_base64,
        intent=body.intent,
        document_type=body.document_type,
        run_gap_analysis=body.run_gap_analysis,
    )
    return StandardResponse(message="Profile created", data=result)


@router.post("/sync-user")
async def sync_user_profile(
    body: SyncUserProfileRequest,
    request_user_id: str | None = Depends(get_optional_request_user_id),
    profile_service: ProfileService = Depends(get_profile_service),
):
    """Seed or update student profile with basic user data from orchestrator."""
    resolved_user_id = body.user_id or request_user_id
    if not resolved_user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="user_id is required")

    payload = body.model_dump(exclude_none=True)
    payload.pop("user_id", None)
    result = await profile_service.sync_user_profile(resolved_user_id, payload)
    return StandardResponse(message="Profile sync completed", data=result)


@router.post("/collect-from-chat")
async def collect_from_chat(
    body: CollectFromChatRequest,
    request_user_id: str | None = Depends(get_optional_request_user_id),
    profile_service: ProfileService = Depends(get_profile_service),
):
    """Persist profile fields extracted from chat and return updated readiness."""
    resolved_user_id = body.user_id or request_user_id
    if not resolved_user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="user_id is required")

    result = await profile_service.collect_from_chat(
        user_id=resolved_user_id,
        fields=body.fields,
        extractions=body.extractions,
        extraction_telemetry=body.extraction_telemetry,
        pending_clarification_fields=body.pending_clarification_fields,
        correction_fields=body.correction_fields,
        chat_id=body.chat_id,
        message_id=body.message_id,
    )
    return StandardResponse(message="Profile fields collected from chat", data=result)


@router.post("/parse-upload")
async def parse_document_upload(
    user_id: str | None = Form(default=None),
    intent: str = Form(default="profile_completion"),
    document_type: str = Form(default="cv"),
    run_gap_analysis: bool = Form(default=False),
    file: UploadFile = File(...),
    request_user_id: str | None = Depends(get_optional_request_user_id),
    profile_service: ProfileService = Depends(get_profile_service),
):
    """Accept streamed multipart upload and create a profile.

    This endpoint is equivalent to /api/v1/profiles/parse but avoids base64 payloads
    on the client side by accepting a multipart file upload.
    """
    allowed_document_types = {"cv", "transcript", "unknown"}
    if document_type not in allowed_document_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"document_type must be one of: {', '.join(sorted(allowed_document_types))}",
        )

    raw_bytes = await _read_upload_bytes(file)
    file_content_base64 = base64.b64encode(raw_bytes).decode("utf-8")

    resolved_user_id = user_id or request_user_id
    if not resolved_user_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="user_id is required")

    result = await profile_service.parse_and_create_profile(
        user_id=resolved_user_id,
        file_name=file.filename or "uploaded_file",
        file_content_base64=file_content_base64,
        intent=intent,
        document_type=document_type,
        run_gap_analysis=run_gap_analysis,
    )
    return StandardResponse(message="Profile created", data=result)


@router.get("/status")
async def get_profile_status(
    user_id: str = Depends(get_request_user_id),
    intent: str | None = Query(default=None),
    profile_service: ProfileService = Depends(get_profile_service),
):
    """Return readiness details for the request user."""
    result = await profile_service.get_profile_status(user_id, intent=intent)
    return StandardResponse(data=result)


@router.get("/{profile_id}")
async def get_profile(profile_id: str, profile_service: ProfileService = Depends(get_profile_service)):
    """Retrieve a single student profile."""
    profile = await profile_service.get_profile(profile_id)
    return StandardResponse(data=profile)


@router.get("")
async def list_profiles(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    profile_service: ProfileService = Depends(get_profile_service),
):
    """List profiles with pagination."""
    result = await profile_service.list_profiles(page=page, page_size=page_size)
    return StandardResponse(data=result)


@router.patch("/{profile_id}")
async def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    profile_service: ProfileService = Depends(get_profile_service),
):
    """Update specific fields on a profile."""
    updates = body.model_dump(exclude_unset=True)
    profile = await profile_service.update_profile(profile_id, updates)
    return StandardResponse(message="Profile updated", data=profile)


@router.put("/{profile_id}")
async def replace_profile(
    profile_id: str,
    body: ProfileUpdate,
    profile_service: ProfileService = Depends(get_profile_service),
):
    """Update profile fields (idempotent full-update style endpoint)."""
    updates = body.model_dump(exclude_unset=True)
    profile = await profile_service.update_profile(profile_id, updates)
    return StandardResponse(message="Profile updated", data=profile)


@router.get("/{profile_id}/skills")
async def get_profile_skills(profile_id: str, profile_service: ProfileService = Depends(get_profile_service)):
    """Retrieve normalized skills extracted for a profile."""
    result = await profile_service.get_profile_skills(profile_id)
    return StandardResponse(data=result)


@router.get("/{profile_id}/gaps")
async def get_profile_gaps(profile_id: str, gap_service: GapAnalysisService = Depends(get_gap_service)):
    """Retrieve the latest stored gap-analysis snapshot for a profile."""
    result = await gap_service.get_latest_analysis(profile_id)
    return StandardResponse(data=result)


@router.post("/{profile_id}/gap-analysis")
async def trigger_gap_analysis(profile_id: str, gap_service: GapAnalysisService = Depends(get_gap_service)):
    """Trigger a gap analysis on an existing profile."""
    result = await gap_service.analyze(profile_id)
    return StandardResponse(data=result)


@router.get("/{profile_id}/clarifications")
async def get_profile_clarifications(
    profile_id: str,
    profile_service: ProfileService = Depends(get_profile_service),
):
    """Return unresolved clarifications and readiness state for a profile."""
    result = await profile_service.get_clarifications(profile_id)
    return StandardResponse(data=result)


@router.post("/{profile_id}/clarifications")
async def submit_profile_clarifications(
    profile_id: str,
    body: ClarificationSubmitRequest,
    profile_service: ProfileService = Depends(get_profile_service),
):
    """Apply clarification answers and update profile readiness state."""
    answers = [item.model_dump() for item in body.answers]
    result = await profile_service.submit_clarifications(profile_id, answers)
    return StandardResponse(message="Clarifications submitted", data=result)


@router.post("/{profile_id}/gap-analysis/jobs")
async def create_gap_analysis_job(
    profile_id: str,
    background_tasks: BackgroundTasks,
    gap_service: GapAnalysisService = Depends(get_gap_service),
):
    """Create async gap-analysis job; queued jobs are processed in background."""
    job = await gap_service.create_gap_job(profile_id)
    if job["status"] == "queued":
        background_tasks.add_task(gap_service.process_gap_job, job["job_id"], profile_id)
    return StandardResponse(message="Gap analysis job created", data=job)


@router.get("/gap-analysis/jobs/{job_id}")
async def get_gap_analysis_job(job_id: str, gap_service: GapAnalysisService = Depends(get_gap_service)):
    """Get async gap-analysis job status and result snapshot."""
    job = await gap_service.get_gap_job(job_id)
    return StandardResponse(data=job)


async def _read_upload_bytes(upload_file: UploadFile) -> bytes:
    """Read an uploaded file in chunks and enforce size limits."""
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    chunk_size = 1024 * 1024
    total_size = 0
    buffer = bytearray()

    while True:
        chunk = await upload_file.read(chunk_size)
        if not chunk:
            break

        total_size += len(chunk)
        if total_size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Max allowed is {settings.MAX_FILE_SIZE_MB} MB",
            )

        buffer.extend(chunk)

    await upload_file.close()
    return bytes(buffer)
