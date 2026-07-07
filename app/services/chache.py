from redisvl.extensions.llmcache import SemanticCache
from openai import OpenAI

cache = SemanticCache(
    name="estimation_cache",
    redis_url="redis://localhost:6379",
    distance_threshold=0.08,  # equivalente a sim ≥ 0.92
    ttl=86400,
)

embeddings_client = OpenAI()

def cache_lookup(request: EstimationRequest) -> EstimationResult | None:
    bucket = build_bucket_key(request)
    embedding = embed_description(request.description)

    hit = cache.check(
        prompt=embedding,
        filter_expression=f"@bucket:{{{bucket}}}",
        num_results=1,
    )
    if hit:
        return EstimationResult.model_validate_json(hit[0]["response"])
    return None

def cache_write(request: EstimationRequest, result: EstimationResult) -> None:
    bucket = build_bucket_key(request)
    embedding = embed_description(request.description)

    cache.store(
        prompt=embedding,
        response=result.model_dump_json(),
        metadata={"bucket": bucket},
    )

def build_bucket_key(request: EstimationRequest, version: str = "v1") -> str:
    return ":".join([
        version,
        request.project_type.value,
        request.detail_level.value,
        request.output_format.value,
    ])