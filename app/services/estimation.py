"""Orquestación de estimaciones conversacionales multi-turno."""

from __future__ import annotations

from typing import Any

import structlog

from app.config import settings
from app.prompts.loader import render_estimation_prompt
from app.routers.estimations import validate_input
from app.schemas.estimations import EstimationRequest, EstimationResult
from app.services.document_extractor import PreparedAttachments
from app.services.llm_files import delete_provider_file
from app.services.llm_wrapper import get_llm_wrapper
from app.services.metadata_extractor import update_project_metadata
from app.services.sessions import ConversationHistory, ProjectMetadata, Session

log = structlog.get_logger()


def _anchors_count(metadata: ProjectMetadata) -> int:
    """Hechos estructurados acumulados contables como anclas de memoria."""
    count = 0
    if metadata.project_name:
        count += 1
    if metadata.assumed_team_size is not None:
        count += 1
    if metadata.agreed_scope:
        count += 1
    count += len(metadata.mentioned_technologies)
    return count


class EstimationService:
    """Motor de estimación con sesión e historial deslizante."""

    def estimate_conversational(
        self,
        *,
        session_id: str,
        session: Session,
        prepared: PreparedAttachments,
        request: EstimationRequest,
        prompt_version: str,
    ) -> tuple[EstimationResult, ProjectMetadata, dict[str, Any]]:
        validate_input(request.description)

        system_prompt, user_prompt = render_estimation_prompt(
            request,
            version=prompt_version,
            project_metadata=session.metadata,
        )

        if session.history is None:
            session.history = ConversationHistory(
                system_prompt=system_prompt,
                max_turns=settings.MAX_TURNS,
            )
        session.history.add_user(user_prompt)

        messages = session.history.to_messages_list(
            session.metadata,
            request=request,
            version=prompt_version,
        )

        wrapper = get_llm_wrapper()
        pdf_uploads = prepared.pdf_uploads
        try:
            result, meta = wrapper.complete_structured(
                messages=messages,
                response_model=EstimationResult,
                pdf_uploads=pdf_uploads,
            )
        finally:
            for uploaded in pdf_uploads:
                delete_provider_file(uploaded)

        session.history.add_assistant(result.summary)
        metadata = update_project_metadata(
            session.metadata,
            user_text=prepared.description,
            result=result,
        )
        session.metadata = metadata

        turn_observed = {
            "turn_index": session.history.turn_count,
            "session_id": session_id,
            "enriched_transcript_chars": len(prepared.description),
            "attachments_total_chars": prepared.attachments_total_chars,
            "messages_in_window": session.history.turn_count * 2,
            "anchors_count": _anchors_count(metadata),
            "summary_chars": len(result.summary),
            "tokens_in": int(meta.get("input_tokens", 0)),
            "tokens_out": int(meta.get("output_tokens", 0)),
            "cost_usd": float(meta.get("cost_usd", 0.0)),
            "latency_ms": int(meta["latency_ms"]),
            "cache_hit_kind": str(meta.get("cache_hit_kind", "none")),
            "last_resolved_tier": str(meta.get("last_resolved_tier", meta["model"])),
        }

        log.info("turn_observed", **turn_observed)

        return result, metadata, turn_observed


estimation_service = EstimationService()
