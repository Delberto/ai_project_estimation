from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    LLM_PROVIDER: str = "openai"
    OPENAI_MODEL: str = "gpt-4o-mini"
    USD_TO_MXN_RATE: float = 18.0
    APP_ENV: str = "development"

    class Config:
        env_file = ".env"


settings = Settings()
#@url_cache
def get_settings() -> Settings:
    """Return cached application settings (singleton)."""
    return Settings()