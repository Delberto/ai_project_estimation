from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas.schemas import EstimationRequest

PROMPTS_DIR = Path(__file__).parent


def _get_environment(version: str) -> Environment:
    template_dir = PROMPTS_DIR / "estimation" / version
    if not template_dir.is_dir():
        raise ValueError(f"Versión de prompt no encontrada: {version}")
    return Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_estimation_prompt(
    request: EstimationRequest,
    version: str = "v1",
) -> tuple[str, str]:
    env = _get_environment(version)
    context = {
        "request": request,
        "description": request.description,
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
    }
    system = env.get_template("system.j2").render(**context)
    user = env.get_template("user.j2").render(**context)
    return system.strip(), user.strip()
