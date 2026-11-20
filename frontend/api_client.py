"""Server-side client for the screening API."""
import os
from urllib.parse import urlsplit

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def setting(name, default=""):
    value = os.getenv(name)
    if value is not None:
        return value
    try:
        return st.secrets.get(name, default)
    except FileNotFoundError:
        return default


BASE_URL = setting("SHORTLIST_API_URL", "http://127.0.0.1:8000").rstrip("/")
API_TOKEN = setting("SHORTLIST_API_TOKEN").strip()


def request(method, path, *, timeout=60, screening=False, **kwargs):
    def failure(message, code):
        return ({"error_code": code} if screening else None), message

    target = urlsplit(BASE_URL)
    if target.scheme != "https" and not (target.scheme == "http" and target.hostname in {"127.0.0.1", "localhost", "::1"}):
        return failure("Set SHORTLIST_API_URL to an HTTPS endpoint or a local loopback address.", "configuration")
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    try:
        response = requests.request(
            method, BASE_URL + path, timeout=timeout, headers=headers, allow_redirects=False, **kwargs
        )
        if 300 <= response.status_code < 400:
            return failure("The screening service returned a redirect. Check the backend URL.", "configuration")
        response.raise_for_status()
    except requests.Timeout:
        return failure("The screening service timed out. It may still be processing. Check rankings before retrying.", "unconfirmed")
    except requests.HTTPError as exc:
        status = exc.response.status_code
        code = {401: "configuration", 403: "configuration", 404: "not_found", 413: "invalid_pdf",
                429: "rate_limited"}.get(status, "unconfirmed")
        if status in {400, 401, 404, 411, 413, 429, 502, 503}:
            try:
                detail = exc.response.json().get("detail")
                if isinstance(detail, str) and 0 < len(detail) <= 200:
                    return failure(detail, code)
            except (ValueError, AttributeError):
                pass
        return failure(f"The screening service returned an error (HTTP {status}). Check the backend and try again.", code)
    except requests.RequestException:
        return failure("Cannot reach the screening service. Check that the backend is running and try again.", "unconfirmed")
    try:
        data = response.json()
    except ValueError:
        return failure("The screening service returned an unreadable response.", "unconfirmed")
    if not isinstance(data, dict):
        return failure("The screening service returned an unexpected response.", "unconfirmed")
    return data, None


def backend_online():
    data, error = request("GET", "/health", timeout=2)
    return not error and data.get("status") == "ok"


def screen_resume(job_id, upload, resume_id=None):
    filename = upload.name
    failure = {"filename": filename, "status": "failed"}
    if resume_id is not None:
        failure["resume_id"] = resume_id
        data, error = request("POST", f"/jobs/{job_id}/resumes/{resume_id}/retry", timeout=1800, screening=True)
        result = data
    else:
        contents = upload.getvalue()
        if (not filename.lower().endswith(".pdf") or "/" in filename or "\\" in filename
                or not contents.startswith(b"%PDF-") or len(contents) > 5 * 1024 * 1024):
            return {**failure, "error_code": "invalid_pdf", "error": "Choose a valid PDF no larger than 5 MiB."}
        data, error = request(
            "POST", f"/jobs/{job_id}/resumes", files=[("files", (filename, contents, "application/pdf"))],
            timeout=1800, screening=True,
        )
        results = data.get("results") if isinstance(data, dict) else None
        result = results[0] if isinstance(results, list) and len(results) == 1 else None
    if error:
        code = data.get("error_code", "unconfirmed") if isinstance(data, dict) else "unconfirmed"
        return {**failure, "error_code": code, "error": error}

    if (isinstance(result, dict) and result.get("status") in ("success", "failed")
            and result.get("filename") == filename and (resume_id is None or result.get("resume_id") == resume_id)):
        return result
    return {**failure, "error_code": "unconfirmed",
            "error": "The screening service returned an incomplete result. Check rankings before retrying."}


def valid_job(data):
    return (isinstance(data, dict) and isinstance(data.get("id"), int)
            and isinstance(data.get("title"), str) and isinstance(data.get("rubric"), list)
            and bool(data["rubric"]) and all(isinstance(item, dict)
            and isinstance(item.get("criterion"), str) and isinstance(item.get("description"), str)
            and isinstance(item.get("weight"), (int, float)) and 0 <= item["weight"] <= 100
            for item in data["rubric"]))


def valid_rankings(data):
    return (isinstance(data, dict) and isinstance(data.get("rankings"), list)
            and all(isinstance(row, dict) and isinstance(row.get("filename"), str)
                    and isinstance(row.get("total_score"), (int, float)) and 0 <= row["total_score"] <= 10
                    and isinstance(row.get("summary"), str) and isinstance(row.get("criteria_breakdown"), list)
                    and all(isinstance(c, dict) and isinstance(c.get("criterion"), str)
                            and isinstance(c.get("score"), (int, float)) and 0 <= c["score"] <= 10
                            and isinstance(c.get("justification"), str) for c in row["criteria_breakdown"])
                    for row in data["rankings"]))
