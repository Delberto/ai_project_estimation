"""Extracción heurística de :class:`ProjectMetadata` tras cada turno.

En esta fase usamos regex y un diccionario de tecnologías conocidas en lugar
de una segunda llamada al LLM. Ver README → "Project metadata".
"""

from __future__ import annotations

import re

from app.schemas.estimations import EstimationResult
from app.services.sessions import ProjectMetadata

# Ordenados de más específico a más genérico para evitar falsos positivos
# (p.ej. "Next.js" antes que "js", "React Native" antes que "React").
_KNOWN_TECHNOLOGIES: tuple[str, ...] = (
    "React Native",
    "Next.js",
    "Node.js",
    "Vue.js",
    "Nuxt.js",
    "NestJS",
    "Spring Boot",
    "ASP.NET",
    ".NET",
    "PostgreSQL",
    "MongoDB",
    "Elasticsearch",
    "GraphQL",
    "TypeScript",
    "JavaScript",
    "Python",
    "Django",
    "FastAPI",
    "Flask",
    "Fastify",
    "Express",
    "Angular",
    "React",
    "Vue",
    "Svelte",
    "Flutter",
    "Kotlin",
    "Swift",
    "Java",
    "Go",
    "Rust",
    "Ruby",
    "Rails",
    "PHP",
    "Laravel",
    "Redis",
    "Kafka",
    "RabbitMQ",
    "Docker",
    "Kubernetes",
    "Terraform",
    "Firebase",
    "Supabase",
    "Stripe",
    "Tailwind",
    "AWS",
    "GCP",
    "Azure",
    "MySQL",
    "SQLite",
    "Prisma",
    "SQLAlchemy",
)

_TEAM_SIZE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:equipo|team)\s+(?:de|of)\s+(\d{1,3})\s*"
        r"(?:desarrolladores|developers|devs|personas|people|engineers)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(\d{1,3})\s*(?:desarrolladores|developers|devs|engineers)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:assumed_team_size|tamaño de equipo|team size)\s*[:=]\s*(\d{1,3})",
        re.IGNORECASE,
    ),
)

_PROJECT_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:proyecto|sistema|plataforma|portal|app(?:licaci[oó]n)?)\s+"
        r"(?:llamad[oa]\s+|named\s+|called\s+)?"
        r'["«]?([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚáéíóúñ0-9](?:[\wÁÉÍÓÚáéíóúñ0-9\s\-/]{0,60}'
        r"[\wÁÉÍÓÚáéíóúñ0-9])?)[»\"]?",
        re.UNICODE,
    ),
    re.compile(
        r"(?:project_name|nombre del proyecto)\s*[:=]\s*[\"']?([^\"'\n,]{2,80})",
        re.IGNORECASE,
    ),
    re.compile(
        r"^##\s*Estimaci[oó]n:\s*(.+)$",
        re.IGNORECASE | re.MULTILINE,
    ),
)

_SCOPE_MAX_LEN = 8000


def _combined_text(
    user_text: str,
    result: EstimationResult | None,
) -> str:
    parts = [user_text or ""]
    if result is not None:
        parts.append(result.summary or "")
        for phase in result.phases:
            parts.append(phase.name)
            parts.append(phase.summary)
    return "\n".join(parts)


def _extract_technologies(text: str) -> list[str]:
    found: list[str] = []
    seen_lower: set[str] = set()
    for tech in _KNOWN_TECHNOLOGIES:
        if re.search(rf"(?<!\w){re.escape(tech)}(?!\w)", text, re.IGNORECASE):
            key = tech.lower()
            if key not in seen_lower:
                seen_lower.add(key)
                found.append(tech)
    return found


def _extract_team_size(text: str) -> int | None:
    for pattern in _TEAM_SIZE_PATTERNS:
        match = pattern.search(text)
        if match:
            size = int(match.group(1))
            if 1 <= size <= 500:
                return size
    return None


def _extract_project_name(text: str) -> str | None:
    for pattern in _PROJECT_NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            name = match.group(1).strip(" .,:;-")
            if 2 <= len(name) <= 128:
                return name
    return None


def _extract_scope(
    user_text: str,
    result: EstimationResult | None,
) -> str | None:
    """Prefer the structured summary; fall back to a short user snippet."""
    if result is not None and result.summary:
        scope = result.summary.strip()
        return scope[:_SCOPE_MAX_LEN] if scope else None
    snippet = (user_text or "").strip()
    if not snippet:
        return None
    # First paragraph / first ~400 chars as a coarse scope seed.
    first_para = snippet.split("\n\n", 1)[0].strip()
    return first_para[:400] if first_para else None


def extract_metadata_from_turn(
    *,
    user_text: str,
    result: EstimationResult | None = None,
) -> ProjectMetadata:
    """Parse facts from the latest user message and LLM estimation."""
    text = _combined_text(user_text, result)
    return ProjectMetadata(
        project_name=_extract_project_name(text),
        assumed_team_size=_extract_team_size(text),
        mentioned_technologies=_extract_technologies(text),
        agreed_scope=_extract_scope(user_text, result),
    )


def merge_project_metadata(
    current: ProjectMetadata,
    incoming: ProjectMetadata,
) -> ProjectMetadata:
    """Merge without wiping known facts: scalars prefer non-None; techs union."""
    tech_map: dict[str, str] = {
        t.lower(): t for t in current.mentioned_technologies
    }
    for tech in incoming.mentioned_technologies:
        tech_map.setdefault(tech.lower(), tech)

    return ProjectMetadata(
        project_name=incoming.project_name or current.project_name,
        assumed_team_size=(
            incoming.assumed_team_size
            if incoming.assumed_team_size is not None
            else current.assumed_team_size
        ),
        mentioned_technologies=list(tech_map.values()),
        agreed_scope=incoming.agreed_scope or current.agreed_scope,
    )


def update_project_metadata(
    current: ProjectMetadata,
    *,
    user_text: str,
    result: EstimationResult,
) -> ProjectMetadata:
    """Extract facts from the turn and merge them into ``current``."""
    extracted = extract_metadata_from_turn(user_text=user_text, result=result)
    return merge_project_metadata(current, extracted)
