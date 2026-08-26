"""Tests mínimos de métricas del stress runner."""

from __future__ import annotations

from evals.stress.metrics import (
    CostBudgetMetric,
    LatencyBudgetMetric,
    MemoryDriftMetric,
)


def test_latency_budget_metric_passes_when_all_turns_are_within_budget() -> None:
    metric = LatencyBudgetMetric(max_latency_ms=2_000)
    result = metric.evaluate(
        [
            {"turn_index": 1, "latency_ms": 900},
            {"turn_index": 2, "latency_ms": 1_500},
        ]
    )

    assert result.name == "latency_budget"
    assert result.passed is True
    assert result.score == 1.0
    assert result.details["within_budget"] == 2


def test_cost_budget_metric_fails_when_total_cost_exceeds_budget() -> None:
    metric = CostBudgetMetric(max_total_cost_usd=0.05)
    result = metric.evaluate(
        [
            {"turn_index": 1, "cost_usd": 0.02},
            {"turn_index": 2, "cost_usd": 0.04},
        ]
    )

    assert result.name == "cost_budget"
    assert result.passed is False
    assert result.score < 1.0
    assert result.details["total_cost_usd"] == 0.06


def test_memory_drift_metric_edge_case_recalls_fact_on_boundary_turn() -> None:
    metric = MemoryDriftMetric()
    result = metric.evaluate(
        snapshots=[
            {
                "turn_index": 1,
                "summary": "Kick-off for project Nimbus.",
                "project_metadata": {"project_name": "Nimbus"},
            },
            {
                "turn_index": 2,
                "summary": "Still estimating Nimbus with Flutter.",
                "project_metadata": {"project_name": "Nimbus"},
            },
        ],
        anchors=[(1, "project name: Nimbus")],
    )

    assert result.name == "memory_drift"
    assert result.passed is True
    assert result.score == 1.0
    assert result.details["checks"] == 1
    assert result.details["hits"] == 1
