"""Chat transports. Application prompts, validation and scoring live in their callers."""
import math
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache

import httpx

from config import LLM_MODEL, LLM_PROVIDER
from logger_config import get_logger

logger = get_logger(__name__)
RATE_LIMIT = "The free AI usage limit has been reached. Please try again later."
UNAVAILABLE = "The AI service is temporarily busy. Please try again shortly."
INVALID_OUTPUT = "The AI service returned an invalid response. Please try again."
MAX_RATE_LIMIT_WAIT = 60


class LLMError(RuntimeError):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


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


def retry_delay(header, attempt):
    if not header:
        return 2 ** attempt
    try:
        delay = float(header)
    except ValueError:
        try:
            delay = (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 2 ** attempt
    return max(0, delay) if math.isfinite(delay) else 2 ** attempt


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
    for attempt in range(2):
        delay = 2 ** attempt
        max_wait = 5
        try:
            response = client().post("chat/completions", json=payload)
        except httpx.TransportError as exc:
            logger.warning("Groq transport failed (%s)", type(exc).__name__)
            error = LLMError(UNAVAILABLE, 503)
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
                    raise LLMError("The AI service input is too long. Try a shorter description or resume.", 502)
            if status in (401, 403):
                raise LLMError("The AI service credentials or permissions need attention.", 503)
            if status == 404:
                raise LLMError("The configured AI model is unavailable.", 503)
            if status not in (408, 429) and status < 500:
                raise LLMError("The AI service rejected the input or model configuration. Try shorter input or check the model.", 502)
            error = LLMError(RATE_LIMIT, 429) if status == 429 else LLMError(UNAVAILABLE, 503)
            delay = retry_delay(response.headers.get("retry-after"), attempt)
            if status == 429:
                max_wait = MAX_RATE_LIMIT_WAIT
        if attempt == 1 or delay > max_wait:
            raise error
        time.sleep(delay)
