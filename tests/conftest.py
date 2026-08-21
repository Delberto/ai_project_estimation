"""Fixtures compartidos para tests de integración HTTP."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.schemas.estimations import EstimationResult, Phase
from app.services.sessions import session_store
from main import app


def make_estimation_result(**overrides: object) -> EstimationResult:
    """Resultado LLM válido (fases suman al total)."""
    defaults: dict[str, object] = {
        "summary": (
            "Estimación para un SaaS de facturación con autenticación, "
            "emisión de facturas y panel de administración."
        ),
        "confidence_pct": 72,
        "phases": [
            Phase(
                name="Discovery",
                duration_weeks=2,
                cost_eur=5000,
                summary="Levantamiento de requisitos y arquitectura del producto.",
            ),
            Phase(
                name="MVP",
                duration_weeks=6,
                cost_eur=20000,
                summary="Implementación del núcleo de facturación y autenticación.",
            ),
        ],
        "total_duration_weeks": 8,
        "total_cost_eur": 25000,
    }
    defaults.update(overrides)
    return EstimationResult(**defaults)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clean_session_store() -> Iterator[None]:
    session_store._sessions.clear()
    yield
    session_store._sessions.clear()


@pytest.fixture(autouse=True)
def _skip_moderation() -> Iterator[None]:
    """Evita llamadas reales a OpenAI Moderations en cada estimate."""
    with patch("app.routers.sessions.validate_input", return_value=None):
        yield


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
