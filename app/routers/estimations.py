from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from openai import OpenAI

from app.config import settings
from app.prompts.loader import render_estimation_prompt
from app.schemas.estimations import EstimationResponse
from app.schemas.schemas import EstimationRequest
from app.services.llm_service import generate_estimation

router = APIRouter(tags=["estimations"])

PROMPT_VERSION = "v1"

PROMPT_INJECTION_PATTERNS = [
    "ignore previous",
    "ignore all instructions",
    "you are now",
    "system prompt",
    "</project_description>",
]


class InputModerationError(Exception):
    pass


client = OpenAI(api_key=settings.OPENAI_API_KEY)


def validate_input(description: str) -> None:
    moderation = client.moderations.create(input=description)
    if moderation.results[0].flagged:
        raise InputModerationError("Description flagged by moderation API")

    lowered = description.lower()
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern in lowered:
            raise InputModerationError(
                f"Possible prompt injection detected: {pattern!r}"
            )


@router.post("/estimate", response_model=EstimationResponse)
def estimate(request: EstimationRequest) -> EstimationResponse:
    try:
        validate_input(request.description)
        system_prompt, user_prompt = render_estimation_prompt(
            request,
            version=PROMPT_VERSION,
        )
        result = generate_estimation(system_prompt, user_prompt)
    except InputModerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error al generar la estimación: {exc}",
        ) from exc

    return EstimationResponse(
        estimation=result["estimation"],
        model=result["model"],
        provider=result["provider"],
        prompt_tokens=result.get("prompt_tokens"),
        completion_tokens=result.get("completion_tokens"),
        total_tokens=result.get("total_tokens"),
        cached_tokens=result.get("cached_tokens"),
        cost_usd=result.get("cost_usd"),
        cost_mxn=result.get("cost_mxn"),
        generated_at=datetime.now(timezone.utc),
    )
