"""Tests de integración de sesiones con httpx.AsyncClient.

Mockean el LLM y la Files API para no depender de proveedores externos.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.config import settings
from app.services.llm_files import ProviderUploadedFile
from app.services.sessions import MAX_TURNS, session_store
from tests.conftest import make_estimation_result

# PDF mínimo válido (suficiente para el path de upload).
_MINIMAL_PDF = (
    b"%PDF-1.1\n"
    b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
    b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
    b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] "
    b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
    b"4 0 obj<< /Length 55 >>stream\n"
    b"BT /F1 12 Tf 50 100 Td (ComplianceModule) Tj ET\n"
    b"endstream\nendobj\n"
    b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n"
    b"trailer<< /Root 1 0 R >>\n"
    b"%%EOF\n"
)

_BASE_TRANSCRIPT = (
    "Necesitamos estimar el proyecto llamado FacturaGo: SaaS de facturación "
    "electrónica con login, roles y reportes. Stack Python y React. "
    "Equipo de 3 desarrolladores."
)


async def _create_session(client: AsyncClient) -> str:
    response = await client.post("/api/v1/sessions")
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


async def _estimate(
    client: AsyncClient,
    session_id: str,
    transcript: str,
    *,
    pdf: bytes | None = None,
    pdf_name: str = "spec.pdf",
) -> dict[str, Any]:
    data = {"transcript": transcript}
    files = None
    if pdf is not None:
        files = [("attachments", (pdf_name, pdf, "application/pdf"))]
    response = await client.post(
        f"/api/v1/sessions/{session_id}/estimate",
        data=data,
        files=files,
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_session_links_two_requests_and_updates_project_metadata(
    client: AsyncClient,
) -> None:
    """Dos turnos en la misma sesión acumulan project_metadata."""
    with patch(
        "app.routers.sessions.generate_estimation",
        return_value=make_estimation_result(
            summary=(
                "Estimación para FacturaGo: MVP de facturación con Python y React."
            ),
        ),
    ):
        session_id = await _create_session(client)

        first = await _estimate(client, session_id, _BASE_TRANSCRIPT)
        meta_first = first["project_metadata"]
        assert meta_first["project_name"] == "FacturaGo"
        assert meta_first["assumed_team_size"] == 3
        assert "Python" in meta_first["mentioned_technologies"]
        assert "React" in meta_first["mentioned_technologies"]

        second_transcript = (
            "Ampliamos el alcance de FacturaGo: añadimos PostgreSQL, "
            "integración Stripe y un módulo de conciliación bancaria "
            "para el mismo equipo."
        )
        second = await _estimate(client, session_id, second_transcript)
        meta_second = second["project_metadata"]

        # Hechos del primer turno se conservan; llegan tecnologías nuevas.
        assert meta_second["project_name"] == "FacturaGo"
        assert meta_second["assumed_team_size"] == 3
        assert "PostgreSQL" in meta_second["mentioned_technologies"]
        assert "Stripe" in meta_second["mentioned_technologies"]
        assert "Python" in meta_second["mentioned_technologies"]

        # GET refleja la misma memoria estructurada.
        detail = await client.get(f"/api/v1/sessions/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["project_metadata"] == meta_second


@pytest.mark.asyncio
async def test_pdf_attachment_changes_estimation_output(
    client: AsyncClient,
) -> None:
    """Con PDF adjunto, el mock del LLM altera un campo concreto del output."""

    from app.schemas.estimations import Phase

    def fake_generate(
        *args: object,
        messages: list[dict[str, Any]] | None = None,
        pdf_uploads: list[ProviderUploadedFile] | None = None,
        **kwargs: object,
    ) -> Any:
        if pdf_uploads:
            return make_estimation_result(
                summary=(
                    "Estimación ampliada por ComplianceModule del PDF adjunto "
                    "con auditoría y retención documental."
                ),
                total_cost_eur=48000,
                phases=[
                    Phase(
                        name="Discovery",
                        duration_weeks=2,
                        cost_eur=8000,
                        summary="Requisitos más compliance del PDF adjunto.",
                    ),
                    Phase(
                        name="MVP",
                        duration_weeks=8,
                        cost_eur=40000,
                        summary="Incluye ComplianceModule y controles del PDF.",
                    ),
                ],
            )
        return make_estimation_result(total_cost_eur=25000)

    fake_upload = ProviderUploadedFile(
        file_id="file-test-pdf",
        filename="compliance.pdf",
        provider="openai",
        size_bytes=len(_MINIMAL_PDF),
    )

    with (
        patch(
            "app.routers.sessions.generate_estimation",
            side_effect=fake_generate,
        ),
        patch(
            "app.services.document_extractor.upload_pdf_to_provider",
            return_value=fake_upload,
        ),
        patch("app.routers.sessions.delete_provider_file"),
        patch(
            "app.routers.sessions.active_llm_provider",
            return_value="openai",
        ),
    ):
        session_plain = await _create_session(client)
        without_pdf = await _estimate(client, session_plain, _BASE_TRANSCRIPT)

        session_pdf = await _create_session(client)
        with_pdf = await _estimate(
            client,
            session_pdf,
            _BASE_TRANSCRIPT,
            pdf=_MINIMAL_PDF,
            pdf_name="compliance.pdf",
        )

    cost_without = without_pdf["result"]["total_cost_eur"]
    cost_with = with_pdf["result"]["total_cost_eur"]
    assert cost_without == 25000
    assert cost_with == 48000
    assert cost_with != cost_without
    assert "ComplianceModule" in with_pdf["result"]["summary"]
    assert "ComplianceModule" not in without_pdf["result"]["summary"]


@pytest.mark.asyncio
async def test_eight_turns_never_exceed_max_turns_in_llm_messages(
    client: AsyncClient,
) -> None:
    """Tras 8 turnos, el historial enviado al LLM no supera MAX_TURNS."""
    captured_messages: list[list[dict[str, Any]]] = []

    def fake_generate(
        *args: object,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: object,
    ) -> Any:
        assert messages is not None
        captured_messages.append(list(messages))
        turn = len(captured_messages)
        return make_estimation_result(
            summary=(
                f"Estimación del turno {turn} para FacturaGo con alcance "
                f"incremental y supuestos explícitos."
            ),
        )

    with patch(
        "app.routers.sessions.generate_estimation",
        side_effect=fake_generate,
    ):
        session_id = await _create_session(client)
        for index in range(8):
            transcript = (
                f"{_BASE_TRANSCRIPT} Turno de refinamiento número {index + 1}: "
                f"ajustamos alcance, riesgos y dependencias del MVP."
            )
            await _estimate(client, session_id, transcript)

    assert len(captured_messages) == 8
    assert settings.MAX_TURNS == MAX_TURNS == 6

    for messages in captured_messages:
        assert messages[0]["role"] == "system"
        user_turns = sum(1 for message in messages if message["role"] == "user")
        assert user_turns <= MAX_TURNS

    # Tras superar la ventana, el último call debe quedar en el tope.
    last_user_turns = sum(
        1 for message in captured_messages[-1] if message["role"] == "user"
    )
    assert last_user_turns == MAX_TURNS

    # El historial en memoria de la sesión también respeta el tope.
    session = session_store.get(session_id)
    assert session is not None
    assert session.history is not None
    assert session.history.turn_count == MAX_TURNS
    assert session.history.max_turns == MAX_TURNS
