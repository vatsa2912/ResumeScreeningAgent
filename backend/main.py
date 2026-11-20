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
from crud import create_job, update_job_rubric, get_rankings_for_job, get_job, create_resume, create_score, get_resume_by_id, get_score_for_resume
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
    return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)


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

    return JobResponse(
        id=job.id,
        title=job.title,
        raw_description=job.raw_description,
        rubric=json.loads(job.rubric_json)
    )
    
@app.put("/jobs/{job_id}/rubric", response_model=JobResponse)
def update_rubric_endpoint(job_id: int, request: RubricUpdateRequest, db: Session = Depends(get_db)):
    try:
        job = update_job_rubric(db, job_id, request.rubric)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rubric. Check criterion fields and weights.")

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job with id {job_id} not found")

    return JobResponse(
        id=job.id,
        title=job.title,
        raw_description=job.raw_description,
        rubric=json.loads(job.rubric_json)
    )

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
                filename=filename, status="failed", error="Expected a valid PDF of up to 5 MiB."
            ))
            continue
        upload.file.seek(0)
        cleaned_text = extract_text_from_pdf(upload.file, max_pages=30)
        if LLM_PROVIDER == "groq" and cleaned_text and len(cleaned_text) > 12_000:
            results.append(ResumeUploadResult(
                filename=filename, status="failed", error="Cloud resumes are limited to 12,000 extracted characters."
            ))
            continue
        if cleaned_text is None:
            results.append(ResumeUploadResult(
                filename=filename, status="failed", error="Could not extract text from PDF"
            ))
            continue

        try:
            resume_data = structure_resume(cleaned_text)
        except LLMError as e:
            results.append(ResumeUploadResult(
                filename=filename, status="failed", error=f"Structuring failed: {e}"
            ))
            continue

        resume_record = create_resume(
            db, job_id=job_id, filename=filename, raw_text=cleaned_text, parsed_data=resume_data
        )

        resume_id = resume_record.id
        db.rollback()
        try:
            scoring_result = score_resume(resume_data, rubric)
        except LLMError as e:
            results.append(ResumeUploadResult(
                filename=filename, status="failed", resume_id=resume_id, error=f"Scoring failed: {e}"
            ))
            continue

        create_score(db, resume_id=resume_id, job_id=job_id, scoring_result=scoring_result)

        db.rollback()  # Release the transaction opened by the score refresh.
        results.append(ResumeUploadResult(
            filename=filename,
            status="success",
            resume_id=resume_id,
            total_score=scoring_result["total_score"]
        ))
        
        
    return BulkUploadResponse(job_id=job_id, results=results)