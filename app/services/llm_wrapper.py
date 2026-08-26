"""LiteLLM-backed wrapper that adds provider fallback, exact-match cache, cost tracking,
and structured logging to every LLM call in the estimator.

Design notes
------------
- The wrapper exposes two primitives:
  - ``complete()``: legacy free-text answer (kept for tests that depend on it).
  - ``complete_structured()``: returns a validated Pydantic model via Instructor,
    re-prompting on validator errors up to ``max_retries`` times.
- The Router is configured with two deployments under the same ``model_name``
  ("estimator") so LiteLLM can switch from primary to fallback transparently.
  When the caller overrides the model per-request we bypass the Router and call
  ``litellm.completion`` directly — that path has no fallback by design.
"""

from __future__ import annotations

import time
from typing import Any, TypeVar

import instructor
import litellm
import structlog
from litellm import Router
from pydantic import BaseModel

from app.config import settings
from app.schemas.estimations import EstimationResult
from app.services.cache import EstimationCache
from app.services.llm_files import (
    ProviderUploadedFile,
    build_user_content_with_pdfs,
    delete_provider_file,
)

log = structlog.get_logger()

_llm_wrapper: "LLMWrapper | None" = None


# Cost per 1M tokens (USD). Update as pricing changes.
MODEL_COSTS: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
}


T = TypeVar("T", bound=BaseModel)


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    base = _normalise_model_name(model)
    costs = MODEL_COSTS.get(base) or MODEL_COSTS.get(model) or {"input": 0.0, "output": 0.0}
    return round((tokens_in * costs["input"] + tokens_out * costs["output"]) / 1_000_000, 6)


def _normalise_model_name(model: str) -> str:
    """Strip provider prefixes like ``anthropic/`` that LiteLLM may emit."""
    return model.split("/", 1)[1] if "/" in model else model


def _provider_from_model(model: str) -> str:
    name = _normalise_model_name(model).lower()
    if name.startswith("claude"):
        return "anthropic"
    if name.startswith("gpt") or name.startswith("o1") or name.startswith("o3"):
        return "openai"
    return "unknown"


class LLMWrapper:
    """Unified LLM client with cache, fallback, and cost tracking."""

    def __init__(
        self,
        *,
        openai_api_key: str | None,
        anthropic_api_key: str | None,
        primary_model: str,
        fallback_model: str,
        timeout: int,
        num_retries: int,
        cache: EstimationCache,
    ):
        self.openai_api_key = openai_api_key
        self.anthropic_api_key = anthropic_api_key
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.timeout = timeout
        self.num_retries = num_retries
        self.cache = cache

        self.router = Router(
            model_list=[
                {
                    "model_name": "estimator",
                    "litellm_params": {
                        "model": primary_model,
                        "api_key": openai_api_key,
                        "timeout": timeout,
                    },
                },
                {
                    "model_name": "estimator",
                    "litellm_params": {
                        "model": fallback_model,
                        "api_key": anthropic_api_key,
                        "timeout": timeout,
                    },
                },
            ],
            fallbacks=[{"estimator": ["estimator"]}],
            num_retries=num_retries,
        )

        # Instructor wraps ``litellm.completion`` so we can call any of the
        # underlying providers with the same ``response_model=`` API.
        self._instructor = instructor.from_litellm(litellm.completion)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(
        self,
        *,
        system_prompt: str,
        user_message: str,
        model_override: str | None = None,
        max_tokens: int = 4000,
        thinking_budget: int | None = None,
    ) -> dict[str, Any]:
        """Single LLM call returning a free-text answer. Kept for tests."""
        cache_key_model = model_override or self.primary_model
        cache_key = EstimationCache.make_key(
            system_prompt=system_prompt,
            user_message=user_message,
            model=cache_key_model,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
        )
        cached = self.cache.get(cache_key)
        if cached:
            return {**cached, "cache_hit": True}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        kwargs = self._build_call_kwargs(
            messages=messages,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            model_override=model_override,
        )

        log.info(
            "llm_call_started",
            mode="blocking",
            model=model_override or self.primary_model,
        )
        t0 = time.perf_counter()
        try:
            response = self._dispatch(model_override=model_override, **kwargs)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            log.error(
                "llm_call_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                latency_ms=latency_ms,
            )
            raise

        latency_ms = int((time.perf_counter() - t0) * 1000)
        result = self._normalise_response(response, latency_ms=latency_ms)
        log.info(
            "llm_call_completed",
            model=result["model"],
            provider=result["provider"],
            input_tokens=result["usage"]["input_tokens"],
            output_tokens=result["usage"]["output_tokens"],
            cost_usd=result["cost_usd"],
            latency_ms=latency_ms,
            finish_reason=result["finish_reason"],
        )
        self.cache.set(cache_key, result)
        return {**result, "cache_hit": False}

    def complete_structured(
        self,
        *,
        system_prompt: str | None = None,
        user_message: str | None = None,
        response_model: type[T],
        model_override: str | None = None,
        max_tokens: int = 4000,
        max_retries: int = 6,
        pdf_uploads: list[ProviderUploadedFile] | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> tuple[T, dict[str, Any]]:
        """Run the LLM with Instructor and return ``(model_instance, meta)``.

        ``meta`` includes ``model``, ``provider`` and ``latency_ms``. Instructor
        re-prompts the LLM up to ``max_retries`` times when a Pydantic validator
        raises, feeding the ``ValueError`` message back to the model.

        Pass either ``messages`` (multi-turno, p.ej. desde
        ``ConversationHistory.to_messages_list``) o el par
        ``system_prompt`` + ``user_message``.

        When ``pdf_uploads`` is set, the **último** mensaje user se convierte
        en content multimodal con los ``file_id``s (OpenAI ``file`` parts o
        Anthropic ``document`` blocks).

        Streaming bypasses are not relevant here — the entire model is built
        atomically by Instructor before this function returns.
        """
        target_model = model_override or self.primary_model
        provider = _provider_from_model(target_model)
        if messages is not None:
            api_messages = _attach_pdfs_to_last_user(
                messages,
                pdf_uploads=pdf_uploads or [],
                provider=provider,
            )
        else:
            if system_prompt is None or user_message is None:
                raise ValueError(
                    "Provide messages=… or both system_prompt and user_message"
                )
            user_content = build_user_content_with_pdfs(
                text=user_message,
                pdf_uploads=pdf_uploads or [],
                provider=provider,
            )
            api_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]

        api_key = (
            self.anthropic_api_key if provider == "anthropic" else self.openai_api_key
        )
        create_kwargs: dict[str, Any] = {
            "model": target_model,
            "api_key": api_key,
            "timeout": self.timeout,
            "messages": api_messages,
            "response_model": response_model,
            "max_tokens": max_tokens,
            "max_retries": max_retries,
        }
        # Anthropic Files API requires the beta header on the Messages call.
        if provider == "anthropic" and pdf_uploads:
            create_kwargs["extra_headers"] = {
                "anthropic-beta": "files-api-2025-04-14",
            }

        log.info(
            "llm_structured_call_started",
            model=target_model,
            response_model=response_model.__name__,
            pdf_count=len(pdf_uploads or []),
        )
        t0 = time.perf_counter()
        try:
            result, raw_completion = self._instructor.chat.completions.create_with_completion(
                **create_kwargs
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            log.error(
                "llm_structured_call_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                latency_ms=latency_ms,
            )
            raise

        latency_ms = int((time.perf_counter() - t0) * 1000)
        usage = getattr(raw_completion, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        resolved_model = _normalise_model_name(
            getattr(raw_completion, "model", target_model)
        )
        meta = {
            "model": resolved_model,
            "provider": provider,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": _estimate_cost(resolved_model, input_tokens, output_tokens),
            "cache_hit_kind": "none",
            "last_resolved_tier": resolved_model,
        }
        log.info(
            "llm_structured_call_completed",
            model=meta["model"],
            provider=meta["provider"],
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=meta["cost_usd"],
        )
        return result, meta

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_call_kwargs(
        self,
        *,
        messages: list[dict],
        max_tokens: int,
        thinking_budget: int | None,
        model_override: str | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
        }

        if thinking_budget is not None:
            target_model = model_override or self.primary_model
            if _provider_from_model(target_model) == "anthropic":
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
                kwargs["max_tokens"] = max(max_tokens, thinking_budget + 1024)
            else:
                log.warning(
                    "thinking_budget_ignored_for_provider",
                    provider=_provider_from_model(target_model),
                    model=target_model,
                )
        return kwargs

    def _dispatch(self, *, model_override: str | None, **kwargs: Any) -> Any:
        """Call the Router (with fallback) or LiteLLM directly when the caller
        wants a specific model."""
        if model_override:
            api_key = (
                self.anthropic_api_key
                if _provider_from_model(model_override) == "anthropic"
                else self.openai_api_key
            )
            return litellm.completion(
                model=model_override,
                api_key=api_key,
                timeout=self.timeout,
                num_retries=self.num_retries,
                **kwargs,
            )
        return self.router.completion(model="estimator", **kwargs)

    @staticmethod
    def _normalise_response(response: Any, *, latency_ms: int) -> dict[str, Any]:
        choice = response.choices[0]
        finish_reason = (choice.finish_reason or "stop").lower()
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", input_tokens + output_tokens) or (
            input_tokens + output_tokens
        )

        model = _normalise_model_name(response.model)
        return {
            "estimation": choice.message.content or "",
            "model": model,
            "provider": _provider_from_model(model),
            "finish_reason": finish_reason,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            },
            "latency_ms": latency_ms,
            "cost_usd": _estimate_cost(model, input_tokens, output_tokens),
        }


def get_llm_wrapper() -> LLMWrapper:
    global _llm_wrapper
    if _llm_wrapper is None:
        _llm_wrapper = LLMWrapper(
            openai_api_key=settings.OPENAI_API_KEY,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            primary_model=settings.OPENAI_MODEL,
            fallback_model=settings.FALLBACK_MODEL,
            timeout=settings.LLM_TIMEOUT,
            num_retries=settings.LLM_NUM_RETRIES,
            cache=EstimationCache(),
        )
    return _llm_wrapper


def generate_estimation(
    system_prompt: str | None = None,
    user_message: str | None = None,
    *,
    messages: list[dict[str, Any]] | None = None,
    pdf_uploads: list[ProviderUploadedFile] | None = None,
    cleanup_pdfs: bool = True,
) -> EstimationResult:
    """Generate a structured estimation, optionally with PDF file_ids attached.

    Accepts either a single-turn ``system_prompt`` + ``user_message`` or a
    full ``messages`` list (sliding-window history).

    PDFs must already be uploaded via :mod:`app.services.llm_files`. When
    ``cleanup_pdfs`` is True (default), remote files are deleted after the
    call finishes (success or failure).
    """
    wrapper = get_llm_wrapper()
    try:
        result, _meta = wrapper.complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            messages=messages,
            response_model=EstimationResult,
            pdf_uploads=pdf_uploads,
        )
        return result
    finally:
        if cleanup_pdfs and pdf_uploads:
            for uploaded in pdf_uploads:
                delete_provider_file(uploaded)


def _attach_pdfs_to_last_user(
    messages: list[dict[str, Any]],
    *,
    pdf_uploads: list[ProviderUploadedFile],
    provider: str,
) -> list[dict[str, Any]]:
    """Copia ``messages`` y adjunta PDFs al content del último mensaje user."""
    if not pdf_uploads:
        return list(messages)

    api_messages = [dict(message) for message in messages]
    for index in range(len(api_messages) - 1, -1, -1):
        if api_messages[index].get("role") != "user":
            continue
        content = api_messages[index].get("content", "")
        if not isinstance(content, str):
            raise ValueError(
                "Cannot attach PDFs to a non-text user message in history"
            )
        api_messages[index] = {
            **api_messages[index],
            "content": build_user_content_with_pdfs(
                text=content,
                pdf_uploads=pdf_uploads,
                provider=provider,
            ),
        }
        return api_messages

    raise ValueError("No user message found to attach PDF uploads")


def active_llm_provider() -> str:
    """Provider inferred from the primary model (``openai`` / ``anthropic``)."""
    return _provider_from_model(settings.OPENAI_MODEL)