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


def request(method, path, *, timeout=60, **kwargs):
    target = urlsplit(BASE_URL)
    if target.scheme != "https" and not (target.scheme == "http" and target.hostname in {"127.0.0.1", "localhost", "::1"}):
        return None, "Set SHORTLIST_API_URL to an HTTPS endpoint or a local loopback address."
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    try:
        response = requests.request(
            method, BASE_URL + path, timeout=timeout, headers=headers, allow_redirects=False, **kwargs
        )
        if 300 <= response.status_code < 400:
            return None, "The screening service returned a redirect. Check the backend URL."
        response.raise_for_status()
    except requests.Timeout:
        return None, "The screening service timed out. It may still be processing. Check rankings before retrying."
    except requests.HTTPError as exc:
        status = exc.response.status_code
        if status in {400, 401, 411, 413, 429, 502, 503}:
            try:
                detail = exc.response.json().get("detail")
                if isinstance(detail, str) and 0 < len(detail) <= 200:
                    return None, detail
            except (ValueError, AttributeError):
                pass
        return None, f"The screening service returned an error (HTTP {status}). Check the backend and try again."
    except requests.RequestException:
        return None, "Cannot reach the screening service. Check that the backend is running and try again."
    try:
        data = response.json()
    except ValueError:
        return None, "The screening service returned an unreadable response."
    if not isinstance(data, dict):
        return None, "The screening service returned an unexpected response."
    return data, None


def backend_online():
    data, error = request("GET", "/health", timeout=2)
    return not error and data.get("status") == "ok"


def screen_resume(job_id, upload):
    filename = upload.name
    contents = upload.getvalue()
    failure = {"filename": filename, "status": "failed"}
    if (
        not filename.lower().endswith(".pdf")
        or "/" in filename
        or "\\" in filename
        or not contents.startswith(b"%PDF-")
    ):
        return {**failure, "error": "Each file needs a valid PDF header and filename."}

    data, error = request(
        "POST",
        f"/jobs/{job_id}/resumes",
        files=[("files", (filename, contents, "application/pdf"))],
        timeout=1800,
    )
    if error:
        return {**failure, "error": error}

    results = data.get("results")
    if (
        isinstance(results, list) and len(results) == 1
        and isinstance(results[0], dict)
        and results[0].get("status") in ("success", "failed")
        and results[0].get("filename") == filename
    ):
        return results[0]
    return {**failure, "error": "The screening service returned an incomplete result. Check rankings before retrying."}


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
