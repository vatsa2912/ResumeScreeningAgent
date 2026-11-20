"""Check upload recovery against a fresh SQLite database and synthetic model results."""
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from test_deployment import AUTH, PROFILE, RUBRIC, SCORES, TOKEN, synthetic_pdf

import crud
import database
import main
from llm_provider import LLMError, RATE_LIMIT
from resume_parser import extract_text_from_pdf


SCORE = {"total_score": 8.0, "criteria_breakdown": SCORES, "summary": "Synthetic score"}


def limited():
    return LLMError(RATE_LIMIT, 429, error_code="rate_limited", retry_after_seconds=90)


class ResumeRecoveryTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        engine = create_engine("sqlite:///" + (Path(directory) / "recovery.db").as_posix())
        self.addCleanup(engine.dispose)
        self.enterContext(patch.multiple(database, engine=engine, SessionLocal=sessionmaker(bind=engine)))
        self.enterContext(patch.object(main, "API_TOKEN", TOKEN))
        self.api = self.enterContext(TestClient(main.app))
        self.structure = self.enterContext(patch.object(main, "structure_resume", return_value=PROFILE))
        self.score = self.enterContext(patch.object(main, "score_resume", return_value=SCORE))
        self.pdf = synthetic_pdf()
        self.job_id = self.new_job()
        self.path = f"/jobs/{self.job_id}"

    def new_job(self):
        with database.get_session() as db:
            return crud.create_job(db, "Developer", "Python programming is required.", RUBRIC).id

    def upload(self, path=None):
        response = self.api.post(
            (path or self.path) + "/resumes", headers=AUTH,
            files={"files": ("demo.pdf", self.pdf, "application/pdf")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result, = response.json()["results"]
        return result

    def test_retry_after_scoring_failure_keeps_one_score(self):
        self.score.side_effect = [limited(), SCORE]
        first = self.upload()
        self.assertEqual((first["status"], first["error_code"], first["retry_after_seconds"]),
                         ("failed", "rate_limited", 90))
        resume_id = first["resume_id"]
        self.assertIsInstance(resume_id, int)
        retry = f"{self.path}/resumes/{resume_id}/retry"
        for _ in range(2):
            response = self.api.post(retry, headers=AUTH)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual((result["status"], result["resume_id"], result["total_score"]),
                             ("success", resume_id, SCORE["total_score"]))

        replay = self.upload()
        self.assertEqual((replay["status"], replay["resume_id"]), ("success", resume_id))
        rankings = self.api.get(self.path + "/rankings", headers=AUTH).json()["rankings"]
        self.assertEqual([row["resume_id"] for row in rankings], [resume_id])
        self.structure.assert_called_once()
        self.assertEqual(self.score.call_count, 2)

    def test_structuring_failure_can_be_resubmitted(self):
        self.structure.side_effect = [limited(), PROFILE]
        first = self.upload()
        self.assertEqual(first["error_code"], "rate_limited")
        self.assertIsNone(first["resume_id"])
        self.score.assert_not_called()
        self.assertEqual(self.upload()["status"], "success")
        self.assertEqual(self.structure.call_count, 2)
        self.score.assert_called_once()

    def test_upload_replays_only_for_matching_job_and_rubric(self):
        first = self.upload()
        self.assertEqual(self.upload()["resume_id"], first["resume_id"])
        self.score.assert_called_once()
        revised = [{**RUBRIC[0], "description": "Python programming in a production environment"}]
        response = self.api.put(self.path + "/rubric", headers=AUTH, json={"rubric": revised})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.upload()["status"], "success")
        self.assertEqual(self.score.call_count, 2)
        self.assertEqual(self.score.call_args.args[1], revised)

        other_job = f"/jobs/{self.new_job()}"
        other = self.upload(other_job)
        self.assertEqual(other["status"], "success")
        self.assertNotEqual(other["resume_id"], first["resume_id"])
        self.assertEqual(self.score.call_count, 3)
        forbidden = self.api.post(f"{other_job}/resumes/{first['resume_id']}/retry", headers=AUTH)
        self.assertEqual(forbidden.status_code, 404)

    def test_existing_unscored_resume_reuses_parsed_data(self):
        raw_text = extract_text_from_pdf(io.BytesIO(self.pdf))
        with database.get_session() as db:
            resume_id = crud.create_resume(db, self.job_id, "demo.pdf", raw_text, PROFILE).id
        result = self.upload()
        self.assertEqual((result["status"], result["resume_id"]), ("success", resume_id))
        self.structure.assert_not_called()
        self.score.assert_called_once_with(PROFILE, RUBRIC)

    def test_concurrent_matching_uploads_return_one_ranking(self):
        start = Barrier(2)

        def submit():
            start.wait(timeout=10)
            return self.upload()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit) for _ in range(2)]
            first, second = [future.result(timeout=20) for future in futures]
        self.assertEqual((first["status"], second["status"]), ("success", "success"))
        self.assertEqual(first["resume_id"], second["resume_id"])
        rankings = self.api.get(self.path + "/rankings", headers=AUTH).json()["rankings"]
        self.assertEqual([row["resume_id"] for row in rankings], [first["resume_id"]])

    def test_reopen_job_and_retry_require_authentication(self):
        self.assertEqual(self.api.get(self.path).status_code, 401)
        self.assertEqual(self.api.post(self.path + "/resumes/1/retry").status_code, 401)
        response = self.api.get(self.path, headers=AUTH)
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()
        self.assertEqual((job["id"], job["title"], job["rubric"]), (self.job_id, "Developer", RUBRIC))
        self.assertEqual(self.api.get("/jobs/99999", headers=AUTH).status_code, 404)
