"""Métricas del stress runner conversacional.

Ubicadas bajo ``evals/stress/`` (y no en ``evals/metrics.py``) porque operan
sobre snapshots de ``turn_observed`` y memoria de sesión, no sobre
:class:`~app.schemas.estimations.EstimationResult` aislado.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from evals.metrics import MetricResult

TurnSnapshot = Mapping[str, Any]
Anchor = tuple[int, str]


def _fact_matches(fact: str, text: str) -> bool:
    """Busca la ancla completa o su fragmento semántico principal."""
    normalized_text = text.casefold()
    normalized_fact = fact.casefold()
    if normalized_fact in normalized_text:
        return True
    if ":" in fact:
        _, rhs = fact.split(":", 1)
        token = rhs.strip().casefold()
        return bool(token) and token in normalized_text
    if " includes " in normalized_fact:
        _, token = normalized_fact.split(" includes ", 1)
        return bool(token.strip()) and token.strip() in normalized_text
    return False


def _snapshot_text(snapshot: TurnSnapshot) -> str:
    """Serializa el snapshot a texto buscable para MemoryDriftMetric."""
    chunks: list[str] = []
    for key in ("summary", "prompt_version", "model", "provider"):
        value = snapshot.get(key)
        if value is not None:
            chunks.append(str(value))

    metadata = snapshot.get("project_metadata")
    if metadata is not None:
        chunks.append(json.dumps(metadata, ensure_ascii=False, sort_keys=True))

    for key, value in snapshot.items():
        if key in {"summary", "project_metadata", "prompt_version", "model", "provider"}:
            continue
        if value is not None:
            chunks.append(str(value))

    return "\n".join(chunks).casefold()


class LatencyBudgetMetric:
    """Comprueba que cada turno respeta un techo de ``latency_ms``."""

    def __init__(self, *, max_latency_ms: int) -> None:
        if max_latency_ms < 1:
            raise ValueError("max_latency_ms must be at least 1")
        self.max_latency_ms = max_latency_ms

    def evaluate(self, turns: Sequence[TurnSnapshot]) -> MetricResult:
        if not turns:
            return MetricResult(
                name="latency_budget",
                score=1.0,
                passed=True,
                details={"turns": 0, "max_latency_ms": self.max_latency_ms},
            )

        per_turn: list[dict[str, Any]] = []
        within_budget = 0
        for snapshot in turns:
            latency_ms = int(snapshot.get("latency_ms", 0))
            ok = latency_ms <= self.max_latency_ms
            within_budget += int(ok)
            per_turn.append(
                {
                    "turn_index": snapshot.get("turn_index"),
                    "latency_ms": latency_ms,
                    "within_budget": ok,
                }
            )

        score = within_budget / len(turns)
        worst = max(int(snapshot.get("latency_ms", 0)) for snapshot in turns)
        return MetricResult(
            name="latency_budget",
            score=score,
            passed=score == 1.0,
            details={
                "max_latency_ms": self.max_latency_ms,
                "turns": len(turns),
                "within_budget": within_budget,
                "worst_latency_ms": worst,
                "per_turn": per_turn,
            },
        )


class CostBudgetMetric:
    """Comprueba que el coste acumulado de LLM no supera el presupuesto."""

    def __init__(self, *, max_total_cost_usd: float) -> None:
        if max_total_cost_usd < 0:
            raise ValueError("max_total_cost_usd must be non-negative")
        self.max_total_cost_usd = max_total_cost_usd

    def evaluate(self, turns: Sequence[TurnSnapshot]) -> MetricResult:
        total_cost_usd = round(
            sum(float(snapshot.get("cost_usd", 0.0)) for snapshot in turns),
            6,
        )
        if total_cost_usd <= self.max_total_cost_usd:
            score = 1.0
        elif self.max_total_cost_usd == 0:
            score = 0.0
        else:
            score = max(0.0, self.max_total_cost_usd / total_cost_usd)

        passed = total_cost_usd <= self.max_total_cost_usd
        return MetricResult(
            name="cost_budget",
            score=score,
            passed=passed,
            details={
                "max_total_cost_usd": self.max_total_cost_usd,
                "total_cost_usd": total_cost_usd,
                "turns": len(turns),
            },
        )


class MemoryDriftMetric:
    """Mide recall de anclas ``fact_to_remember`` en snapshots posteriores."""

    def evaluate(
        self,
        *,
        snapshots: Sequence[TurnSnapshot],
        anchors: Sequence[Anchor],
    ) -> MetricResult:
        if not anchors:
            return MetricResult(
                name="memory_drift",
                score=1.0,
                passed=True,
                details={"anchors": 0, "checks": 0, "hits": 0},
            )

        indexed = {
            int(snapshot["turn_index"]): snapshot
            for snapshot in snapshots
            if snapshot.get("turn_index") is not None
        }
        turn_indices = sorted(indexed)

        checks: list[dict[str, Any]] = []
        hits = 0
        for introduced_at, fact in anchors:
            for turn_index in turn_indices:
                if turn_index <= introduced_at:
                    continue
                text = _snapshot_text(indexed[turn_index])
                found = _fact_matches(fact, text)
                hits += int(found)
                checks.append(
                    {
                        "fact": fact,
                        "introduced_at": introduced_at,
                        "checked_turn": turn_index,
                        "found": found,
                    }
                )

        total_checks = len(checks)
        score = 1.0 if total_checks == 0 else hits / total_checks
        return MetricResult(
            name="memory_drift",
            score=score,
            passed=score == 1.0,
            details={
                "anchors": len(anchors),
                "checks": total_checks,
                "hits": hits,
                "misses": total_checks - hits,
                "per_check": checks,
            },
        )
