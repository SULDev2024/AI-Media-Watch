"""Render the human-readable evidence report from EvidencePackage + RefereeResult.

Two outputs are supported: Markdown (operational reports stored in the
``reports.markdown`` table) and HTML (for the web view). Both come from
matching Jinja2 templates in ``aimw/report/templates/``.

``SCHEMA_VERSION`` is bumped whenever a template change would invalidate a
previously rendered/stored report. Tests pin against this value via golden
files; bumping the version is a deliberate operator decision.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from aimw.core.schema.evidence import EvidencePackage
from aimw.reasoning.referee import RefereeResult

SCHEMA_VERSION: str = "2"

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
    undefined=StrictUndefined,
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
)


def render_markdown(pkg: EvidencePackage, result: RefereeResult) -> str:
    """Render the Markdown report for *pkg* + *result*."""
    template = _env.get_template("report.md.j2")
    return template.render(pkg=pkg, result=result, schema_version=SCHEMA_VERSION)


def render_html(pkg: EvidencePackage, result: RefereeResult) -> str:
    """Render the HTML report for *pkg* + *result*."""
    template = _env.get_template("report.html.j2")
    return template.render(pkg=pkg, result=result, schema_version=SCHEMA_VERSION)
