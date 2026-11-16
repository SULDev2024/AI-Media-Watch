"""Qwen3-VL wrapper for targeted in-image text recovery (§5, §0.2 issue #12).

Architecture constraints from §0.2 issue #12:
* Vision can **corroborate** — never **originate** STRONG evidence.
* VLM is invoked only on frames that already had OCR hits (or scene-change
  keyframes). The extractor enforces the call policy; this wrapper is stateless.
* ``is_available()`` returns False when the extra is not installed or the model
  fails to load, and ``recover_in_image_text()`` returns an empty list.
  The extractor caller must check ``is_available()`` before invoking.

Install: ``uv sync --extra vlm`` (pulls transformers + torch + accelerate).
The 4B model requires ~8–10 GB VRAM or ~32 GB RAM for CPU inference.
A 2B fallback model is attempted if the 4B load fails.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aimw.core.config import get_settings
from aimw.core.logging import get_logger

log = get_logger("aimw.entities.vlm.qwen")

_RECOVERY_PROMPT = (
    "List all text visible in this image exactly as it appears, one item per line. "
    "Be precise and verbatim. Do not interpret or translate."
)

_FALLBACK_MODEL = "Qwen/Qwen2.5-VL-2B-Instruct"


class QwenWrapper:
    """Lazy Qwen3-VL wrapper for in-image text recovery.

    Thread-safety: not thread-safe. The extractor holds one wrapper per
    process and calls it synchronously from ``asyncio.to_thread``.
    """

    def __init__(self) -> None:
        self._model: Any | None = None
        self._processor: Any | None = None
        self._available: bool | None = None

    def is_available(self) -> bool:
        """Return True if the model is loaded and ready."""
        if self._available is None:
            self._available = self._try_load()
        return self._available

    def _try_load(self) -> bool:
        settings = get_settings()
        if not settings.vlm_enabled:
            log.debug("vlm_disabled_by_config")
            return False
        try:
            import torch
            from transformers import (
                AutoProcessor,
                Qwen2_5VLForConditionalGeneration,
            )
        except ImportError:
            log.debug("vlm_dependencies_not_installed", hint="uv sync --extra vlm")
            return False

        primary = settings.vlm_model
        for model_name in (primary, _FALLBACK_MODEL):
            try:
                log.info("vlm_loading", model=model_name)
                self._processor = AutoProcessor.from_pretrained(model_name)
                device = _resolve_device(settings.vlm_device)
                dtype = torch.float16 if device == "cuda" else torch.float32
                self._model = Qwen2_5VLForConditionalGeneration.from_pretrained(
                    model_name,
                    torch_dtype=dtype,
                    device_map=device,
                )
                log.info("vlm_loaded", model=model_name, device=device)
                return True
            except Exception as exc:
                log.warning("vlm_load_failed", model=model_name, error=str(exc))
        return False

    def recover_in_image_text(self, image_path: Path) -> list[str]:
        """Ask the VLM to list all on-screen text in *image_path*.

        Returns an empty list if the model is unavailable or inference fails.
        Results are raw text lines; the caller re-runs patterns over them.
        """
        if not self.is_available():
            return []
        # is_available() returned True → both _processor and _model are loaded.
        assert self._processor is not None
        assert self._model is not None
        try:
            import torch
            from PIL import Image

            image = Image.open(image_path).convert("RGB")
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": _RECOVERY_PROMPT},
                    ],
                }
            ]
            inputs = self._processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
                tokenize=True,
            )
            with torch.inference_mode():
                output_ids = self._model.generate(**inputs, max_new_tokens=256)
            input_len = inputs["input_ids"].shape[1]
            generated = self._processor.decode(output_ids[0][input_len:], skip_special_tokens=True)
            lines = [ln.strip() for ln in generated.splitlines() if ln.strip()]
            log.debug("vlm_recovered", image=str(image_path), line_count=len(lines))
            return lines
        except Exception as exc:
            log.error("vlm_inference_failed", image=str(image_path), error=str(exc))
            return []


def _resolve_device(setting: str) -> str:
    """Resolve 'auto' to 'cuda' or 'cpu' based on availability."""
    if setting == "cpu":
        return "cpu"
    if setting == "cuda":
        return "cuda"
    # auto
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


# Process-wide singleton — reset in tests via reset_qwen().
_WRAPPER: QwenWrapper | None = None


def get_qwen() -> QwenWrapper:
    """Return the process-wide :class:`QwenWrapper`, building it on first use."""
    global _WRAPPER
    if _WRAPPER is None:
        _WRAPPER = QwenWrapper()
    return _WRAPPER


def reset_qwen() -> None:
    """Drop the singleton (test isolation)."""
    global _WRAPPER
    _WRAPPER = None
