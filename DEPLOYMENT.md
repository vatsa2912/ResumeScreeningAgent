# Deploy Shortlist

Shortlist runs locally with Ollama and SQLite, or as an invite-only university demo with Streamlit Community Cloud, Render, Groq Free, and Neon Free. Read [Free tier limits](FREE_TIER_LIMITS.md) before provisioning anything. Use synthetic resumes for the cloud demonstration.

## Windows local setup

Install Python 3.13 and [Ollama for Windows](https://ollama.com/download/windows). Run the commands below from the repository root. The checked-in default model is `qwen2.5:7b-instruct`.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
ollama list
# If Qwen is missing, with the Ollama desktop service running:
ollama pull qwen2.5:7b-instruct
```

If you use this workspace's portable Ollama installation, start it in a separate PowerShell window with:

```powershell
$env:OLLAMA_MODELS = Join-Path (Get-Location) 'ollama-models'
.\ollama\ollama.exe serve
```

If the portable runner fails to initialize CUDA, restart it with `$env:CUDA_VISIBLE_DEVICES = '-1'` and `$env:OLLAMA_VULKAN = '0'` in its PowerShell window to use the same model on CPU. Set `OLLAMA_NO_CLOUD=1` in the Ollama server environment if you want to disable Ollama's cloud features.

Reuse an existing Ollama process if it already serves the model. To run both installations simultaneously, set `OLLAMA_HOST` to a different loopback port before starting the portable server, and set the matching `OLLAMA_BASE_URL` in `.env`.

Run the backend and frontend in two separate PowerShell windows:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py --server.address 127.0.0.1
```

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
$env:SHORTLIST_TEST_LIVE = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -k live_ollama -v
Remove-Item Env:SHORTLIST_TEST_LIVE
```

Leave `LLM_PROVIDER=ollama` and `DATABASE_URL` blank for local SQLite. The API token is optional on loopback and required for Groq mode.

## Try Groq locally

1. Create a [GroqCloud](https://console.groq.com/) account and keep your organization on Free. Create a key in the console. Confirm that `openai/gpt-oss-120b` is available to your organization using the [models list API](https://console.groq.com/docs/api-reference#models-list) and check the organization Limits page. This model is listed on the Free tier and supports structured output. Shortlist requests JSON Object Mode and also validates model output in Python.
2. Set `LLM_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_MODEL=openai/gpt-oss-120b`, and `SHORTLIST_API_TOKEN` in `.env`. Generate the shared token locally with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Keep `DATABASE_URL` blank to use SQLite, or point it at a separate test database.
3. Restart both processes. Create a synthetic job, edit the rubric, upload a synthetic text-based PDF and refresh rankings. Check the per-file results and the criterion explanations. The health endpoint only confirms application startup.

## Database on Neon Free

Create a Free project after deployment approval. In the Neon connection dialog, copy a pooled PostgreSQL URL and keep its TLS settings. Use it as `DATABASE_URL` on Render. Shortlist creates missing tables on startup, with an application pool of two connections plus one overflow connection. A new Neon project starts with an empty dataset. Render SQLite files are ephemeral across restarts and deployments.

Local data remains in `data/app.db`. For a demo, recreate synthetic jobs through the UI. To migrate an authorized existing dataset later, stop writers, back up SQLite, and import into a separate empty staging PostgreSQL database. Preserve IDs and timestamps and load `jobs`, then `resumes`, then `scores` in one transaction. Reset PostgreSQL sequences past the highest imported IDs, verify table counts and known fractional scores and compare rankings through the API before changing the production URL. Keep the SQLite backup for rollback. There is no automatic transfer or destructive schema migration. Existing manually created PostgreSQL tables with integer score columns would require a reviewed column migration to preserve fractional scores.

## Render settings

After push and deployment approval, connect GitHub and select this repository and the `feature/free-cloud-deployment` branch. Use the root `render.yaml` Blueprint or a manual **Free** Python web service with these settings:

| Setting | Value |
| --- | --- |
| Root directory | Repository root (leave blank) |
| Python | `PYTHON_VERSION=3.13.7` |
| Build command | `python -m pip install -r backend/requirements-render.txt` |
| Start command | `python -m uvicorn main:app --app-dir backend --host 0.0.0.0 --port $PORT --workers 1 --no-access-log --limit-concurrency 10` |
| Health check | `/health` |
| Environment | `LLM_PROVIDER=groq`, `GROQ_TIMEOUT=35`, `GROQ_MODEL`, `GROQ_API_KEY`, `DATABASE_URL`, `SHORTLIST_API_TOKEN` |

Keep the Render workspace without a payment method. Open the HTTPS `/health` URL and check for `{"status":"ok"}`. Verify an unauthenticated request to `/jobs/1/rankings` gets HTTP 401.

## Streamlit Community Cloud settings

Connect GitHub. Select the same repository and branch. Use `frontend/app.py` as the entry point and choose Python 3.13 in Advanced settings. Community Cloud discovers `frontend/requirements.txt` next to the entry point. Add these values to app Secrets:

```toml
SHORTLIST_API_URL = "https://YOUR-SERVICE.onrender.com"
SHORTLIST_API_TOKEN = "SAME_TOKEN_AS_RENDER"
```

Use a private GitHub repository so the app starts private. Confirm its private sharing setting before providing credentials or inviting viewers. Invite individual reviewers by email and verify in a signed-out window that the app requires sign-in. Signed-in viewers share one demo workspace and can exercise the same API access. Use the Render URL over HTTPS. The Groq and database credentials belong only on Render. Environment variables take precedence over Streamlit secrets.

Follow the five existing pages and run the synthetic workflow. Change a criterion weight after screening and confirm the stale-rankings warning appears. Session state survives in-session reruns and navigation. A full browser reload starts a new Streamlit session. A stale ranking can still include earlier scores until a fresh job is created.

## Data handling and troubleshooting

- Groq receives job descriptions, extracted resume text and structured profiles. Render processes PDFs and Neon stores extracted text, structured profiles and scores. Use synthetic data in the demo. Consult [Groq data controls](https://console.groq.com/docs/your-data) before any separate approved use of personal data. Human reviewers must verify evidence against the original PDF and make hiring decisions.
- Render can take about a minute to wake. Visit `/health`, wait for a successful response, and retry the operation once. Check for identical API tokens if the app receives HTTP 401.
- Groq credential or model errors require checking the secret, organization and model availability. HTTP 429 means check organization limits and wait. Long `Retry-After` intervals return immediately to the user. Invalid JSON or schema errors are retried up to three total generation attempts.
- Use text-based PDFs, up to 5 MiB and 30 pages each, within a 16 MiB request. Cloud batches allow up to three PDFs, and job descriptions and extracted resume text each allow up to 12,000 characters. Context and token limits can still require smaller inputs. Submit one file at a time if timeouts or rate limits recur. Check rankings before retrying timed-out submissions.
- For database startup failures, check the Neon project status, URL, TLS options, credentials and quotas. Check the logs for safe error categories. Local workflow and previous development logs may still contain sensitive data and should stay off GitHub.
