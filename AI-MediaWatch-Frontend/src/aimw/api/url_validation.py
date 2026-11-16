"""SSRF-resistant URL validation for the analyst API (C3 mitigation).

This module is the single point where externally-supplied URLs are
validated before they enter the system. ``POST /analysis/run`` uses
``validate_ingest_url`` to reject:

* schemes other than ``http`` / ``https``
* hosts that are literal IP addresses in private, loopback, link-local,
  or otherwise non-routable ranges
* unqualified internal-looking hostnames (``localhost``, single-label
  names, ``*.internal``, ``*.local``, ``*.lan``)
* common cloud metadata endpoints
* URLs whose host is not on the per-platform allow-list

Allowed platforms are explicit: YouTube and Telegram only. Adding a new
platform is a code change reviewed against the SSRF threat model — never
an environment variable.

The validator intentionally does NOT perform DNS resolution.  Doing so
in the request path would (a) leak the API host's DNS view to attackers
and (b) be racy (TOCTOU) against a server that resolves to public IP at
validation time and link-local IP at fetch time.  The fetcher (Phase 13
worker) must perform its own resolution + IP filtering before opening a
socket.  ``validate_ingest_url`` enforces only the cheaper string-level
contracts.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

# Per-platform host allow-lists. Hostnames are matched case-insensitively
# against the FULL host (no subdomain wildcarding).  Adding a host is a
# code change.
_ALLOWED_HOSTS: dict[str, frozenset[str]] = {
    "youtube": frozenset(
        {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "music.youtube.com",
            "youtu.be",
        }
    ),
    "telegram": frozenset(
        {
            "t.me",
            "telegram.me",
            "telegram.org",
        }
    ),
}


# Hosts/labels that always signal an internal target. These are rejected
# regardless of platform.
_INTERNAL_HOST_LABELS: frozenset[str] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        # Cloud metadata endpoints (by name) — IP form is caught by the
        # ipaddress branch.
        "metadata.google.internal",
        "metadata",
    }
)


# Internal TLDs commonly used for non-routable corporate names.
_INTERNAL_TLDS: tuple[str, ...] = (
    ".internal",
    ".local",
    ".lan",
    ".intranet",
    ".corp",
    ".home",
    ".localdomain",
)


class URLValidationError(ValueError):
    """Raised when an externally-supplied URL fails SSRF validation."""


def _split(url: str) -> tuple[str, str]:
    """Return (scheme_lower, host_lower) from a URL string.

    Raises URLValidationError on parse failure or missing components.
    """
    if not isinstance(url, str):
        raise URLValidationError("url must be a string")
    url = url.strip()
    if not url:
        raise URLValidationError("url is empty")
    if len(url) > 2048:
        raise URLValidationError("url exceeds 2048 characters")
    # Reject URLs with embedded credentials (``user:pass@host``) outright
    # — they have no legitimate use here and are a common SSRF vector.
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    if not scheme:
        raise URLValidationError("url missing scheme")
    if not host:
        raise URLValidationError("url missing host")
    if parts.username or parts.password:
        raise URLValidationError("url must not include embedded credentials")
    return scheme, host


def _reject_if_ip_unsafe(host: str) -> None:
    """If ``host`` parses as an IP address, reject any non-public IP.

    Public IPv4/IPv6 *literals* are also rejected: legitimate platform
    URLs use DNS names. Allowing IP literals at all is a recurring SSRF
    pattern (e.g. ``http://93.184.216.34/`` bypasses naive host
    allow-lists), so we just refuse them outright.
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # not an IP literal
    # Any IP literal is rejected. Be specific in the error message so
    # operators can diagnose.
    reason_parts: list[str] = []
    if ip.is_loopback:
        reason_parts.append("loopback")
    if ip.is_private:
        reason_parts.append("private")
    if ip.is_link_local:
        reason_parts.append("link-local")
    if ip.is_multicast:
        reason_parts.append("multicast")
    if ip.is_reserved:
        reason_parts.append("reserved")
    if ip.is_unspecified:
        reason_parts.append("unspecified")
    detail = ",".join(reason_parts) if reason_parts else "public-literal"
    raise URLValidationError(
        f"url host is an IP address ({detail}); only platform hostnames are accepted"
    )


def _reject_if_internal_name(host: str) -> None:
    """Reject obviously internal hostnames by string analysis only."""
    if host in _INTERNAL_HOST_LABELS:
        raise URLValidationError(f"url host {host!r} is an internal hostname")
    # Single-label names ("server", "router") cannot be public domains.
    if "." not in host:
        raise URLValidationError(
            f"url host {host!r} has no dot — cannot be a public domain"
        )
    for tld in _INTERNAL_TLDS:
        if host.endswith(tld):
            raise URLValidationError(
                f"url host {host!r} ends with internal TLD {tld!r}"
            )


def validate_ingest_url(url: str, platform: str) -> str:
    """Validate a URL submitted to POST /analysis/run.

    Parameters
    ----------
    url:
        The URL supplied by the API caller.
    platform:
        The declared platform; must be one of the keys in ``_ALLOWED_HOSTS``.

    Returns
    -------
    The validated URL (unchanged on success), so callers can use the
    return value as the canonical form.

    Raises
    ------
    URLValidationError
        On any validation failure. The error message is safe to surface to
        the API caller — it never echoes internal state.
    """
    platform_norm = (platform or "").strip().lower()
    if platform_norm not in _ALLOWED_HOSTS:
        raise URLValidationError(
            f"platform {platform!r} is not supported; "
            f"allowed: {sorted(_ALLOWED_HOSTS)}"
        )

    scheme, host = _split(url)
    if scheme not in ("http", "https"):
        raise URLValidationError(
            f"url scheme {scheme!r} is not allowed; only http and https"
        )

    _reject_if_ip_unsafe(host)
    _reject_if_internal_name(host)

    if host not in _ALLOWED_HOSTS[platform_norm]:
        raise URLValidationError(
            f"url host {host!r} is not on the {platform_norm!r} allow-list"
        )

    return url


__all__ = ["URLValidationError", "validate_ingest_url"]
