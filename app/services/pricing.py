MODEL_PRICING_USD_PER_MILLION: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    },
}


def calculate_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> float | None:
    pricing = MODEL_PRICING_USD_PER_MILLION.get(model)
    if pricing is None:
        return None

    billable_input_tokens = max(prompt_tokens - cached_tokens, 0)
    input_cost = (billable_input_tokens / 1_000_000) * pricing["input"]
    cached_cost = (cached_tokens / 1_000_000) * pricing["cached_input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]

    return input_cost + cached_cost + output_cost


def calculate_cost_mxn(cost_usd: float, usd_to_mxn_rate: float) -> float:
    return cost_usd * usd_to_mxn_rate
