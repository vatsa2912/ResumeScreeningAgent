"""Deployment regression checks using synthetic data only."""
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "frontend")]

import database
import llm_provider
import main
import resume_structurer
import rubric_builder

TOKEN = "synthetic-test-token-not-a-credential"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
RUBRIC = [{"criterion": "Python", "description": "Python programming", "weight": 100, "how_to_detect": "Find Python projects"}]
PROFILE = {
    "name": "Synthetic Candidate", "email": None, "phone": None,
    "skills": {"technical_skills": ["Python"], "soft_skills": []},
    "years_of_experience": 0, "education": [], "roles": [],
    "projects": [{"name": "Demo", "summary": "Built a parser with Python.", "tech_used": ["Python"]}],
}
SCORES = [{"criterion": "Python", "score": 8, "justification": "Built a parser with Python in the Demo project."}]


def synthetic_pdf():
    text = (
        b"BT /F1 12 Tf 30 700 Td (Synthetic Candidate) Tj "
        b"0 -20 Td (Python project: built a text parser with Python and tested parsing.) Tj "
        b"0 -20 Td (Skills: Python, unit testing, file processing, and debugging.) Tj ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = io.BytesIO()
    pdf.write(b"%PDF-1.4\n")
    offsets = [0]
    for number, data in enumerate(objects, 1):
        offsets.append(pdf.tell())
        pdf.write(b"%d 0 obj\n" % number + data + b"\nendobj\n")
    xref = pdf.tell()
    pdf.write(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.write(b"%010d 00000 n \n" % offset)
    pdf.write(b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % xref)
    return pdf.getvalue()


class ApiTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        setup = patch.multiple(database, engine=engine, SessionLocal=sessionmaker(bind=engine))
        self.addCleanup(setup.stop)
        setup.start()
        self.enterContext(patch.object(main, "API_TOKEN", TOKEN))
        self.api = self.enterContext(TestClient(main.app))

    def workflow(self):
        response = self.api.post("/jobs", headers=AUTH, json={"title": "Developer", "raw_description": "Python programming is required."})
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()
        path = f"/jobs/{job['id']}"
        saved = self.api.put(path + "/rubric", headers=AUTH, json={"rubric": job["rubric"]})
        self.assertEqual(saved.status_code, 200, saved.text)
        response = self.api.post(
            path + "/resumes", headers=AUTH,
            files=[("files", ("demo.pdf", synthetic_pdf(), "application/pdf")),
                   ("files", ("invalid.pdf", b"invalid", "application/pdf"))],
        )
        self.assertEqual(response.status_code, 200, response.text)
        result, invalid = response.json()["results"]
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(invalid["status"], "failed")
        rankings = self.api.get(path + "/rankings", headers=AUTH).json()["rankings"]
        self.assertEqual(rankings[0]["total_score"], result["total_score"])
        detail = self.api.get(f"/resumes/{result['resume_id']}", headers=AUTH)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIn("Python", detail.json()["parsed_data"]["skills"]["technical_skills"])

    def test_workflow_with_mocked_models(self):
        with (
            patch.object(rubric_builder, "chat_json", side_effect=["broken JSON", json.dumps(RUBRIC)]) as chat,
            patch.object(resume_structurer, "chat_json", return_value=json.dumps(PROFILE)),
            patch("scoring_agent.chat_json", return_value=json.dumps(SCORES)),
        ):
            self.workflow()
            self.assertEqual(chat.call_count, 2)

    def test_auth_health_and_size_limit(self):
        self.assertEqual(self.api.get("/health").json(), {"status": "ok"})
        for method, path in (("POST", "/jobs"), ("PUT", "/jobs/1/rubric"),
                             ("POST", "/jobs/1/resumes"), ("GET", "/jobs/1/rankings"), ("GET", "/resumes/1")):
            self.assertEqual(self.api.request(method, path).status_code, 401)
        response = self.api.post("/jobs/1/resumes", headers={**AUTH, "content-length": str(main.MAX_BATCH_BYTES + 1)})
        self.assertEqual(response.status_code, 413)

    def test_safe_llm_error(self):
        with patch.object(rubric_builder, "chat_json", return_value="[42]") as chat:
            response = self.api.post("/jobs", headers=AUTH, json={"title": "Developer", "raw_description": "Python"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], llm_provider.INVALID_OUTPUT)
        self.assertEqual(chat.call_count, 3)

    def test_workflow_through_mocked_groq_http(self):
        completions = iter([
            httpx.Response(400, json={"error": {"code": "json_validate_failed"}}),
            *(httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})
              for value in ({"items": RUBRIC}, PROFILE, {"items": SCORES})),
        ])
        with (
            httpx.Client(base_url="https://mock.invalid/", transport=httpx.MockTransport(lambda _: next(completions))) as client,
            patch.object(llm_provider, "client", return_value=client),
            patch.object(llm_provider, "LLM_PROVIDER", "groq"),
            patch.object(main, "LLM_PROVIDER", "groq"),
            patch.object(rubric_builder, "LLM_PROVIDER", "groq"),
            patch("scoring_agent.LLM_PROVIDER", "groq"),
            patch.dict(os.environ, {"GROQ_MODEL": "test-model"}),
        ):
            self.workflow()

    @unittest.skipUnless(os.getenv("SHORTLIST_TEST_LIVE") == "1", "requires a running local Ollama model")
    def test_live_ollama_workflow(self):
        self.assertEqual(llm_provider.LLM_PROVIDER, "ollama")
        self.workflow()


class ProviderTests(unittest.TestCase):
    def test_groq_rate_limit_retry_and_json_envelope(self):
        requests = []

        def respond(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(429, headers={"Retry-After": "2"})
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"items": RUBRIC})}}]})

        with (
            httpx.Client(base_url="https://mock.invalid/openai/v1/", transport=httpx.MockTransport(respond)) as client,
            patch.object(llm_provider, "client", return_value=client),
            patch.object(llm_provider, "LLM_PROVIDER", "groq"),
            patch.object(rubric_builder, "LLM_PROVIDER", "groq"),
            patch.dict(os.environ, {"GROQ_MODEL": "test-model"}),
            patch.object(llm_provider.time, "sleep") as sleep,
        ):
            self.assertEqual(rubric_builder.build_rubric("Python"), RUBRIC)
        sleep.assert_called_once_with(2)
        self.assertEqual(json.loads(requests[1].content)["response_format"], {"type": "json_object"})

    def test_groq_long_wait_and_configuration_fail_fast(self):
        for status in (429, 401, 404, 400):
            with (
                patch.object(llm_provider, "client") as client,
                patch.object(llm_provider, "LLM_PROVIDER", "groq"),
                patch.dict(os.environ, {"GROQ_MODEL": "test-model"}),
                patch.object(llm_provider.time, "sleep") as sleep,
            ):
                client.return_value.post.return_value = httpx.Response(status, headers={"Retry-After": "100"})
                with self.assertRaises(llm_provider.LLMError) as raised:
                    llm_provider.chat_json("test")
                self.assertEqual(raised.exception.status_code, 429 if status == 429 else 502 if status == 400 else 503)
                client.return_value.post.assert_called_once()
                sleep.assert_not_called()


class StreamlitTests(unittest.TestCase):
    def test_navigation_rubric_and_rankings_state(self):
        from streamlit.testing.v1 import AppTest
        import api_client

        job = {"id": 1, "title": "Developer", "rubric": RUBRIC}
        ranking = {"filename": "demo.pdf", "total_score": 8, "summary": "Synthetic result",
                   "criteria_breakdown": SCORES}
        with (
            patch.object(api_client, "backend_online", return_value=True),
            patch.object(api_client, "request", side_effect=[
                (job, None), (job, None),
                ({"results": [{"filename": "demo.pdf", "status": "success", "total_score": 8}]}, None),
                ({"rankings": [ranking]}, None), ({"rankings": [ranking]}, None), (job, None),
            ]),
        ):
            app = AppTest.from_file(str(ROOT / "frontend" / "app.py")).run()
            app.button(key="nav_Job Setup").click().run()
            app.text_input(key="title_widget").set_value("Developer").run()
            app.text_area(key="description_widget").set_value("Python").run()
            next(button for button in app.button if "Generate" in button.label).click().run()
            self.assertEqual(app.session_state["job"]["id"], 1)
            app.button(key="nav_Scoring Criteria").click().run()
            next(button for button in app.button if "Save" in button.label).click().run()
            app.button(key="nav_Resume Screening").click().run()
            app.file_uploader[0].set_value(("demo.pdf", synthetic_pdf(), "application/pdf")).run()
            next(button for button in app.button if "Evaluate Candidates" in button.label).click().run()
            self.assertEqual(app.session_state["eval_result"][0]["status"], "success")
            app.button(key="nav_Candidate Rankings").click().run()
            next(button for button in app.button if button.label == "Refresh rankings").click().run()
            self.assertEqual(app.session_state["rankings"][0]["filename"], "demo.pdf")
            self.assertFalse(app.exception)
            app.button(key="nav_Scoring Criteria").click().run()
            app.number_input[0].set_value(90).run()
            next(button for button in app.button if "Save" in button.label).click().run()
            app.button(key="nav_Candidate Rankings").click().run()
            self.assertTrue(app.session_state["rankings_stale"])
            self.assertTrue(any("earlier version" in item.value for item in app.warning))
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
