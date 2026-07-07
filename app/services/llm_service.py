from openai import OpenAI

from app.config import settings
from app.services.pricing import calculate_cost_mxn, calculate_cost_usd


def generate_estimation(system_prompt: str, user_prompt: str) -> dict:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
    )

    estimation = response.choices[0].message.content
    if not estimation:
        raise ValueError("El modelo no devolvió una estimación")

    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage else None
    completion_tokens = usage.completion_tokens if usage else None
    total_tokens = usage.total_tokens if usage else None

    cached_tokens = 0
    if usage and usage.prompt_tokens_details:
        cached_tokens = usage.prompt_tokens_details.cached_tokens or 0

    cost_usd = None
    cost_mxn = None
    if prompt_tokens is not None and completion_tokens is not None:
        cost_usd = calculate_cost_usd(
            model=settings.OPENAI_MODEL,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        )
        if cost_usd is not None:
            cost_mxn = calculate_cost_mxn(cost_usd, settings.USD_TO_MXN_RATE)

    return {
        "estimation": estimation,
        "model": settings.OPENAI_MODEL,
        "provider": settings.LLM_PROVIDER,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens or None,
        "cost_usd": cost_usd,
        "cost_mxn": cost_mxn,
    }
