from pydantic import BaseModel
from typing import Any


class JobCreateRequest(BaseModel):
    title: str
    raw_description: str


class JobResponse(BaseModel):
    id: int
    title: str
    raw_description: str
    rubric: list[dict[str, Any]]

    class Config:
        from_attributes = True
        
class RubricUpdateRequest(BaseModel):
    rubric: list[dict[str, Any]]
    
class RankingEntry(BaseModel):
    resume_id: int
    filename: str
    total_score: float
    criteria_breakdown: list[dict[str, Any]]
    summary: str


class RankingsResponse(BaseModel):
    job_id: int
    job_title: str
    rankings: list[RankingEntry]
    
class ResumeUploadResult(BaseModel):
    filename: str
    status: str
    resume_id: int | None = None
    total_score: float | None = None
    error: str | None = None


class BulkUploadResponse(BaseModel):
    job_id: int
    results: list[ResumeUploadResult]
    
class ResumeDetailResponse(BaseModel):
    id: int
    job_id: int
    filename: str
    parsed_data: dict[str, Any]
    total_score: float | None = None
    criteria_breakdown: list[dict[str, Any]] | None = None
    summary: str | None = None
class ResumeSkills(BaseModel, strict=True):
    technical_skills: list[str]
    soft_skills: list[str]


class ResumeEducation(BaseModel, strict=True):
    degree: str | None
    institution: str | None
    years: str | None


class ResumeRole(BaseModel, strict=True):
    title: str | None
    company: str | None
    duration: str | None


class ResumeProject(BaseModel, strict=True):
    name: str | None
    summary: str | None
    tech_used: list[str]


class StructuredResume(BaseModel, strict=True, allow_inf_nan=False):
    name: str | None
    email: str | None
    phone: str | None
    skills: ResumeSkills
    years_of_experience: int | float | None
    education: list[ResumeEducation]
    roles: list[ResumeRole]
    projects: list[ResumeProject]
