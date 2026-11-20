import hashlib
import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from models import Job, Resume, Score, ScreeningReceipt
from logger_config import get_logger
from rubric_builder import normalize_weights, validate_rubric
import os

logger = get_logger(os.path.splitext(os.path.basename(__file__))[0])


def create_job(db: Session, title: str, raw_description: str, rubric: list[dict]) -> Job:
    job = Job(
        title=title,
        raw_description=raw_description,
        rubric_json=json.dumps(rubric)
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(f"Created job with id {job.id}")
    return job


def get_job(db: Session, job_id: int) -> Job | None:
    return db.query(Job).filter(Job.id == job_id).first()

def update_job_rubric(db: Session, job_id: int, rubric: list[dict]) -> Job | None:
    job = get_job(db, job_id)
    if job is None:
        return None

    validate_rubric(rubric)
    rubric = normalize_weights(rubric)

    job.rubric_json = json.dumps(rubric)
    db.commit()
    db.refresh(job)
    logger.info(f"Updated rubric for job_id {job_id}")
    return job


def get_job_rubric(db: Session, job_id: int) -> list[dict] | None:
    job = get_job(db, job_id)
    if job is None:
        return None
    return json.loads(job.rubric_json)


def create_resume(db: Session, job_id: int, filename: str, raw_text: str, parsed_data: dict) -> Resume:
    resume = Resume(
        job_id=job_id,
        filename=filename,
        raw_text=raw_text,
        parsed_json=json.dumps(parsed_data)
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    logger.info(f"Saved resume for job_id {job_id} with id {resume.id}")
    return resume

def get_resume_by_id(db: Session, resume_id: int) -> Resume | None:
    return db.query(Resume).filter(Resume.id == resume_id).first()


def screening_digest(job_id, filename, raw_text, rubric):
    inputs = json.dumps([job_id, filename, raw_text, rubric], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(inputs.encode("utf-8")).hexdigest()


def find_checkpoint(db, digest):
    return db.query(Resume).join(ScreeningReceipt).filter(ScreeningReceipt.input_digest == digest).first()


def find_unfinished_legacy_resume(db, job_id, filename, raw_text, resume_id=None):
    # Existing installations may have a parsed resume from a failed scoring call.
    has_receipt = db.query(ScreeningReceipt).filter(ScreeningReceipt.resume_id == Resume.id).exists()
    query = db.query(Resume).filter(
        Resume.job_id == job_id, Resume.filename == filename, Resume.raw_text == raw_text,
        ~Resume.scores.any(), ~has_receipt,
    )
    if resume_id is not None:
        query = query.filter(Resume.id == resume_id)
    return query.order_by(Resume.id.desc()).first()


def lock_job_for_write(db, job_id):
    # Serialize only the short checkpoint/score writes, never the model requests.
    db.rollback()
    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        db.query(Job.id).filter(Job.id == job_id).with_for_update().one()


def save_checkpoint(db, digest, job_id, filename, raw_text, parsed_data, legacy_id=None):
    lock_job_for_write(db, job_id)
    resume = find_checkpoint(db, digest)
    if resume is None:
        resume = find_unfinished_legacy_resume(db, job_id, filename, raw_text, legacy_id)
        if resume is None:
            resume = Resume(job_id=job_id, filename=filename, raw_text=raw_text,
                            parsed_json=json.dumps(parsed_data))
            db.add(resume)
            db.flush()
        db.add(ScreeningReceipt(input_digest=digest, resume_id=resume.id))
    resume_id = resume.id
    db.commit()
    return resume_id


def get_score_for_resume(db: Session, resume_id: int) -> Score | None:
    return db.query(Score).filter(Score.resume_id == resume_id).first()


def get_resumes_for_job(db: Session, job_id: int) -> list[Resume]:
    return db.query(Resume).filter(Resume.job_id == job_id).all()


def create_score(db: Session, resume_id: int, job_id: int, scoring_result: dict) -> Score:
    score = Score(
        resume_id=resume_id,
        job_id=job_id,
        total_score=scoring_result["total_score"],
        criteria_breakdown_json=json.dumps(scoring_result["criteria_breakdown"]),
        justification_text=scoring_result.get("summary", "")
    )
    db.add(score)
    db.commit()
    db.refresh(score)
    logger.info(f"Saved score for resume_id {resume_id}: {score.total_score}/10")
    return score


def save_score_once(db, resume_id, job_id, scoring_result):
    lock_job_for_write(db, job_id)
    score = get_score_for_resume(db, resume_id) or create_score(db, resume_id, job_id, scoring_result)
    total = score.total_score
    db.rollback()
    return total


def get_rankings_for_job(db: Session, job_id: int) -> list[dict]:
    rows = (
        db.query(Score, Resume.filename)
        .outerjoin(Resume, Score.resume_id == Resume.id)
        .filter(Score.job_id == job_id)
        .order_by(Score.total_score.desc())
        .all()
    )

    rankings = []
    for score, filename in rows:
        rankings.append({
            "resume_id": score.resume_id,
            "filename": filename if filename is not None else "Unknown",
            "total_score": score.total_score,
            "criteria_breakdown": json.loads(score.criteria_breakdown_json),
            "summary": score.justification_text
        })
        


    return rankings
