from contextlib import asynccontextmanager
import logging
import os

import structlog
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.routers import estimations

def configure_logging():
    """Dual config: readable console in development, JSON in production."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    shared_processors = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.EventRenamer("msg"),
    ]

    if os.environ.get("ENV") == "production":
        # Production: JSON output for observability tool ingestion
        structlog.configure(
            processors=shared_processors + [
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, log_level)
            ),
        )
    else:
        # Development: colored console output, human-readable
        structlog.configure(
            processors=shared_processors + [
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, log_level)
            ),
        )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    configure_logging()
    log = structlog.get_logger()
    settings = get_settings()
    log.info("application_started", environment=settings.APP_ENV)
    yield
    log.info("application_shutdown")

app = FastAPI(
    title="Estimador CAG",
    lifespan=lifespan,
    description=(
        "API para generar estimaciones de proyectos de software a partir de "
        "transcripciones de reuniones. Utiliza contexto embebido (CAG) con "
        "ejemplos de referencia inyectados directamente en el prompt del LLM."
    ),
    version="0.1.0",
)

app.include_router(estimations.router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "estimador-cag"}


def main():
    import uvicorn


    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
