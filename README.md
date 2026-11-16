# AI Media Watch

AI Media Watch is a university project for reviewing possible scam and financial-fraud signals in submitted text, images and videos. It combines local speech transcription, OCR, vision analysis and language models, then presents a risk assessment and supporting evidence in a React dashboard. Results require human review; they are not proof that a person or organization committed fraud.

## Implemented features

- Manual text, image and video submission; URL ingestion through the application's downloader where the platform permits access.
- Speech transcription using faster-whisper.
- English OCR with EasyOCR for uploaded images and sampled video frames. Recognized text is saved separately from rule-matched risk signals and displayed in the OCR tab.
- Three local Ollama analysis roles: speech analysis, visual analysis and final risk assessment.
- Saved evidence packages, reports, transcript display, entity extraction, queue and graph views.
- Additional collection, feedback, validation and investigation modules in the source. Optional integrations require their own configuration and dependencies; their presence is not a claim that every integration has been tested.

## Architecture and source map

```text
React dashboard :5174
  -> AIMW FastAPI API :8003
     -> saved media + eager background worker + SQLite
        -> Local Agent FastAPI :8002
           -> FFmpeg -> Whisper small (speech)
           -> OpenCV sampled RGB frames -> EasyOCR (text)
           -> Ollama :11434
              Mistral speech analysis + Qwen visual analysis
              -> Llama 3 auditor
        -> OCR artifact, transcript, risk verdict, evidence and report
  <- dashboard polls saved results
```

| Path | Role |
| --- | --- |
| `main.py` | Local Agent API: `/health`, multipart `/analyze`, direct-media `/analyze-url` |
| `audio_engine.py` | FFmpeg extraction and CPU/int8 Whisper; videos without audio return an empty transcript |
| `vision_engine.py` | OpenCV frame sampling, EasyOCR on CPU and informative-frame selection |
| `agents.py`, `visual_evidence.py`, `cache.py` | Active model calls, visual evidence budgeting and SQLite result cache |
| `requirements-local-agent.txt` | Local Agent direct dependencies; separate from the AIMW environment |
| `AI-MediaWatch-Frontend/src/aimw` | API, workers, packaged Alembic migrations, scoring, entities, reasoning, reports and collection |
| `AI-MediaWatch-Frontend/web` | React 18, TypeScript, Vite 5, Tailwind, TanStack Query, Recharts and Cytoscape |
| `AI-MediaWatch-Frontend/pyproject.toml`, `uv.lock` | Python 3.11 AIMW dependency definition and lockfile |
| `AI-MediaWatch-Frontend/config` | Signal, regulation and threshold configuration |
| `AI-MediaWatch-Frontend/start_api.py`, `start_demo.ps1` | Apply migrations and start the supported Windows demo |
| `extension/` and `AI-MediaWatch-Frontend/extension/` | Browser extension source; review its configured endpoints before use |
| `*_v3*.py`, evaluation scripts and tests | Research variants and evaluation tooling; not the active launcher path |
| `streamlit_app.py`, `cli_analyze.py` | Legacy interfaces with different processing behavior; not the supported demo path |

The AIMW backend uses FastAPI, Pydantic, SQLAlchemy, SQLite and Alembic. Celery/Redis are available for a separate worker configuration; the documented eager demo does not require Redis or Docker.

## Local AI models

| Component | Exact active model/engine | Role |
| --- | --- | --- |
| Ollama speech analyst | `mistral:latest` | Analyze speech transcript |
| Ollama vision analyst | `qwen2.5vl:latest` | Describe relevant evidence in selected frames |
| Ollama auditor | `llama3:latest` | Return risk score, reasoning and flags |
| faster-whisper | `small` | CPU/int8 transcription in the Local Agent |
| EasyOCR | English detector/recognizer | Read visible text, returning boxes and confidence |

These names come from the active modules. The AIMW fallback extraction path has different optional models; installing those is unnecessary for the documented Local Agent path. The `latest` Ollama tags are mutable: record your installed model digests when reporting an evaluation.

## Windows installation

Use PowerShell from the repository root. Install Git, Python **3.12** for Local Agent, Python **3.11** for AIMW, Node.js with npm, FFmpeg (including ffprobe), Ollama and the `uv` package manager. If the Python launcher is unavailable, use the full path to the corresponding interpreter.

Verify prerequisites:

```powershell
git --version
py -3.12 --version
py -3.11 --version
node --version
npm --version
ffmpeg -version
ffprobe -version
ollama --version
uv --version
```

Node package requirements are recorded in `web/package.json` and `package-lock.json`. A specific minimum Node version is not declared by this project; use a version compatible with its locked Vite dependencies.

### 1. Create the Local Agent environment

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.\venv\Scripts\python.exe -m pip install -r requirements-local-agent.txt
.\venv\Scripts\python.exe -m pip check
```

Direct dependencies are pinned to versions observed on the working machine, except the torch/torchvision pair. Install a mutually compatible pair from the CPU index; this is not a fully locked transitive environment. The observed pair was torch 2.15.0+cpu / torchvision 0.29.2+cpu. A fresh Windows installation has not been certified. Keep PyAV 18.1.0 with faster-whisper 1.2.1 as specified in `requirements-audio-compat.txt`.

### 2. Install AIMW and the dashboard separately

```powershell
Set-Location AI-MediaWatch-Frontend
uv sync --locked
Copy-Item .env.example .env
Set-Location web
npm ci
Set-Location ..
```

Edit `AI-MediaWatch-Frontend/.env` before launching. Replace the admin password and JWT secret placeholders with private values. The template uses local Ollama, eager mode, API port 8003 and Local Agent port 8002. Leave optional cloud/Telegram integrations unset for local uploads. Your real `.env` must never be committed.

The launcher still prints historical demonstration credentials; use your actual configured account instead. Existing databases retain their existing accounts. Changing the template does not reset an account in an existing database.

The root `.env.example` only documents `OLLAMA_HOST`. The Local Agent does not load that file automatically. Its default is localhost:11434; to override it in the terminal that starts Local Agent:

```powershell
$env:OLLAMA_HOST = 'http://127.0.0.1:11434'
```

### 3. Download models separately

In a terminal with Ollama installed:

```powershell
ollama pull mistral:latest
ollama pull qwen2.5vl:latest
ollama pull llama3:latest
ollama list
```

From the repository root, download/cache Whisper and EasyOCR weights through their existing initialization functions:

```powershell
.\venv\Scripts\python.exe -c "from audio_engine import preload; preload()"
.\venv\Scripts\python.exe -c "from vision_engine import get_reader; get_reader()"
```

These commands can download large files and load models into memory. Ollama stores models in its own configured model directory (normally under the user profile); Whisper uses the Hugging Face cache and EasyOCR normally uses `~/.EasyOCR/model`. None belong in Git. Provision models while online before attempting an offline demo.

### 4. Start the application

Start Ollama, or leave its desktop service running. If it is not running:

```powershell
ollama serve
```

In another terminal, from the repository root:

```powershell
Set-Location AI-MediaWatch-Frontend
.\start_demo.ps1
```

If PowerShell blocks the reviewed local script, use a process-scoped policy:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start_demo.ps1
```

Open `http://127.0.0.1:5174` and use your configured login. Keep the terminal open. The launcher starts missing services only, waits for them, and stops only processes it started when closed. It does not restart already-running services after code changes.

For manual startup, use separate terminals:

```powershell
# Terminal 1, repository root
.\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8002

# Terminal 2, repository root
Set-Location AI-MediaWatch-Frontend
.\.venv\Scripts\python.exe start_api.py

# Terminal 3, repository root
Set-Location AI-MediaWatch-Frontend/web
npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Vite proxies `/api` to 8003. API startup creates local storage and applies packaged database migrations; no private database is needed. Directly running `python main.py` uses a different bind/port, so use the command above.

## OCR, speech and video workflow

Uploaded images are loaded with EXIF orientation correction. Videos are sampled approximately every two seconds, resized to a maximum height of 480 pixels, and transcribed with Whisper. Audio-free videos continue to frame analysis. EasyOCR reads the sampled frames; the results retain recognized text, bounding boxes, confidence and sample timestamps. The dashboard shows recognized OCR text, including text that matches no risk rule. OCR is currently English-only in this path.

The vision analyst receives up to three informative frames. Speech and visual reports feed the auditor; the returned assessment, transcript and OCR are passed to AIMW and saved. Existing cached model assessments can be enriched with OCR without rerunning the auditor. Risk thresholds in the bridge are 60 for HIGH, 40 for MEDIUM and 15 for LOW; these are implementation thresholds, not calibrated probabilities.

## Verification and tests

Health checks only establish API/database readiness, not successful model inference:

```powershell
Invoke-RestMethod http://127.0.0.1:8002/health
Invoke-RestMethod http://127.0.0.1:8003/health/ready
```

Run focused local checks from the repository root:

```powershell
.\venv\Scripts\python.exe -m unittest test_audio_compat test_silent_video -v
Set-Location AI-MediaWatch-Frontend
uv run --locked pytest tests/test_local_agent_integration.py -q
Set-Location web
npm run build
```

Do not run blanket root test discovery for an offline smoke test: some older scripts load models, access private media or make network calls at import/run time. Corpus evaluation requires separately authorized private data and labels, deliberately absent from Git. Tests referencing those files cannot establish performance on a clean clone.

For the real demo, upload an image containing clearly readable English text, then a video with speech and a video without audio. Confirm the OCR tab, transcript, final report, saved result after refresh and visible failure behavior. CPU inference can take minutes and can exceed the configured timeout. Check the API logs when a request fails.

## Requirements and limitations

- Use a 64-bit Windows machine with enough RAM and disk for Python environments, three Ollama models and processing artifacts. There is no measured minimum RAM/VRAM specification or validated latency guarantee in this repository. The active Whisper and OCR paths run on CPU; Qwen vision explicitly requests CPU inference.
- Initial package/model downloads need internet. Local uploads can use local inference afterward; platform URLs still need network access and may fail because of access restrictions, cookies or downloader changes.
- Some UI-advertised platforms are not accepted by every URL-validation path. Prefer local uploads for a controlled demonstration.
- OCR can misread small/stylized text; sparse frame sampling can miss brief overlays. Transcript and model evidence are truncated, and the auditor can return invalid JSON.
- Scores and displayed confidence are not calibrated probabilities. Existing metrics code includes a prediction self-comparison fallback; do not use that page as evidence of accuracy. No accuracy/F1 claim is made here.
- Authentication includes development stubs/defaults. Treat this as a local academic demo. Do not expose it to the public internet without fixing and testing authentication, authorization, secret handling and upload/download limits.
- Alternative research versions, legacy CLI/Streamlit interfaces and optional PaddleOCR/VLM modules differ from the supported path. The local launcher does not run corpus collectors or send deliberate alerts as a setup step; configure integrations carefully.
- Research datasets, reviewer packages, model weights and old results are private/local artifacts and are excluded. Their absence is intentional.

## What belongs in Git

Source code, migrations, tests, configuration templates, `requirements*.txt`, `pyproject.toml`, `uv.lock`, `package.json` and `package-lock.json` belong in Git. Models, environments, `node_modules`, uploads, databases, cookies, sessions, actual `.env`, datasets, logs, generated builds and reviewer run artifacts do not.

For a file that was previously tracked, `git rm --cached -- path` stops tracking while retaining the local file. It does **not** remove older copies from history. This submission is prepared on an independent clean-root branch so the old tracked videos are not included in the new repository's history. The original local `master` history and its existing `origin` remain intact.

Before future commits, review:

```powershell
git status --short
git diff --cached --stat
git diff --cached
```

Stage only intended source/documentation changes, inspect them for secrets and commit them. Use the submission remote/branch recorded in the preparation report. Pushing publishes code and must be done deliberately. No force push is required.
