"""Runtime settings, loaded from environment variables and `.env`."""

from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Provider:
    """An OpenAI-compatible upstream."""

    name: str
    base_url: str
    api_key: str


# Known OpenAI-compatible endpoints. Adding a provider is one entry here plus a key setting.
PROVIDER_BASE_URLS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    shoji_provider: str = "groq"
    shoji_upstream_timeout: float = 60.0
    # Retries for connection failures and 5xx responses, before any response is sent.
    shoji_upstream_retries: int = 1
    shoji_retry_backoff: float = 0.5
    # Used only when a request omits `model`.
    shoji_default_model: str | None = None

    # Redact personal data before forwarding and restore it in replies. Off = pass-through.
    shoji_redact: bool = True
    # Detections scoring below this are ignored (e.g. a bare 91+mobile run as Aadhaar, 0.4).
    shoji_min_score: float = 0.5

    # Encrypted placeholder vault; unset key = no vault (see shoji/vault.py).
    shoji_vault_key: str = ""
    shoji_vault_path: str = "shoji_vault.db"
    shoji_vault_ttl_hours: float = 24.0

    groq_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""

    def provider(self) -> Provider:
        name = self.shoji_provider.lower()
        if name not in PROVIDER_BASE_URLS:
            known = ", ".join(sorted(PROVIDER_BASE_URLS))
            raise ValueError(f"Unknown provider {name!r}; expected one of: {known}")
        api_key = getattr(self, f"{name}_api_key")
        return Provider(name=name, base_url=PROVIDER_BASE_URLS[name], api_key=api_key)
