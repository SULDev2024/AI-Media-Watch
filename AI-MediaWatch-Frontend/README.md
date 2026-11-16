# AI Media Watch application

This directory contains the AIMW Python API, database migrations, workers,
React dashboard, collection tools and tests. It is part of the repository,
not a separate frontend-only project.

Use the [root README](../README.md) for Windows setup, separate Python
environments, model downloads, ports and tests. Copy this directory's
`.env.example` to `.env` and replace placeholders before starting.

Run `start_demo.ps1` from this directory after setup. The dashboard uses
port 5174, AIMW API 8003, Local Agent 8002 and Ollama 11434.
No Docker stack is supplied or required for eager mode.

The analytics pages are implemented features, not proof of measured
accuracy. Private datasets and old evaluation outputs are excluded.
