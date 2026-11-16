"""Application settings, loaded from environment and `.env`.

All settings are namespaced with the ``AIMW_`` prefix. Secrets use
:class:`~pydantic.SecretStr` so they cannot be logged by accident, and
``extra="forbid"`` makes a typo'd ``AIMW_*`` variable fail loudly instead of
being silently ignored.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Runtime configuration for AI Media Watch."""

    model_config = SettingsConfigDict(
        env_prefix="AIMW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        case_sensitive=False,
    )

    # Runtime environment + logging.
    env: Environment = "dev"
    log_level: LogLevel = "INFO"

    # Run pipeline tasks inline in-process (no separate Celery worker/Redis).
    # Mirrors the AIMW_EAGER env var read directly by aimw.workers.celery_app;
    # declared here so it is accepted in .env under extra="forbid".
    eager: bool = False

    # Skip video download and Whisper; judge from URL + YouTube title/description only.
    # Gives verdicts in ~8-12s instead of 3-5 min. Set in .env as AIMW_FAST_ANALYSIS=1.
    fast_analysis: bool = False

    # GPU server pipeline URL (full qwen2.5vl analysis via Cloudflare tunnel).
    # When set, the pipeline forwards to this server for LLM verdicts.
    gpu_pipeline_url: str | None = None
    gpu_pipeline_timeout_s: float = 900.0
    auto_purge_clean: bool = False

    # Secrets (never rendered in logs; call .get_secret_value() at point of use).
    groq_api_key: SecretStr | None = None
    telegram_api_id: int | None = None
    telegram_api_hash: SecretStr | None = None
    # Portable Telethon StringSession produced by ``scripts/telegram_login.py``.
    # Preferred over a file session because it survives Docker rebuilds and
    # needs no interactive login at runtime (the login happens once, locally).
    telegram_session: SecretStr | None = None

    # Storage (ADR-0003). ``data_dir`` is the single knob; the SQLite and Chroma
    # paths derive from it unless explicitly overridden. Every consumer must use
    # the ``resolved_*`` properties (absolute, CWD-independent) so the API, the
    # Celery worker, tests, and Docker all read and write the same tree.
    data_dir: Path = Path("./data")
    sqlite_path: Path | None = None  # default: <data_dir>/aimw.db
    chroma_path: Path | None = None  # default: <data_dir>/chroma
    redis_url: str = "redis://localhost:6379/0"

    # Collection (Phase 4). The curated seed channel list is operator-edited
    # config (read by path, never imported). Media and state dirs derive from
    # data_dir so every process agrees on the absolute locations (ADR-0003).
    seed_channels_path: Path = Path("config/channels.yaml")

    # Whisper transcription (Phase 5). large-v3 is the production default;
    # operators on low-resource machines may set AIMW_WHISPER_MODEL=base. CI
    # uses tiny. Device "auto" picks CUDA when CTranslate2 reports support;
    # "cuda" attempts CUDA but falls back to CPU/int8 on load-time failure
    # (per-call failures are NOT retried — see TranscriptionError).
    whisper_model: str = "large-v3"
    whisper_device: Literal["cpu", "cuda", "auto"] = "auto"
    whisper_compute_type: str = "int8"
    whisper_cache_dir: Path | None = None  # default: <data_dir>/transcripts

    # Optional cap on downloaded media length (seconds). None = no cap. Bulk
    # crawls set this so a stray multi-hour stream can't stall the pipeline on
    # download + transcription; short scam promos are unaffected.
    max_download_duration_s: float | None = None

    # OCR (Phase 6). PaddleOCR-VL is the primary engine (§5: 2x better
    # Cyrillic vs general VLMs); the PaddleOCR 3.x classic engine is the
    # fallback when the VL class isn't importable. Frame sampling combines
    # ffmpeg scene-change detection with uniform sampling at
    # frames_per_3s/3 fps; pHash dedup collapses near-identical frames.
    ocr_engine: Literal["paddle_vl", "paddle_3"] = "paddle_vl"
    ocr_cache_dir: Path | None = None  # default: <data_dir>/ocr
    frame_cache_dir: Path | None = None  # default: <data_dir>/frames
    frames_per_3s: int = 1
    scene_change_threshold: float = 0.3

    # VLM (Phase 7). Qwen3-VL for targeted in-image text recovery on frames
    # that already had OCR hits. Install with: ``uv sync --extra vlm``.
    # Set AIMW_VLM_ENABLED=false to skip without uninstalling the extra.
    vlm_enabled: bool = True
    vlm_model: str = "Qwen/Qwen2.5-VL-4B-Instruct"
    vlm_device: Literal["cpu", "cuda", "auto"] = "auto"

    # Entity extraction (Phase 7). Watchlist is a JSON file mapping
    # {"handles": [...], "wallets": [...]}; if not set, fuzzy recovery is skipped.
    watchlist_path: Path | None = None  # default: <data_dir>/watchlist.json

    # Reasoning / Groq (Phase 10). §0.3 issue #16: token-budget guard, 200K
    # tokens/day is the binding free-tier limit. groq_request_token_budget is
    # the per-call estimate used to refuse calls when the daily cap is close.
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    groq_daily_token_cap: int = 200_000
    groq_request_token_budget: int = 4_000

    # Sovereign / on-prem inference (Phase 20). The reasoning layer speaks the
    # OpenAI-compatible chat-completions protocol, so the SAME client runs
    # against Groq cloud OR a self-hosted model server (vLLM, Ollama, TGI,
    # llama.cpp) by pointing these at a local endpoint. This is the data-
    # sovereignty requirement for government deployment: citizen content never
    # leaves the operator's network.
    #
    # Defaults preserve existing Groq behaviour: when llm_* are unset the
    # resolver falls back to the groq_* values above. Set AIMW_LLM_PROVIDER=local
    # plus AIMW_LLM_BASE_URL/AIMW_LLM_MODEL to switch to on-prem inference with
    # no code change. AIMW_LLM_REQUIRE_AUTH=false omits the Authorization header
    # for local servers that don't authenticate.
    llm_provider: Literal["groq", "openai_compatible", "local"] = "groq"
    llm_base_url: str | None = None  # overrides groq_base_url when set
    llm_model: str | None = None  # overrides groq_model when set
    llm_api_key: SecretStr | None = None  # overrides groq_api_key when set
    llm_require_auth: bool = True  # False for local servers without auth
    llm_daily_token_cap: int | None = None  # overrides groq cap (None=no extra cap on-prem)
    llm_request_timeout_s: float = 120.0
    llm_vision: bool = False  # send video frames to the LLM (requires multimodal model)

    # Telegram Bot (user-facing scam checker).
    telegram_bot_token: SecretStr | None = None

    # API server bind address (used by aimw.api.server).
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # Analyst API authentication. When set, every analyst endpoint enforces
    # the X-API-Key header. Empty string or None disables enforcement (dev/test).
    api_key: SecretStr | None = None

    # JWT authentication (Phase 21).
    jwt_secret: SecretStr | None = None
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 hours
    # Default admin credentials — created on first startup if no users exist.
    # MUST be changed in production via .env.
    admin_email: str = "admin@aimw.local"
    admin_password: SecretStr | None = None

    # Alerts (Phase 21). Admin notifications on HIGH/CRITICAL detections.
    alert_telegram_bot_token: SecretStr | None = None
    alert_telegram_chat_id: str | None = None
    alert_email_smtp_host: str | None = None
    alert_email_smtp_port: int = 587
    alert_email_from: str | None = None
    alert_email_to: str | None = None
    alert_email_password: SecretStr | None = None

    # Webhooks (Phase 21). Comma-separated URLs to POST when scam detected.
    webhook_urls: str | None = None

    @property
    def resolved_data_dir(self) -> Path:
        """Absolute data directory, independent of the current working dir."""
        return self.data_dir.expanduser().resolve()

    @property
    def resolved_sqlite_path(self) -> Path:
        """Absolute SQLite path; derived from ``data_dir`` unless overridden."""
        override = self.sqlite_path
        path = override if override is not None else self.resolved_data_dir / "aimw.db"
        return path.expanduser().resolve()

    @property
    def resolved_chroma_path(self) -> Path:
        """Absolute ChromaDB path; derived from ``data_dir`` unless overridden."""
        override = self.chroma_path
        path = override if override is not None else self.resolved_data_dir / "chroma"
        return path.expanduser().resolve()

    @property
    def resolved_media_dir(self) -> Path:
        """Absolute directory for downloaded raw media (``<data_dir>/media``)."""
        return self.resolved_data_dir / "media"

    @property
    def resolved_state_dir(self) -> Path:
        """Absolute directory for mutable runtime state (``<data_dir>/state``)."""
        return self.resolved_data_dir / "state"

    @property
    def resolved_whisper_cache_dir(self) -> Path:
        """Absolute directory for Whisper transcript JSON cache (Phase 5)."""
        override = self.whisper_cache_dir
        path = override if override is not None else self.resolved_data_dir / "transcripts"
        return path.expanduser().resolve()

    @property
    def resolved_ocr_cache_dir(self) -> Path:
        """Absolute directory for OCR JSON cache (Phase 6)."""
        override = self.ocr_cache_dir
        path = override if override is not None else self.resolved_data_dir / "ocr"
        return path.expanduser().resolve()

    @property
    def resolved_frame_cache_dir(self) -> Path:
        """Absolute directory for sampled frame PNGs (Phase 6)."""
        override = self.frame_cache_dir
        path = override if override is not None else self.resolved_data_dir / "frames"
        return path.expanduser().resolve()

    @property
    def sqlite_url_async(self) -> str:
        """SQLAlchemy async URL (aiosqlite) for the resolved SQLite path."""
        return f"sqlite+aiosqlite:///{self.resolved_sqlite_path.as_posix()}"

    @property
    def sqlite_url_sync(self) -> str:
        """SQLAlchemy sync URL (used by Alembic) for the resolved SQLite path."""
        return f"sqlite:///{self.resolved_sqlite_path.as_posix()}"

    @property
    def resolved_watchlist_path(self) -> Path:
        """Absolute watchlist JSON path; derived from ``data_dir`` unless overridden."""
        override = self.watchlist_path
        path = override if override is not None else self.resolved_data_dir / "watchlist.json"
        return path.expanduser().resolve()

    @property
    def json_logs(self) -> bool:
        """Whether logs should be emitted as JSON (true everywhere but dev)."""
        return self.env != "dev"

    # ── Resolved LLM provider config (Phase 20 sovereign inference) ───────────
    # One place the chat client reads, regardless of provider. llm_* overrides
    # win; otherwise fall back to the groq_* defaults so nothing breaks.

    @property
    def resolved_llm_base_url(self) -> str:
        """Chat-completions base URL (on-prem override or Groq default)."""
        return self.llm_base_url or self.groq_base_url

    @property
    def resolved_llm_model(self) -> str:
        """Chat-completions model id (on-prem override or Groq default)."""
        return self.llm_model or self.groq_model

    @property
    def resolved_llm_api_key(self) -> SecretStr | None:
        """API key for the chat endpoint, or None for unauthenticated local servers."""
        if not self.llm_require_auth:
            return None
        return self.llm_api_key or self.groq_api_key

    @property
    def resolved_llm_daily_token_cap(self) -> int:
        """Daily token cap. On-prem can raise/disable it; defaults to the Groq cap."""
        return self.llm_daily_token_cap if self.llm_daily_token_cap is not None else self.groq_daily_token_cap

    @property
    def is_sovereign_inference(self) -> bool:
        """True when inference runs against a non-Groq (self-hosted) endpoint."""
        return self.llm_provider != "groq" or bool(self.llm_base_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    Cached so configuration is parsed once. Call ``get_settings.cache_clear()``
    in tests that need to re-read the environment.
    """
    return Settings()
