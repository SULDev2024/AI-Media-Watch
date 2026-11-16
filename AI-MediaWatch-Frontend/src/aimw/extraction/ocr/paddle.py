"""PaddleOCR wrapper with PaddleOCR-VL → PaddleOCR-3.x fallback.

Engine selection at construction time:

1. Try ``from paddleocr import PaddleOCRVL`` (the 0.9B Cyrillic-strong VLM
   recommended by §5 of the architecture). On success, ``engine == "paddle_vl"``.
2. Fall back to ``from paddleocr import PaddleOCR`` (the classic 3.x detector +
   recognizer). On success, ``engine == "paddle_3"``.
3. If neither imports, raise :class:`OcrEngineUnavailable` — the caller decides
   whether to skip (slow tests) or fail (production worker).

PaddleOCR + paddlepaddle is in the optional ``ocr`` extra because its
~800 MB install footprint and brittle Windows wheel resolution make it a
no-go for default CI. Install locally with ``uv sync --extra ocr``; the fast
tests mock this wrapper so the suite stays green without it.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

from aimw.core.logging import get_logger
from aimw.extraction.ocr.models import OcrBlock

log = get_logger("aimw.extraction.ocr.paddle")

EngineName = Literal["paddle_vl", "paddle_3"]


class OcrEngineUnavailable(RuntimeError):
    """Neither PaddleOCR-VL nor classic PaddleOCR could be imported."""


def _bbox_from_quad(quad: Any) -> tuple[int, int, int, int]:
    """Reduce PaddleOCR's 4-point polygon to an axis-aligned bbox.

    PaddleOCR returns polygons as either ``[[x0,y0],[x1,y1],[x2,y2],[x3,y3]]``
    or numpy arrays of the same shape. We collapse to ``(x_min, y_min, x_max, y_max)``
    since the downstream consumer (Phase 7) cares about position, not orientation.
    """
    xs = [round(float(p[0])) for p in quad]
    ys = [round(float(p[1])) for p in quad]
    return (min(xs), min(ys), max(xs), max(ys))


class OcrEngine:
    """Lazy wrapper around PaddleOCR (VL preferred, 3.x fallback).

    When using the classic paddle_3 engine, runs two recognition passes:
    one with the Cyrillic model (ru) and one with the English model (en),
    then deduplicates by bounding-box overlap so logos and captions in any
    Latin or Cyrillic script are captured.
    """

    def __init__(self, requested: EngineName = "paddle_vl", *, lang: str = "ru") -> None:
        self._requested: EngineName = requested
        self._lang = lang
        self._engine_name: EngineName | None = None
        self._impl: Any | None = None
        self._impl_en: Any | None = None  # second-pass English model (classic only)
        self._engine_version: str = _paddle_version()

    @property
    def engine(self) -> EngineName:
        if self._engine_name is None:
            self._load()
        assert self._engine_name is not None
        return self._engine_name

    @property
    def engine_version(self) -> str:
        return self._engine_version

    def _load(self) -> None:
        if self._impl is not None:
            return
        # NB: ``A or B`` would not work here — ``(None, None)`` is a *truthy*
        # tuple in Python, so a failed first attempt would not fall through.
        loaders = (
            (self._try_load_vl, self._try_load_classic)
            if self._requested == "paddle_vl"
            else (self._try_load_classic, self._try_load_vl)
        )
        for loader in loaders:
            impl, name = loader()
            if impl is not None:
                self._impl, self._engine_name = impl, name
                log.info(
                    "ocr_engine_loaded", engine=self._engine_name, version=self._engine_version
                )
                # For classic engine: load English model as a second pass so
                # Latin logos and English on-screen text are also recognised.
                if name == "paddle_3" and self._lang != "en":
                    en_impl, _ = self._try_load_classic_lang("en")
                    if en_impl is not None:
                        self._impl_en = en_impl
                        log.info("ocr_engine_en_loaded", version=self._engine_version)
                return
        raise OcrEngineUnavailable(
            "neither PaddleOCRVL nor PaddleOCR could be imported; "
            "install with `uv sync --extra ocr`"
        )

    def _try_load_vl(self) -> tuple[Any, EngineName] | tuple[None, None]:
        try:
            from paddleocr import PaddleOCRVL  # type: ignore[attr-defined]
        except ImportError as exc:
            log.debug("paddle_vl_unavailable", error=str(exc))
            return (None, None)
        try:
            # PaddleOCRVL 3.7+ is a document pipeline; no lang= param (multilingual).
            return (PaddleOCRVL(enable_mkldnn=False), "paddle_vl")
        except Exception as exc:
            # VL class exists but construction failed (e.g. weights download
            # blocked, GPU init failure). Let the classic path try next.
            log.warning("paddle_vl_construct_failed", error=str(exc))
            return (None, None)

    def _try_load_classic_lang(self, lang: str) -> tuple[Any, EngineName] | tuple[None, None]:
        """Load a classic PaddleOCR instance with a specific language."""
        try:
            from paddleocr import PaddleOCR
            try:
                return (
                    PaddleOCR(
                        lang=lang,
                        use_textline_orientation=True,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        enable_mkldnn=False,
                    ),
                    "paddle_3",
                )
            except TypeError:
                return (PaddleOCR(lang=lang, enable_mkldnn=False), "paddle_3")
        except Exception as exc:
            log.debug("paddle_3_lang_load_failed", lang=lang, error=str(exc))
            return (None, None)

    def _try_load_classic(self) -> tuple[Any, EngineName] | tuple[None, None]:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            log.debug("paddle_3_unavailable", error=str(exc))
            return (None, None)
        try:
            # enable_mkldnn=False avoids a PIR/oneDNN NotImplementedError on
            # Windows (paddlepaddle 3.3 + oneDNN executor bug on certain attrs).
            # use_doc_orientation_classify/use_doc_unwarping disabled: video
            # frames don't need document pre-processing; disabling saves ~2s/call.
            return (
                PaddleOCR(
                    lang=self._lang,
                    use_textline_orientation=True,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    enable_mkldnn=False,
                ),
                "paddle_3",
            )
        except TypeError:
            # Older 3.x builds may not support some params; retry with minimal args.
            try:
                return (PaddleOCR(lang=self._lang, enable_mkldnn=False), "paddle_3")
            except Exception as exc2:
                log.warning("paddle_3_construct_failed", error=str(exc2))
                return (None, None)
        except Exception as exc:
            log.warning("paddle_3_construct_failed", error=str(exc))
            return (None, None)

    def recognize(self, image_path: Path) -> list[OcrBlock]:
        """Recognize all text blocks in ``image_path`` and return them normalized.

        Runs the primary model (Cyrillic/ru) then merges results from the
        English model (en), deduplicating boxes that overlap >50% and keeping
        whichever read has higher confidence. This captures both Cyrillic text
        and Latin logos/captions in a single pass.
        """
        self._load()
        # PaddleOCR 3.7+: .ocr() is deprecated; both VL and classic use .predict().
        raw = list(self._impl.predict(str(image_path)))  # type: ignore[union-attr]
        blocks = _normalize(raw)

        if self._impl_en is not None:
            raw_en = list(self._impl_en.predict(str(image_path)))
            blocks_en = _normalize(raw_en)
            blocks = _merge_blocks(blocks, blocks_en)

        return blocks


def _iou(a: tuple[int,int,int,int], b: tuple[int,int,int,int]) -> float:
    """Intersection-over-union of two axis-aligned bboxes."""
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / (area_a + area_b - inter)


def _merge_blocks(primary: list[OcrBlock], secondary: list[OcrBlock]) -> list[OcrBlock]:
    """Merge two OCR result lists, deduplicating by bounding-box overlap.

    For each block in ``secondary``: if it overlaps an existing block by >50%
    IoU, keep whichever has higher confidence. Otherwise add it (new detection
    from the second-language pass).
    """
    result = list(primary)
    for s in secondary:
        best_iou, best_idx = 0.0, -1
        for i, r in enumerate(result):
            iou = _iou(r.bbox, s.bbox)
            if iou > best_iou:
                best_iou, best_idx = iou, i
        if best_iou > 0.5:
            if s.confidence > result[best_idx].confidence:
                result[best_idx] = s
        else:
            result.append(s)
    return result


def _paddle_version() -> str:
    try:
        return version("paddleocr")
    except PackageNotFoundError:
        return "unknown"


def _normalize(raw: Any) -> list[OcrBlock]:
    """Normalize PaddleOCR's return shape into a flat list of :class:`OcrBlock`.

    Handles four known return shapes:

    1. ``[[ [polygon, (text, confidence)], ... ]]`` — classic PaddleOCR ≤2.x
    2. ``[{"rec_texts": [...], "rec_scores": [...], "dt_polys": [...]}]`` — new
       PaddleOCR 3.7+ ``.ocr()`` (list of per-image dicts)
    3. ``{"rec_texts": [...], "rec_scores": [...], "dt_polys": [...]}`` — single
       dict (VL predict() result objects after iteration, or classic 3.x predict())
    4. ``[ [polygon, (text, confidence)], ... ]`` — older mixed flat list
    """
    blocks: list[OcrBlock] = []
    if raw is None:
        return blocks

    # PaddleOCR 3.7+: ocr() returns list of per-image dicts.
    # Unwrap to the first dict then fall through to dict handling.
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        raw = raw[0]

    # Dict shape: VL predict result objects and new classic 3.7 format.
    if isinstance(raw, dict):
        texts = raw.get("rec_texts") or raw.get("texts") or []
        scores = raw.get("rec_scores") or raw.get("scores") or []
        polys = (
            raw.get("rec_polys")
            or raw.get("dt_polys")
            or raw.get("polys")
            or raw.get("boxes")
            or []
        )
        for text, score, poly in zip(texts, scores, polys, strict=False):
            blocks.append(
                OcrBlock(text=str(text), bbox=_bbox_from_quad(poly), confidence=float(score))
            )
        return blocks

    # Classic PaddleOCR ≤2.x: outer list is per-image; always one image.
    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        items = raw[0]
        for item in items or []:
            block = _block_from_pair(item)
            if block is not None:
                blocks.append(block)
        return blocks

    # Older mixed flat list carrying [polygon, (text, confidence)] pairs.
    if isinstance(raw, list):
        for item in raw:
            block = _block_from_pair(item)
            if block is not None:
                blocks.append(block)
    return blocks


def _block_from_pair(item: Any) -> OcrBlock | None:
    """Best-effort parse of a ``[polygon, (text, confidence)]`` PaddleOCR row."""
    try:
        polygon, payload = item[0], item[1]
        if isinstance(payload, (list, tuple)) and len(payload) >= 2:
            text, confidence = payload[0], payload[1]
        else:
            text, confidence = str(payload), 1.0
        return OcrBlock(text=str(text), bbox=_bbox_from_quad(polygon), confidence=float(confidence))
    except (TypeError, IndexError, ValueError):
        return None
