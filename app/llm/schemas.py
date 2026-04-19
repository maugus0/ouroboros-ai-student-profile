"""Pydantic schemas for LLM output validation."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DegreeLevelEnum(str, Enum):
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"
    UNKNOWN = "unknown"


class TargetDegreeSourceEnum(str, Enum):
    USER_INPUT = "user_input"
    CV_EXPLICIT = "cv_explicit"
    TRAJECTORY_INFERENCE = "trajectory_inference"
    UNKNOWN = "unknown"


class EducationEntry(BaseModel):
    institution: str
    degree: str
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[float] = None
    gpa_scale: Optional[float] = None
    achievements: list[str] = Field(default_factory=list)
    evidence: Optional[str] = None


class WorkExperience(BaseModel):
    company: str
    position: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None
    skills_used: list[str] = Field(default_factory=list)
    evidence: Optional[str] = None


class ResearchExperience(BaseModel):
    title: str
    role: Optional[str] = None
    description: Optional[str] = None
    publication_venue: Optional[str] = None
    date: Optional[str] = None
    evidence: Optional[str] = None


class PublicationEntry(BaseModel):
    title: str
    venue: Optional[str] = None
    year: Optional[str] = None
    role: Optional[str] = None
    evidence: Optional[str] = None


class ExtractedProfile(BaseModel):
    """Complete extracted profile returned by the LLM."""

    # Personal
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    nationality: Optional[str] = None
    date_of_birth: Optional[str] = None

    # Target degree
    target_degree_needs_clarification: bool = False
    target_degree_reasoning: Optional[str] = None

    # Academic
    education: list[EducationEntry] = Field(default_factory=list)
    current_degree_level: Optional[DegreeLevelEnum] = Field(
        default=None, description="Highest /most recent degree being pursued or completed"
    )
    gpa_highest: Optional[float] = None
    gpa_scale: Optional[float] = None

    # Experience
    work_experience: list[WorkExperience] = Field(default_factory=list)
    research_experience: list[ResearchExperience] = Field(default_factory=list)

    # Skills
    technical_skills: list[str] = Field(default_factory=list)
    languages: list[dict[str, str]] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)

    # Research
    research_interests: Optional[list[str]] = Field(default=None, description="research areas and interests")
    publications: list[PublicationEntry] = Field(default_factory=list)
    target_degree_level: Optional[DegreeLevelEnum] = Field(default=DegreeLevelEnum.UNKNOWN)
    target_degree_confidence: Optional[float] = Field(ge=0.0, le=1.0, default=0.5)
    target_degree_source: Optional[TargetDegreeSourceEnum] = Field(default=TargetDegreeSourceEnum.UNKNOWN)

    # Metadata
    confidence_map: dict[str, float] = Field(default_factory=dict)
    evidence_map: dict[str, str] = Field(default_factory=dict)
    clarification_queue: list[dict[str, str]] = Field(default_factory=list)
    contradiction_flags: list[dict[str, str]] = Field(default_factory=list)
