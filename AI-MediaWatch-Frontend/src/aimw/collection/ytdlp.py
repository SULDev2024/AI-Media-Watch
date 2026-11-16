"""yt-dlp wrapper — downloads a single ≤720p clip and returns raw metadata.

Side-effect only (constraint #5): emits a raw media file + metadata. It never
reads the evidence schema and assumes nothing about the DB beyond what the
caller does with the returned artifact.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any, NamedTuple
from threading import Event

from aimw.core.logging import get_logger

log = get_logger("aimw.collection.ytdlp")

# Cap at 360p for fast download — analysis only needs audio (Whisper) and a
# few key frames (Vision LLM). 360p is ~4x smaller than 720p with no accuracy
# loss. AV1 (av01) is still excluded: OpenCV can't decode it.
_FORMAT = (
    "bv*[height<=360][vcodec^=avc1]+ba"   # h264 360p (fastest merge path)
    "/bv*[height<=360][vcodec^=vp9]+ba"   # vp9 360p
    "/bv*[height<=360][vcodec!^=av01]+ba" # anything <=360p except AV1
    "/b[height<=360]"                      # single-stream <=360p
    "/b[height<=480]"                      # up to 480p fallback
    "/b"                                    # any single progressive stream
    "/best"                                # absolute fallback (TikTok/IG/etc.)
)
_CHUNK = 1 << 20


class DownloadedMedia(NamedTuple):
    """Raw artifact returned by :func:`download` (no evidence semantics)."""

    path: Path
    duration_s: float | None
    width: int | None
    height: int | None
    title: str | None
    description: str | None
    uploader: str | None
    video_id: str


def _ffmpeg_dir() -> str | None:
    """Return a directory containing an ``ffmpeg`` binary for yt-dlp to merge with.

    Prefers a system ffmpeg on PATH; otherwise falls back to the static binary
    bundled by the optional ``imageio-ffmpeg`` package. yt-dlp needs ffmpeg to
    merge the separate video+audio streams YouTube serves; without it every
    multi-format download aborts. yt-dlp only recognises a binary named
    ``ffmpeg``/``ffmpeg.exe``, so the imageio binary (named
    ``ffmpeg-win-...exe``) is copied once into a cache dir under that name.
    Returns None if neither is available (yt-dlp then handles only single-stream
    progressive formats).
    """
    if shutil.which("ffmpeg"):
        return None  # on PATH already; let yt-dlp find it
    try:
        import imageio_ffmpeg

        src = Path(imageio_ffmpeg.get_ffmpeg_exe())
        ext = src.suffix  # ".exe" on Windows, "" elsewhere
        cache_dir = Path(tempfile.gettempdir()) / "aimw_ffmpeg"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / f"ffmpeg{ext}"
        if not target.exists() or target.stat().st_size != src.stat().st_size:
            shutil.copy2(src, target)
        return str(cache_dir)
    except Exception:
        return None


def _sha16(path: Path) -> str:
    """Content hash (first 16 hex chars of SHA-256) used as the video id."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class MediaTooLong(RuntimeError):
    """Raised when a video exceeds the caller's ``max_duration_s`` cap."""


def download(
    url: str, dest_dir: Path, *, max_duration_s: float | None = None,
    cancel_event: Event | None = None,
) -> DownloadedMedia:
    """Download ``url`` to ``dest_dir/<video_id>.mp4`` and return its metadata.

    The video id is ``sha256(file_bytes)[:16]`` so identical content dedupes.
    Raises on download failure; callers are responsible for not crashing loops.

    ``max_duration_s`` (optional): reject videos longer than this BEFORE the
    media bytes are fetched, via yt-dlp's ``match_filter``. Bulk collection sets
    a cap (scam promos are short) so a stray multi-hour stream can't stall the
    crawl; the default ``None`` preserves the unbounded behaviour other callers
    rely on. Rejected videos raise :class:`MediaTooLong`.
    """
    import os

    import yt_dlp  # lazy import: keeps module import cheap and degradation graceful

    # Clip cap: only download the first AIMW_CLIP_SECONDS seconds (default 300 = 5 min).
    # Scam signals appear in the opening minutes; trimming the tail saves 80%+ of
    # download and transcription time for long videos.
    _clip_s = int(os.environ.get("AIMW_CLIP_SECONDS", "300"))

    dest_dir.mkdir(parents=True, exist_ok=True)
    def check_cancelled(*_args: Any) -> None:
        if cancel_event is not None and cancel_event.is_set():
            from aimw.workers.cancellation import JobCancelled
            raise JobCancelled('Cancelled by user.')
    check_cancelled()
    options: dict[str, Any] = {
        "format": _FORMAT,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        # YouTube requires an external runtime for its JS challenges. Node is
        # already used by the dashboard, but yt-dlp enables only Deno by default.
        "js_runtimes": {"deno": {}, "node": {}},
        "no_warnings": False,
        "restrictfilenames": True,
        "download_sections": f"*0-{_clip_s}",
        "force_keyframes_at_cuts": False,
        "progress_hooks": [check_cancelled],
        "postprocessor_hooks": [check_cancelled],
        "socket_timeout": 20,
        "retries": 2,
    }
    ffmpeg_dir = _ffmpeg_dir()
    if ffmpeg_dir is not None:
        options["ffmpeg_location"] = ffmpeg_dir
    # Optional cookies file (AIMW_COOKIES_FILE) unlocks login-gated platforms
    # like Instagram and Facebook. Export it from your browser (e.g. the
    # "Get cookies.txt" extension) and point this env var at it.
    cookies = os.environ.get("AIMW_COOKIES_FILE")
    if cookies and Path(cookies).exists():
        options["cookiefile"] = cookies
    if max_duration_s is not None:
        def _too_long(info_dict: dict[str, Any], *, incomplete: bool = False) -> str | None:
            dur = info_dict.get("duration")
            if dur is not None and dur > max_duration_s:
                return f"duration {dur}s exceeds cap {max_duration_s}s"
            return None
        options["match_filter"] = _too_long
    with tempfile.TemporaryDirectory() as tmp:
        options["outtmpl"] = str(Path(tmp) / "dl.%(ext)s")
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
        check_cancelled()
        try:
            produced = next(Path(tmp).glob("dl.*"))
        except StopIteration:
            # match_filter rejected the video → no media written.
            raise MediaTooLong(
                f"{url} skipped (over {max_duration_s}s cap or filtered)"
            ) from None
        video_id = _sha16(produced)
        final = dest_dir / f"{video_id}.mp4"
        if final.exists():
            final.unlink()
        shutil.move(str(produced), str(final))

    log.info("ytdlp_downloaded", url=url, video_id=video_id, path=str(final))
    return DownloadedMedia(
        path=final,
        duration_s=_as_float(info.get("duration")),
        width=_as_int(info.get("width")),
        height=_as_int(info.get("height")),
        title=info.get("title"),
        description=info.get("description"),
        uploader=info.get("uploader"),
        video_id=video_id,
    )
