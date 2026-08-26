#!/usr/bin/env python3
"""Stress runner conversacional contra la API FastAPI.

Recorre escenarios × tamaños de adjunto × repeticiones, escribe **una fila
CSV por turno** y evalúa métricas de sesión al cerrar cada corrida.

Uso:
    uv run python -m evals.stress.run --http http://localhost:8000
    uv run python evals/stress/run.py --repeats 3
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from evals.stress.fixtures.build_pdfs import generate_all
from evals.stress.metrics import (
    CostBudgetMetric,
    LatencyBudgetMetric,
    MemoryDriftMetric,
)
from evals.stress.scenarios import SCENARIOS, TurnScenario

STRESS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = STRESS_DIR / "fixtures"
DEFAULT_OUTPUT = STRESS_DIR / "results.csv"
DEFAULT_REPEATS = 3

ATTACHMENT_SIZES: list[tuple[str, str | None]] = [
    ("0kb", None),
    ("5kb", "attach_5kb.pdf"),
    ("20kb", "attach_20kb.pdf"),
    ("50kb", "attach_50kb.pdf"),
    ("100kb", "attach_100kb.pdf"),
]

CSV_FIELDS = [
    "run_id",
    "timestamp",
    "scenario",
    "attachment_size",
    "attachment_bytes",
    "repeat",
    "session_id",
    "turn_index",
    "status",
    "error",
    "turn_index_observed",
    "enriched_transcript_chars",
    "attachments_total_chars",
    "messages_in_window",
    "anchors_count",
    "summary_chars",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "latency_ms",
    "cache_hit_kind",
    "last_resolved_tier",
    "latency_budget_score",
    "latency_budget_passed",
    "cost_budget_score",
    "cost_budget_passed",
    "memory_drift_score",
    "memory_drift_passed",
]


@dataclass(frozen=True)
class Scenario:
    name: str
    turns: list[TurnScenario]


def load_scenarios() -> list[Scenario]:
    return [Scenario(name=name, turns=turns) for name, turns in SCENARIOS.items()]


def ensure_fixtures() -> None:
    generate_all(FIXTURES_DIR)


def _attachment_path(label: str, filename: str | None) -> Path | None:
    if filename is None:
        return None
    path = FIXTURES_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing fixture {path}. Run evals/stress/fixtures/build_pdfs.py first."
        )
    return path


def _attachment_bytes(label: str, path: Path | None) -> int:
    if path is None:
        return 0
    return path.stat().st_size


def build_turn_snapshot(
    *,
    turn_observed: dict[str, Any],
    estimate_body: dict[str, Any],
    session_body: dict[str, Any],
) -> dict[str, Any]:
    """Snapshot para métricas a partir de ``turn_observed`` + sesión."""
    result = estimate_body["result"]
    return {
        **turn_observed,
        "turn_index": turn_observed.get("turn_index"),
        "summary": result["summary"],
        "project_metadata": session_body["project_metadata"],
    }


async def _create_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/api/v1/sessions")
    response.raise_for_status()
    return response.json()["session_id"]


async def _get_session(client: httpx.AsyncClient, session_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/v1/sessions/{session_id}")
    response.raise_for_status()
    return response.json()


async def _estimate_turn(
    client: httpx.AsyncClient,
    *,
    session_id: str,
    transcript: str,
    attachment_path: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    data = {"transcript": transcript}
    files = None
    if attachment_path is not None:
        files = [
            (
                "attachments",
                (
                    attachment_path.name,
                    attachment_path.read_bytes(),
                    "application/pdf",
                ),
            )
        ]

    response = await client.post(
        f"/api/v1/sessions/{session_id}/estimate",
        data=data,
        files=files,
    )
    response.raise_for_status()
    estimate_body = response.json()
    session_body = await _get_session(client, session_id)
    return estimate_body, session_body


def _write_csv_rows(output_path: Path, rows: list[dict[str, Any]], *, append: bool) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = append and output_path.exists() and output_path.stat().st_size > 0
    mode = "a" if append and output_path.exists() else "w"
    with output_path.open(mode, newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if not write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


async def run_scenario_once(
    client: httpx.AsyncClient,
    *,
    scenario: Scenario,
    attachment_label: str,
    attachment_path: Path | None,
    repeat: int,
    latency_metric: LatencyBudgetMetric,
    cost_metric: CostBudgetMetric,
    memory_metric: MemoryDriftMetric,
) -> list[dict[str, Any]]:
    run_id = str(uuid.uuid4())
    attachment_bytes = _attachment_bytes(attachment_label, attachment_path)
    snapshots: list[dict[str, Any]] = []
    anchors = [(turn_index, fact) for turn_index, _transcript, fact in scenario.turns]
    turn_rows: list[dict[str, Any]] = []

    base_row = {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "scenario": scenario.name,
        "attachment_size": attachment_label,
        "attachment_bytes": attachment_bytes,
        "repeat": repeat,
    }

    try:
        session_id = await _create_session(client)

        for turn_index, transcript, _fact in scenario.turns:
            estimate_body, session_body = await _estimate_turn(
                client,
                session_id=session_id,
                transcript=transcript,
                attachment_path=attachment_path,
            )
            turn_observed = estimate_body.get("turn_observed") or {}
            snapshot = build_turn_snapshot(
                turn_observed=turn_observed,
                estimate_body=estimate_body,
                session_body=session_body,
            )
            snapshots.append(snapshot)

            latency_result = latency_metric.evaluate(snapshots)
            cost_result = cost_metric.evaluate(snapshots)
            memory_result = memory_metric.evaluate(
                snapshots=snapshots,
                anchors=anchors,
            )

            turn_rows.append(
                {
                    **base_row,
                    "session_id": session_id,
                    "turn_index": turn_index,
                    "status": "ok",
                    "error": "",
                    "turn_index_observed": turn_observed.get("turn_index", ""),
                    "enriched_transcript_chars": turn_observed.get(
                        "enriched_transcript_chars", ""
                    ),
                    "attachments_total_chars": turn_observed.get(
                        "attachments_total_chars", ""
                    ),
                    "messages_in_window": turn_observed.get("messages_in_window", ""),
                    "anchors_count": turn_observed.get("anchors_count", ""),
                    "summary_chars": turn_observed.get("summary_chars", ""),
                    "tokens_in": turn_observed.get("tokens_in", ""),
                    "tokens_out": turn_observed.get("tokens_out", ""),
                    "cost_usd": turn_observed.get("cost_usd", ""),
                    "latency_ms": turn_observed.get("latency_ms", ""),
                    "cache_hit_kind": turn_observed.get("cache_hit_kind", ""),
                    "last_resolved_tier": turn_observed.get("last_resolved_tier", ""),
                    "latency_budget_score": latency_result.score,
                    "latency_budget_passed": latency_result.passed,
                    "cost_budget_score": cost_result.score,
                    "cost_budget_passed": cost_result.passed,
                    "memory_drift_score": memory_result.score,
                    "memory_drift_passed": memory_result.passed,
                }
            )

        if not turn_rows:
            raise RuntimeError("No turns completed")

    except Exception as exc:
        error_row = {
            **base_row,
            "session_id": "",
            "turn_index": len(turn_rows) + 1,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
        turn_rows.append(error_row)

    return turn_rows


async def run_all(
    client: httpx.AsyncClient,
    *,
    repeats: int,
    output_path: Path,
    latency_metric: LatencyBudgetMetric,
    cost_metric: CostBudgetMetric,
    memory_metric: MemoryDriftMetric,
    scenarios: list[Scenario],
    attachment_sizes: list[tuple[str, str | None]],
    reset_output: bool,
) -> int:
    total_rows = 0
    first_write = True
    for scenario in scenarios:
        for attachment_label, attachment_filename in attachment_sizes:
            attachment_path = _attachment_path(attachment_label, attachment_filename)
            for repeat in range(repeats):
                rows = await run_scenario_once(
                    client,
                    scenario=scenario,
                    attachment_label=attachment_label,
                    attachment_path=attachment_path,
                    repeat=repeat,
                    latency_metric=latency_metric,
                    cost_metric=cost_metric,
                    memory_metric=memory_metric,
                )
                _write_csv_rows(
                    output_path,
                    rows,
                    append=not (reset_output and first_write),
                )
                first_write = False
                total_rows += len(rows)
                status = rows[-1].get("status", "error") if rows else "error"
                print(
                    f"[{status}] scenario={scenario.name} attachment={attachment_label} "
                    f"repeat={repeat} turn_rows={len(rows)}"
                )
    return total_rows


async def main(
    *,
    base_url: str,
    repeats: int,
    output_path: Path,
    max_latency_ms: int,
    max_total_cost_usd: float,
    scenarios: list[Scenario],
    attachment_sizes: list[tuple[str, str | None]],
    client: httpx.AsyncClient | None = None,
    reset_output: bool = True,
) -> int:
    ensure_fixtures()
    if reset_output and output_path.exists():
        output_path.unlink()

    latency_metric = LatencyBudgetMetric(max_latency_ms=max_latency_ms)
    cost_metric = CostBudgetMetric(max_total_cost_usd=max_total_cost_usd)
    memory_metric = MemoryDriftMetric()

    if client is not None:
        return await run_all(
            client,
            repeats=repeats,
            output_path=output_path,
            latency_metric=latency_metric,
            cost_metric=cost_metric,
            memory_metric=memory_metric,
            scenarios=scenarios,
            attachment_sizes=attachment_sizes,
            reset_output=reset_output,
        )

    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=300.0) as http_client:
        return await run_all(
            http_client,
            repeats=repeats,
            output_path=output_path,
            latency_metric=latency_metric,
            cost_metric=cost_metric,
            memory_metric=memory_metric,
            scenarios=scenarios,
            attachment_sizes=attachment_sizes,
            reset_output=reset_output,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run conversational stress evals.")
    parser.add_argument(
        "--http",
        "--base-url",
        dest="base_url",
        default=os.getenv("STRESS_API_BASE_URL", "http://localhost:8000"),
        help="API base URL",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run in-process against ASGI app with mocked LLM (no live API key)",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=int(os.getenv("STRESS_REPEATS", str(DEFAULT_REPEATS))),
        help="Repetitions per scenario × attachment size (default: 3)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.getenv("STRESS_OUTPUT", str(DEFAULT_OUTPUT))),
        help="CSV output path",
    )
    parser.add_argument(
        "--max-latency-ms",
        type=int,
        default=int(os.getenv("STRESS_MAX_LATENCY_MS", "60000")),
        help="Per-turn latency budget for LatencyBudgetMetric",
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=float(os.getenv("STRESS_MAX_COST_USD", "5.0")),
        help="Session cumulative LLM cost budget for CostBudgetMetric",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing CSV instead of overwriting",
    )
    return parser.parse_args(argv)


def cli(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")

    client = None
    if args.offline:
        from unittest.mock import patch

        from httpx import ASGITransport, AsyncClient

        from main import app
        from tests.conftest import make_estimation_result
        from tests.test_sessions_integration import _llm_meta, _mock_llm_wrapper

        turn_counter = {"n": 0}

        def fake_get_llm_wrapper():
            turn_counter["n"] += 1
            turn = turn_counter["n"]
            meta = _llm_meta()
            meta["input_tokens"] = 1800 + turn * 350
            meta["output_tokens"] = 650 + turn * 40
            meta["latency_ms"] = 900 + turn * 180
            meta["cost_usd"] = round(
                (meta["input_tokens"] * 0.15 + meta["output_tokens"] * 0.60) / 1_000_000,
                6,
            )
            wrapper = _mock_llm_wrapper(
                make_estimation_result(
                    summary=(
                        f"Estimación del turno {turn} con supuestos explícitos, "
                        f"stack acordado y restricciones de presupuesto."
                    )
                )
            )
            wrapper.complete_structured.return_value = (
                wrapper.complete_structured.return_value[0],
                meta,
            )
            return wrapper

        from app.services.llm_files import ProviderUploadedFile

        async def _run_offline() -> int:
            with (
                patch("app.services.estimation.validate_input", return_value=None),
                patch("app.services.estimation.delete_provider_file"),
                patch(
                    "app.services.document_extractor.upload_pdf_to_provider",
                    side_effect=lambda filename, data, provider: ProviderUploadedFile(
                        file_id="file-offline",
                        filename=filename,
                        provider=provider,
                        size_bytes=len(data),
                    ),
                ),
                patch(
                    "app.services.estimation.get_llm_wrapper",
                    side_effect=fake_get_llm_wrapper,
                ),
            ):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as ac:
                    return await main(
                        base_url="http://test",
                        repeats=args.repeats,
                        output_path=args.output,
                        max_latency_ms=args.max_latency_ms,
                        max_total_cost_usd=args.max_cost_usd,
                        scenarios=load_scenarios(),
                        attachment_sizes=ATTACHMENT_SIZES,
                        client=ac,
                        reset_output=not args.append,
                    )

        total = asyncio.run(_run_offline())
        print(f"Wrote {total} turn rows to {args.output} (offline/mock)")
        return

    total = asyncio.run(
        main(
            base_url=args.base_url,
            repeats=args.repeats,
            output_path=args.output,
            max_latency_ms=args.max_latency_ms,
            max_total_cost_usd=args.max_cost_usd,
            scenarios=load_scenarios(),
            attachment_sizes=ATTACHMENT_SIZES,
            reset_output=not args.append,
        )
    )
    print(f"Wrote {total} turn rows to {args.output}")


if __name__ == "__main__":
    cli()
