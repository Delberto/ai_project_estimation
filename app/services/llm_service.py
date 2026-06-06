from openai import OpenAI

from app.config import settings
from app.context.examples import ESTIMATION_EXAMPLES
from app.services.pricing import calculate_cost_mxn, calculate_cost_usd


def build_system_prompt(examples: list[dict]) -> str:
    examples_text = ""
    for index, example in enumerate(examples, start=1):
        examples_text += f"""
---
### Ejemplo {index}

**Resumen de reunión:**
{example["meeting_summary"].strip()}

**Estimación generada:**
{example["estimation"].strip()}
"""

    return f"""Eres un estimador de software experto. Tu tarea es analizar la transcripción de una reunión con un cliente y generar una estimación detallada del proyecto de software.

Debes basarte en los ejemplos de referencia que se muestran a continuación. Cada ejemplo incluye un resumen de reunión y la estimación que se generó a partir de él. Usa estos ejemplos como guía de formato, nivel de detalle y criterios de estimación.

Genera una estimación que incluya:
- Un título descriptivo del proyecto
- Desglose de tareas con horas estimadas
- Total de horas
- Equipo recomendado
- Duración estimada del proyecto

Responde únicamente con la estimación, sin explicaciones adicionales.
{examples_text}
"""


def generate_estimation(
    transcription: str,
    examples: list[dict] | None = None,
) -> dict:
    context_examples = examples if examples is not None else ESTIMATION_EXAMPLES
    system_prompt = build_system_prompt(context_examples)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": transcription},
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
