"""Shared Typer group for extraction subcommands (``aimw extract ...``).

Each extraction subsystem registers its own commands on ``extract_app``. The
top-level CLI mounts this group; subsystems don't need to know each other.
"""

from __future__ import annotations

import typer

from aimw.extraction.ocr.cli import register as _register_ocr
from aimw.extraction.whisper.cli import register as _register_whisper

extract_app = typer.Typer(
    help="Extraction: transcribe (Phase 5) and OCR (Phase 6).",
    no_args_is_help=True,
)

_register_whisper(extract_app)
_register_ocr(extract_app)
