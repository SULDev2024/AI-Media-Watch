# Local Agent connection

This installation uses separate ports because other projects already occupy
8000, 8001 and 5173:

Browser :5174 -> AIMW API :8003 -> Local Agent :8002 -> Ollama :11434

## Start

From this folder in PowerShell:

```powershell
.\start_demo.ps1
```

Keep that terminal open. The launcher starts missing services and leaves
existing services alone. Ctrl+C stops only processes it started.
Open http://localhost:5174 and log in using the account configured in `.env`:
Use the email/password you set in `.env`. See the root README for fresh setup.

The first API startup applies the packaged migrations to a NEW local database
at `data/aimw.db`. This is not the missing historical 380-video research database.

## Setup on another computer

The Local Agent needs a Python 3.12 `venv` and FFmpeg (setup is in the root
README). AIMW needs Python 3.11
and its own `.venv`; do not install its dependencies into Local Agent's venv.

```powershell
uv sync
cd web
npm install
cd ..
```

If uv is not on PATH, this machine also has `.\.bootstrap\Scripts\uv.exe`.
Configure `.env` using the settings below (no Groq account required):

```env
AIMW_EAGER=1
AIMW_FAST_ANALYSIS=0
AIMW_AUTO_PURGE_CLEAN=false
AIMW_GPU_PIPELINE_URL=http://127.0.0.1:8002
AIMW_GPU_PIPELINE_TIMEOUT_S=900
AIMW_API_PORT=8003
AIMW_LLM_PROVIDER=local
AIMW_LLM_BASE_URL=http://127.0.0.1:11434/v1
AIMW_LLM_MODEL=qwen2.5vl:latest
AIMW_LLM_REQUIRE_AUTH=false
```

## Behavior

- Uploaded videos and images are sent once to Local Agent. AIMW does not load
  another Whisper model for the same media.
- Page links are downloaded by AIMW using yt-dlp, then uploaded to Local Agent.
  Private/login-restricted or unavailable media can still fail; such failures
  are displayed, never scored CLEAN. Platform credentials/cookies may be needed.
- Pasted text uses AIMW's local Ollama judge directly.
- Backend risk score, rationale, flags and transcript populate the saved report.
  EasyOCR provides recognized text, boxes, confidence and sampled-frame times
  to the OCR tab. The bridge does not supply speech word timestamps.
- Invalid model output, connection errors and timeouts produce failed results.
- Automatic deletion is disabled by default, including for new research data.
- Collectors and corpus rerun scripts are not started by this launcher.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_local_agent_integration.py -q
cd web
npm run build
```
