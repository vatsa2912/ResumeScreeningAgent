"""Chat transports. Application prompts, validation and scoring live in their callers."""
import math
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache

import httpx

from config import LLM_MODEL, LLM_PROVIDER
from logger_config import get_logger

logger = get_logger(__name__)
RATE_LIMIT = "Groq's free AI rate limit is temporarily in use."
DAILY_LIMIT = "Groq's daily free AI allowance has been reached."
INPUT_TOO_LARGE = "This input exceeds the AI service's single-request limit. Shorten the resume or job description and retry."
UNAVAILABLE = "The AI service is temporarily busy. Please try again shortly."
INVALID_OUTPUT = "The AI service returned an invalid response. Please try again."
MAX_RATE_LIMIT_WAIT = 60
MAX_RATE_LIMIT_TOTAL_WAIT = 120
MAX_RATE_LIMIT_RETRIES = 4


class LLMError(RuntimeError):
    def __init__(self, message, status_code=502, *, error_code=None, retry_after_seconds=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code or ("invalid_output" if message == INVALID_OUTPUT else "provider_error")
        self.retry_after_seconds = retry_after_seconds


@lru_cache(maxsize=1)
def client():
    if LLM_PROVIDER == "groq":
        return httpx.Client(
            base_url="https://api.groq.com/openai/v1/",
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY'].strip()}"},
            timeout=float(os.getenv("GROQ_TIMEOUT") or "35"),
        )
    return httpx.Client(
        base_url=os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434",
        timeout=float(os.getenv("OLLAMA_TIMEOUT") or "300"),
    )


def retry_after(header):
    if not header:
        return None
    try:
        delay = float(header)
    except ValueError:
        try:
            delay = (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, delay) if math.isfinite(delay) else None


def duration_seconds(value):
    # Groq reset headers and its 429 messages use durations such as "2m59.56s".
    if not value or len(value) > 64:
        return None
    units = {"d": 86400, "h": 3600, "m": 60, "s": 1, "ms": 0.001}
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|[dhms])", value)
    if not parts or "".join(number + unit for number, unit in parts) != value:
        return None
    return sum(float(number) * units[unit] for number, unit in parts)


def rate_limit_error(response, retries):
    # Inspect the provider's quota hint locally. Its raw body may contain sensitive data.
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = ""
    message = message[:1600].lower() if isinstance(message, str) else ""
    limit = re.search(r"\blimit\s*:?\s*(\d[\d,]*)", message)
    requested = re.search(r"\brequested\s*:?\s*(\d[\d,]*)", message)
    exceeds_limit = limit and requested and int(requested[1].replace(",", "")) > int(limit[1].replace(",", ""))
    if "request too large" in message or exceeds_limit:
        return LLMError(INPUT_TOO_LARGE, 413, error_code="input_too_large")

    daily = "per day" in message or bool(re.search(r"\b(tpd|rpd)\b", message))
    exhausted_requests = response.headers.get("x-ratelimit-remaining-requests") == "0"
    # This header describes requests per day. A token reset is a separate, minute-based limit.
    daily = daily or exhausted_requests
    seconds = retry_after(response.headers.get("retry-after"))
    if seconds is None:
        hint = re.search(r"try again in\s+([\d.]+(?:ms|[dhms])(?:[\d.]+(?:ms|[dhms]))*)", message)
        seconds = duration_seconds(hint[1]) if hint else None
    if seconds is None:
        if exhausted_requests:
            seconds = duration_seconds(response.headers.get("x-ratelimit-reset-requests"))
        elif not daily and ("tokens per minute" in message or "(tpm)" in message):
            seconds = duration_seconds(response.headers.get("x-ratelimit-reset-tokens"))
    if seconds is None and not daily:
        seconds = min(15 * 2 ** retries, MAX_RATE_LIMIT_WAIT)

    delay = None if seconds is None else max(1, math.ceil(seconds))
    description = DAILY_LIMIT if daily else RATE_LIMIT
    if delay is None:
        description += " Retry when the daily allowance refreshes."
    else:
        description += f" Retry in about {delay} seconds."
    return LLMError(description, 429, error_code="rate_limited", retry_after_seconds=delay)


def chat_json(prompt, *, array=False):
    if LLM_PROVIDER == "ollama":
        try:
            response = client().post(
                "api/chat", json={"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False}
            )
            response.raise_for_status()
            return response.json()["message"]["content"].strip()
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning("Ollama request failed (%s)", type(exc).__name__)
            raise LLMError(UNAVAILABLE, 503) from None

    if LLM_PROVIDER != "groq":
        raise LLMError("The AI provider configuration is invalid.", 503)

    if array:
        prompt += '\nWrap the requested JSON array in a JSON object with a single key "items".'
    payload = {
        "model": os.environ["GROQ_MODEL"].strip(),
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 4096,
    }
    if payload["model"] in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
        payload["reasoning_effort"] = "low"

    rate_retries = 0
    rate_waited = 0
    retried_unavailable = False
    while True:
        delay = 1
        try:
            response = client().post("chat/completions", json=payload)
        except httpx.TransportError as exc:
            logger.warning("Groq transport failed (%s)", type(exc).__name__)
            error = LLMError(UNAVAILABLE, 503, error_code="provider_unavailable")
        else:
            status = response.status_code
            if status == 200:
                try:
                    choice = response.json()["choices"][0]
                    content = choice["message"]["content"]
                    if choice.get("finish_reason") != "length" and isinstance(content, str):
                        return content.strip()
                except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                    pass
                # Business-level retry handles malformed or truncated completions.
                return ""
            logger.warning("Groq returned HTTP %s", status)
            if status == 429:
                error = rate_limit_error(response, rate_retries)
                delay = error.retry_after_seconds
                if delay is not None:
                    # Even a repeatedly rounded-down Retry-After must leave time for refill.
                    delay = max(delay, 2 ** rate_retries)
                if (
                    delay is None or delay > MAX_RATE_LIMIT_WAIT
                    or rate_retries >= MAX_RATE_LIMIT_RETRIES
                    or rate_waited + delay > MAX_RATE_LIMIT_TOTAL_WAIT
                ):
                    logger.warning("Groq quota outcome %s, retry in seconds %s", error.error_code, delay)
                    raise error
                rate_waited += delay
                rate_retries += 1
                time.sleep(delay)
                continue
            if status == 413:
                raise LLMError(INPUT_TOO_LARGE, 413, error_code="input_too_large")
            if status in (400, 422):
                # Groq may reject its own invalid JSON at the HTTP layer.
                try:
                    code = response.json()["error"]["code"]
                except (KeyError, TypeError, ValueError):
                    code = None
                if code == "json_validate_failed":
                    return ""
                if code in {"model_not_found", "model_decommissioned"}:
                    raise LLMError("The configured AI model is unavailable.", 503)
                if code == "context_length_exceeded":
                    raise LLMError(INPUT_TOO_LARGE, 413, error_code="input_too_large")
            if status in (401, 403):
                raise LLMError("The AI service credentials or permissions need attention.", 503)
            if status == 404:
                raise LLMError("The configured AI model is unavailable.", 503)
            if status != 408 and status < 500:
                raise LLMError("The AI service rejected the input or model configuration. Try shorter input or check the model.", 502)
            error = LLMError(UNAVAILABLE, 503, error_code="provider_unavailable")
            hinted = retry_after(response.headers.get("retry-after"))
            delay = hinted if hinted is not None else delay
        if retried_unavailable or delay > 5:
            raise error
        retried_unavailable = True
        time.sleep(delay)
