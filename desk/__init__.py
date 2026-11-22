"""Competitor Move Desk -- dated, sourced answers about rival 3PLs.

Track: Research and markets, ContextCon 05.

Four verdicts, never a guess: answered, cannot_verify, false_premise,
ambiguous_entity. Every fact carries the passage that states it and the date
of the record it came from.
"""

from .config import Config, load as load_config
from .models import (
    Answer,
    Case,
    DateKind,
    EntityCandidate,
    Evidence,
    SourceKind,
    Verdict,
)

__all__ = [
    "Config",
    "load_config",
    "Answer",
    "Case",
    "DateKind",
    "EntityCandidate",
    "Evidence",
    "SourceKind",
    "Verdict",
]
