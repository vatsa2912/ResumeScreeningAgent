"""Exercise multi-file recovery through the Streamlit upload controls."""
from collections import Counter
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "frontend"))
import api_client


JOB = {"id": 22, "title": "Developer", "rubric": [{"criterion": "Python", "description": "Build software", "weight": 100}]}


def button(app, prefix):
    return next(item for item in app.button if item.label.startswith(prefix))


def upload(filename, contents=None):
    return (filename, contents if contents is not None else b"%PDF-example " + filename.encode(), "application/pdf")


class BatchRecoveryTests(unittest.TestCase):
    def start_app(self, handler, with_job=True):
        def request(method, path, **kwargs):
            if method == "GET" and path == "/jobs/22/rankings":
                return {"rankings": []}, None
            return handler(method, path, **kwargs)

        self.enterContext(patch.object(api_client, "backend_online", return_value=True))
        self.enterContext(patch.object(api_client, "request", side_effect=request))
        app = AppTest.from_file(str(ROOT / "frontend" / "app.py")).run()
        if with_job:
            app.session_state["job"] = JOB
            app.session_state["weights"] = [100]
            app.button(key="nav_Resume Screening").click().run()
        return app

    def test_seven_with_four_failures_retries_only_those_four(self):
        attempts = Counter()
        score_retries = []
        names = [f"resume-{index}.pdf" for index in range(7)]

        def respond(method, path, **kwargs):
            self.assertEqual(method, "POST")
            if path == "/jobs/22/resumes/74/retry":
                self.assertNotIn("files", kwargs)
                score_retries.append(path)
                return {"filename": names[3], "status": "success", "resume_id": 74, "total_score": 8}, None
            self.assertEqual(path, "/jobs/22/resumes")
            filename = kwargs["files"][0][1][0]
            attempts[filename] += 1
            result = {"filename": filename, "status": "success", "total_score": 8}
            if filename in names[3:] and attempts[filename] == 1:
                result = {"filename": filename, "status": "failed", "error": "The AI service is busy."}
                if filename == names[3]:
                    result["resume_id"] = 74
            return {"results": [result]}, None

        app = self.start_app(respond)
        app.file_uploader[0].set_value([upload(name) for name in names]).run()
        button(app, "Evaluate Candidates").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("3 succeeded and 4 failed" in item.value for item in app.warning))
        button(app, "Continue screening (4)").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("7 succeeded and 0 failed" in item.value for item in app.success))
        self.assertEqual([attempts[name] for name in names], [1, 1, 1, 1, 2, 2, 2])
        self.assertEqual(len(score_retries), 1)

    def test_rate_limit_pauses_selection_until_retry_time(self):
        submitted = []
        names = [f"resume-{index}.pdf" for index in range(7)]

        def respond(method, path, **kwargs):
            filename = kwargs["files"][0][1][0]
            submitted.append(filename)
            if len(submitted) == 4:
                return {"results": [{"filename": filename, "status": "failed", "error_code": "rate_limited",
                                     "error": "Try again in two minutes.", "retry_after_seconds": 120}]}, None
            return {"results": [{"filename": filename, "status": "success", "total_score": 8}]}, None

        app = self.start_app(respond)
        app.file_uploader[0].set_value([upload(name) for name in names]).run()
        button(app, "Evaluate Candidates").click().run()
        self.assertEqual(submitted, names[:4])
        self.assertEqual([item["status"] for item in app.session_state["eval_result"]],
                         ["success"] * 3 + ["failed"] + ["pending"] * 3)
        button(app, "Continue screening").click().run()
        self.assertEqual(submitted, names[:4])
        app.session_state["screening_retry_at"] = 0
        button(app, "Continue screening").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(submitted, names[:4] + names[3:])
        self.assertTrue(any("7 succeeded" in item.value for item in app.success))

    def test_same_name_replacements_and_unconfirmed_uploads(self):
        received = []

        def respond(method, path, **kwargs):
            filename, contents, _ = kwargs["files"][0][1]
            received.append(contents)
            if filename == "uncertain.pdf":
                return {"error_code": "unconfirmed"}, "The service timed out."
            return {"results": [{"filename": filename, "status": "success", "total_score": 8}]}, None

        app = self.start_app(respond)
        good = upload("same.pdf")
        bad = upload("same.pdf", b"invalid")
        ambiguous = upload("uncertain.pdf")
        replacement = upload("same.pdf", b"%PDF-new document content")
        app.file_uploader[0].set_value([good, bad, ambiguous]).run()
        button(app, "Evaluate Candidates").click().run()
        self.assertEqual(received, [good[1], ambiguous[1]])
        self.assertTrue(button(app, "Continue screening (0)").disabled)
        app.file_uploader[0].set_value([good, replacement, ambiguous]).run()
        button(app, "Continue screening (1)").click().run()
        self.assertEqual(received, [good[1], ambiguous[1], replacement[1]])
        button(app, "Retry unconfirmed").click().run()
        self.assertEqual(received[-1], ambiguous[1])
        self.assertFalse(app.exception)

    def test_reopen_saved_job(self):
        def respond(method, path, **kwargs):
            self.assertEqual((method, path), ("GET", "/jobs/22"))
            return JOB, None

        app = self.start_app(respond, with_job=False)
        app.button(key="nav_Job Setup").click().run()
        app.number_input[0].set_value(22)
        button(app, "Reopen saved job").click().run()
        self.assertEqual(app.session_state["job"], JOB)
        self.assertEqual(app.session_state["rankings"], [])
        self.assertEqual(app.session_state["page"], "Resume Screening")
        self.assertFalse(app.exception)

    def test_previous_version_batch_guidance_preserves_saved_scores(self):
        submitted = []

        def respond(method, path, **kwargs):
            filename = kwargs["files"][0][1][0]
            submitted.append(filename)
            return {"results": [{"filename": filename, "status": "success", "total_score": 7}]}, None

        app = self.start_app(respond, with_job=False)
        app.session_state["job"] = JOB
        app.session_state["weights"] = [100]
        app.session_state["eval_result"] = [{"filename": "scored.pdf", "status": "success"},
                                            {"filename": "retry.pdf", "status": "failed"}]
        app.button(key="nav_Resume Screening").click().run()
        self.assertTrue(any("1 scored · 1 failed" in item.value for item in app.info))
        app.file_uploader[0].set_value([upload("scored.pdf"), upload("retry.pdf")]).run()
        self.assertTrue(button(app, "Evaluate Candidates").disabled)
        app.file_uploader[0].set_value([upload("retry.pdf")]).run()
        button(app, "Evaluate Candidates").click().run()
        self.assertEqual(submitted, ["retry.pdf"])
        self.assertFalse(app.exception)

    def test_changed_saved_rubric_can_evaluate_same_file_again(self):
        submitted = []

        def respond(method, path, **kwargs):
            filename = kwargs["files"][0][1][0]
            submitted.append(filename)
            return {"results": [{"filename": filename, "status": "success", "total_score": 8}]}, None

        app = self.start_app(respond)
        app.file_uploader[0].set_value([upload("resume.pdf")]).run()
        button(app, "Evaluate Candidates").click().run()
        self.assertTrue(button(app, "Continue screening (0)").disabled)
        app.session_state["job"] = {**JOB, "rubric": [{**JOB["rubric"][0], "description": "Different requirement"}]}
        app.run()
        button(app, "Evaluate Candidates").click().run()
        self.assertEqual(submitted, ["resume.pdf", "resume.pdf"])
        self.assertFalse(app.exception)
