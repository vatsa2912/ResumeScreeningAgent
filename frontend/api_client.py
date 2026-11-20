"""Small client for the existing local screening API."""
import os

import requests

BASE_URL = os.getenv("SHORTLIST_API_URL", "http://127.0.0.1:8000").rstrip("/")


def request(method, path, *, timeout=60, **kwargs):
    try:
        response = requests.request(method, BASE_URL + path, timeout=timeout, **kwargs)
        response.raise_for_status()
    except requests.Timeout:
        return None, "The screening service timed out. Local AI processing can take several minutes; check the backend before retrying."
    except requests.HTTPError as exc:
        return None, f"The screening service returned an error (HTTP {exc.response.status_code}). Check the backend and try again."
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
    data, error = request("GET", "/openapi.json", timeout=2)
    return not error and isinstance(data.get("paths"), dict)


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
