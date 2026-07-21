"""Exact-match in-memory cache for free-text LLM completions."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class EstimationCache:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    @staticmethod
    def make_key(
        *,
        system_prompt: str,
        user_message: str,
        model: str,
        max_tokens: int,
        thinking_budget: int | None,
    ) -> str:
        payload = json.dumps(
            {
                "system_prompt": system_prompt,
                "user_message": user_message,
                "model": model,
                "max_tokens": max_tokens,
                "thinking_budget": thinking_budget,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        return self._store.get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = value
