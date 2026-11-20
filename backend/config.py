import os

from dotenv import load_dotenv

load_dotenv()

LLM_MODEL = os.getenv("OLLAMA_MODEL") or "qwen2.5:7b-instruct"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
API_TOKEN = os.getenv("SHORTLIST_API_TOKEN", "").strip()


def validate_settings():
    if LLM_PROVIDER not in {"ollama", "groq"}:
        raise RuntimeError("LLM_PROVIDER must be ollama or groq.")
    if os.getenv("RENDER") == "true" and LLM_PROVIDER != "groq":
        raise RuntimeError("Render requires LLM_PROVIDER=groq.")
    if LLM_PROVIDER == "groq":
        if not all(os.getenv(key, "").strip() for key in ("GROQ_API_KEY", "GROQ_MODEL")):
            raise RuntimeError("Groq requires GROQ_API_KEY and GROQ_MODEL.")
        if len(API_TOKEN) < 32:
            raise RuntimeError("Groq mode requires a strong SHORTLIST_API_TOKEN of at least 32 characters.")
