"""Canonical type aliases and constants for the evidence schema.

These ``Literal`` aliases are the closed vocabularies of the v4 architecture
(§2). They are part of the public schema contract: adding or removing a member
is a schema change and must bump :data:`SCHEMA_VERSION`.
"""

from __future__ import annotations

from typing import Literal

# Bumping this is a breaking change to the serialized form. ``serialization``
# embeds it in every payload and refuses to load anything else.
SCHEMA_VERSION = "4.0.0"

# How strong a single piece of evidence is.
EvidenceStrength = Literal["strong", "medium", "weak"]

# Which direction a piece of evidence argues.
Polarity = Literal["incriminating", "mitigating"]

# Which extractor/subsystem produced the evidence.
Source = Literal["speech", "ocr", "vision", "entity", "network"]

# The five-band risk level derived (never stored) from the score (§6.3).
RiskLevel = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "CLEAN"]

__all__ = [
    "SCHEMA_VERSION",
    "EvidenceStrength",
    "Polarity",
    "RiskLevel",
    "Source",
]
