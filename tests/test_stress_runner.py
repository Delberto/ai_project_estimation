"""Tests del stress runner (in-process, LLM mockeado)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.schemas.estimations import EstimationResult
from evals.stress.run import ATTACHMENT_SIZES, load_scenarios, main
from main import app
from tests.conftest import make_estimation_result
from tests.test_sessions_integration import _mock_llm_wrapper


@pytest.mark.asyncio
async def test_stress_runner_writes_csv_row(tmp_path: Path) -> None:
    output = tmp_path / "results.csv"
    scenarios = [load_scenarios()[0]]  # baseline (3 turns)
    attachment_sizes = [ATTACHMENT_SIZES[0]]  # 0kb

    with patch(
        "app.services.estimation.get_llm_wrapper",
        return_value=_mock_llm_wrapper(
            make_estimation_result(
                summary="Estimación baseline para Nimbus con Flutter y PostgreSQL."
            )
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            total = await main(
                base_url="http://test",
                repeats=1,
                output_path=output,
                max_latency_ms=30_000,
                max_total_cost_usd=1.0,
                scenarios=scenarios,
                attachment_sizes=attachment_sizes,
                client=client,
            )

    text = output.read_text(encoding="utf-8")
    assert total == 3
    assert "baseline" in text
    assert "0kb" in text
    assert "tokens_in" in text
    assert "memory_drift_score" in text
    assert ",ok," in text or text.count(",ok,") >= 1
