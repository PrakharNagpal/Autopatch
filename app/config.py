"""Central settings loaded from environment / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    devin_api_key: str = ""
    github_token: str = ""
    github_owner: str = ""
    github_repo: str = "superset-fork"
    github_webhook_secret: str = ""

    daily_acu_budget: float = 50.0
    per_session_acu_cap: float = 10.0

    database_path: str = "./data/remediation.db"
    api_host: str = "0.0.0.0"
    api_port: int = 8080


settings = Settings()
