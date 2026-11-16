"""Validated file-upload contract with the Local Agent inference service."""
from pathlib import Path
import mimetypes

import httpx


def validate_result(data: object) -> dict:
    if not isinstance(data, dict) or data.get("error"):
        raise ValueError("Local Agent returned an error instead of an assessment")
    score = data.get("risk_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
        raise ValueError("Local Agent returned a missing or invalid risk_score")
    flags = data.get("flags")
    if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
        raise ValueError("Local Agent returned invalid flags")
    if "parse_error" in flags:
        raise ValueError("Local Agent could not parse its auditor response; retry analysis")
    for field in ("reasoning", "transcript"):
        if not isinstance(data.get(field), str):
            raise ValueError(f"Local Agent returned invalid {field}")
    return data


async def analyze_file(path: Path, *, base_url: str, caption: str, platform: str,
                       timeout_s: float = 900.0) -> dict:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=10.0)) as client:
        with path.open("rb") as source:
            response = await client.post(
                f"{base_url.rstrip('/')}/analyze",
                files={"file": (path.name, source, mime)},
                data={"caption": caption, "platform": platform},
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            if isinstance(detail, str) and detail.strip():
                raise RuntimeError(f"Local Agent analysis failed: {detail}") from exc
            raise
        return validate_result(response.json())
