from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/payments"
    redis_url: str = "redis://localhost:6379/0"
    max_retries: int = 3
    retry_delays_seconds: list[int] = [60, 300, 900]  # 1m, 5m, 15m

    class Config:
        env_file = ".env"


settings = Settings()
