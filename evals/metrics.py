"""Contrato compartido para métricas de evaluación."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MetricResult:
    """Resultado normalizado de una métrica de eval/stress."""

    name: str
    score: float
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)
