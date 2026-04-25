"""Shared types for the analyst review system."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class AnalystVerdict:
    analyst_key: str
    decision_id: str
    verdict: str  # AGREE | DISAGREE | NEUTRAL
    confidence: float  # 0-1
    reasoning: list[str]
    suggested_errors: list[str] = field(default_factory=list)


AnalystFunc = Callable[
    [sqlite3.Connection, str, sqlite3.Row, dict[str, Any]],
    AnalystVerdict,
]
