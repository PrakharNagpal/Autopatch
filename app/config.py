"""Central settings loaded from environment / .env file."""

import base64

from pydantic_settings import BaseSettings, SettingsConfigDict


def _extract_org_id(api_key: str) -> str:
    """Pull org-<id> out of a Devin API key (personal or service user)."""
    try:
        encoded = api_key.split("_", 2)[-1]
        pad = 4 - len(encoded) % 4
        decoded = base64.b64decode(encoded + "=" * pad).decode()
        # format: "email|<user>_org-<id>:..." or similar
        for part in decoded.replace("|", "_").split("_"):
            if part.startswith("org-"):
                return part.split(":")[0]
    except Exception:
        pass
    return ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    devin_api_key: str = ""
    # Service user token (cog_ prefix) with ManageBilling org permission.
    # Required for the v3 session cost endpoint. Create one in Devin settings.
    devin_service_key: str = ""
    github_token: str = ""
    github_owner: str = ""
    github_repo: str = "superset-fork"
    github_webhook_secret: str = ""

    daily_acu_budget: float = 50.0
    per_session_acu_cap: float = 10.0
    # Dollars per ACU — set to match your Devin plan rate
    acu_usd_rate: float = 2.25

    database_path: str = "./data/remediation.db"
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    @property
    def devin_org_id(self) -> str:
        """Org ID extracted from whichever key is available."""
        return (
            _extract_org_id(self.devin_service_key)
            or _extract_org_id(self.devin_api_key)
        )


settings = Settings()
