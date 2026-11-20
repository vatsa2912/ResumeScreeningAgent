from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi import Request
from fastapi.responses import JSONResponse
from secrets import compare_digest

from config import API_TOKEN, LLM_PROVIDER, validate_settings
from llm_provider import LLMError
from logger_config import get_logger

from database import init_db, get_session
from rubric_builder import build_rubric
import json
from crud import (
    create_job, update_job_rubric, get_rankings_for_job, get_job, get_resume_by_id,
    get_score_for_resume, screening_digest, find_checkpoint, find_unfinished_legacy_resume,
    save_checkpoint, save_score_once,
)
from models import ScreeningReceipt
from schemas import JobCreateRequest, JobResponse, RubricUpdateRequest, RankingsResponse, ResumeUploadResult, BulkUploadResponse, ResumeDetailResponse
from typing import List
from resume_parser import extract_text_from_pdf
from resume_structurer import structure_resume
from scoring_agent import score_resume



app = FastAPI(title="Resume Screening Agent API")
logger = get_logger(__name__)
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_BATCH_BYTES = 16 * 1024 * 1024
MAX_CLOUD_FILES = 3


@app.middleware("http")
async def protect_api(request: Request, call_next):
    path = request.url.path.rstrip("/")
    protected = path.startswith(("/jobs", "/resumes"))
    if API_TOKEN and protected:
        expected = f"Bearer {API_TOKEN}".encode()
        provided = request.headers.get("authorization", "").encode()
        if not compare_digest(provided, expected):
            return JSONResponse({"detail": "Screening service access denied."}, status_code=401)

    if request.method == "POST" and path.startswith("/jobs/") and path.endswith("/resumes"):
        length = request.headers.get("content-length", "")
        if not length.isascii() or not length.isdecimal() or len(length) > 20 or "transfer-encoding" in request.headers:
            return JSONResponse({"detail": "Uploads require a valid Content-Length."}, status_code=411)
        if int(length) > MAX_BATCH_BYTES:
            return JSONResponse({"detail": "Upload exceeds the 16 MiB request limit."}, status_code=413)

    response = await call_next(request)
    if protected:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(LLMError)
async def handle_llm_error(request: Request, exc: LLMError):
    headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds is not None else {}
    return JSONResponse({"detail": str(exc), "error_code": exc.error_code,
                         "retry_after_seconds": exc.retry_after_seconds}, status_code=exc.status_code, headers=headers)


@app.exception_handler(SQLAlchemyError)
async def handle_database_error(request: Request, exc: SQLAlchemyError):
    logger.warning("Database operation failed (%s)", type(exc).__name__)
    return JSONResponse({"detail": "The screening database is temporarily unavailable."}, status_code=503)


@app.on_event("startup")
def on_startup():
    validate_settings()
    try:
        init_db()
    except SQLAlchemyError:
        raise RuntimeError("Database initialization failed. Check the database settings.") from None


@app.get("/health")
def health():
    return {"status": "ok"}


def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@app.post("/jobs", response_model=JobResponse)
def create_job_endpoint(request: JobCreateRequest, db: Session = Depends(get_db)):
    if LLM_PROVIDER == "groq" and len(request.raw_description) > 12_000:
        raise HTTPException(status_code=413, detail="Cloud job descriptions are limited to 12,000 characters.")
    rubric = build_rubric(request.raw_description)
    job = create_job(
        db,
        title=request.title,
        raw_description=request.raw_description,
        rubric=rubric
    )

    return job_response(job)


def job_response(job):
    return JobResponse(id=job.id, title=job.title, raw_description=job.raw_description,
                       rubric=json.loads(job.rubric_json))


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job_endpoint(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job_response(job)


@app.put("/jobs/{job_id}/rubric", response_model=JobResponse)
def update_rubric_endpoint(job_id: int, request: RubricUpdateRequest, db: Session = Depends(get_db)):
    try:
        job = update_job_rubric(db, job_id, request.rubric)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rubric. Check criterion fields and weights.")

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job with id {job_id} not found")

    return job_response(job)

@app.get("/jobs/{job_id}/rankings", response_model=RankingsResponse)
def get_rankings_endpoint(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job with id {job_id} not found")

    rankings = get_rankings_for_job(db, job_id)

    return RankingsResponse(
        job_id=job.id,
        job_title=job.title,
        rankings=rankings
    )

@app.get("/resumes/{resume_id}", response_model=ResumeDetailResponse)
def get_resume_endpoint(resume_id: int, db: Session = Depends(get_db)):
    resume = get_resume_by_id(db, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail=f"Resume with id {resume_id} not found")

    score = get_score_for_resume(db, resume_id)

    return ResumeDetailResponse(
        id=resume.id,
        job_id=resume.job_id,
        filename=resume.filename,
        parsed_data=json.loads(resume.parsed_json),
        total_score=score.total_score if score else None,
        criteria_breakdown=json.loads(score.criteria_breakdown_json) if score else None,
        summary=score.justification_text if score else None
    )
    

def model_failure(filename, stage, error, resume_id=None):
    return ResumeUploadResult(
        filename=filename, status="failed", resume_id=resume_id, error=f"{stage} failed: {error}",
        error_code=error.error_code, retry_after_seconds=error.retry_after_seconds,
    )


def score_checkpoint(db, resume_id, rubric):
    resume = get_resume_by_id(db, resume_id)
    filename, job_id = resume.filename, resume.job_id
    saved = get_score_for_resume(db, resume_id)
    if saved is None:
        parsed = json.loads(resume.parsed_json)
        db.rollback()
        try:
            result = score_resume(parsed, rubric)
        except LLMError as exc:
            return model_failure(filename, "Scoring", exc, resume_id)
        total = save_score_once(db, resume_id, job_id, result)
    else:
        total = saved.total_score
        db.rollback()
    return ResumeUploadResult(filename=filename, status="success", resume_id=resume_id, total_score=total)


@app.post("/jobs/{job_id}/resumes/{resume_id}/retry", response_model=ResumeUploadResult)
def retry_scoring_endpoint(job_id: int, resume_id: int, db: Session = Depends(get_db)):
    resume = get_resume_by_id(db, resume_id)
    if resume is None or resume.job_id != job_id:
        raise HTTPException(status_code=404, detail="Resume not found for this job.")
    rubric = json.loads(resume.job.rubric_json)
    digest = screening_digest(job_id, resume.filename, resume.raw_text, rubric)
    receipt = db.query(ScreeningReceipt).filter_by(resume_id=resume_id).first()
    if receipt and receipt.input_digest != digest:
        return ResumeUploadResult(filename=resume.filename, status="failed", resume_id=resume_id,
                                  error_code="rubric_changed",
                                  error="The criteria changed. Reopen the job to screen with its current criteria.")
    if receipt is None and get_score_for_resume(db, resume_id) is None:
        resume_id = save_checkpoint(db, digest, job_id, resume.filename, resume.raw_text,
                                    json.loads(resume.parsed_json), resume_id)
    return score_checkpoint(db, resume_id, rubric)


@app.post("/jobs/{job_id}/resumes", response_model=BulkUploadResponse)
def upload_resumes_endpoint(job_id: int, files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job with id {job_id} not found")

    rubric = json.loads(job.rubric_json)
    db.rollback()  # Release the read transaction before waiting on the model.
    if LLM_PROVIDER == "groq" and len(files) > MAX_CLOUD_FILES:
        raise HTTPException(status_code=413, detail="Cloud screening accepts up to 3 PDFs per batch.")
    results = []

    for upload in files:
        filename = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if (
            not filename.lower().endswith(".pdf")
            or upload.content_type not in {"application/pdf", "application/octet-stream"}
            or upload.size is None
            or not 0 < upload.size <= MAX_FILE_BYTES
            or upload.file.read(5) != b"%PDF-"
        ):
            results.append(ResumeUploadResult(
                filename=filename, status="failed", error_code="invalid_pdf", error="Expected a valid PDF of up to 5 MiB."
            ))
            continue
        upload.file.seek(0)
        cleaned_text = extract_text_from_pdf(upload.file, max_pages=30)
        if LLM_PROVIDER == "groq" and cleaned_text and len(cleaned_text) > 12_000:
            results.append(ResumeUploadResult(
                filename=filename, status="failed", error_code="input_too_long",
                error="Cloud resumes are limited to 12,000 extracted characters."
            ))
            continue
        if not cleaned_text:
            results.append(ResumeUploadResult(
                filename=filename, status="failed", error_code="invalid_pdf",
                error="Could not read enough text. Use a PDF with selectable text, up to 30 pages. For a scan, run OCR first."
            ))
            continue

        digest = screening_digest(job_id, filename, cleaned_text, rubric)
        checkpoint = find_checkpoint(db, digest)
        if checkpoint:
            resume_id = checkpoint.id
        else:
            legacy = find_unfinished_legacy_resume(db, job_id, filename, cleaned_text)
            parsed = json.loads(legacy.parsed_json) if legacy else None
            db.rollback()
            if parsed is None:
                try:
                    parsed = structure_resume(cleaned_text)
                except LLMError as exc:
                    results.append(model_failure(filename, "Structuring", exc))
                    continue
            resume_id = save_checkpoint(db, digest, job_id, filename, cleaned_text, parsed)
        results.append(score_checkpoint(db, resume_id, rubric))

    return BulkUploadResponse(job_id=job_id, results=results)
