from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.schemas.estimations import EstimationResponse
from app.schemas.schemas import EstimationRequest
from app.services.llm_service import generate_estimation

router = APIRouter(tags=["estimations"])


@router.post("/estimate", response_model=EstimationResponse)
def estimate(request: EstimationRequest) -> EstimationResponse:
    try:
        result = generate_estimation(request)
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
