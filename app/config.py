from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Saathi Student Wellness"
    app_env: str = "development"
    app_base_url: str = "http://localhost:8000"
    app_timezone: str = "Asia/Kolkata"
    secret_key: str = "replace-this-development-secret-with-at-least-32-random-characters"
    cookie_secure: bool = False
    cookie_samesite: str = "strict"
    database_url: str = "postgresql+psycopg://wellness_app:local-app-change-me@localhost:5432/wellness"
    seed_demo_data: bool = True

    ai_api_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""

    # Embedding provider is separate from Pinecone: it converts text to the dense vector.
    embedding_api_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""

    pinecone_api_key: str = ""
    pinecone_index_name: str = "saathi-knowledge"
    pinecone_cloud: str = "aws"
    # Pinecone currently lists no India serverless region. us-east-1 works on Starter;
    # ap-southeast-1 (Singapore) requires a plan that supports it.
    pinecone_region: str = "us-east-1"
    pinecone_dimension: int = 384
    pinecone_query_vectors_enabled: bool = False
    pinecone_cross_border_approved: bool = False

    stt_api_base_url: str = ""
    stt_api_key: str = ""
    stt_model: str = ""
    voice_enabled: bool = True

    # These are Production Webhook URLs copied from the activated n8n Cloud workflows.
    n8n_enabled: bool = False
    n8n_webhook_url: str = ""
    n8n_report_webhook_url: str = ""
    n8n_health_webhook_url: str = ""
    n8n_webhook_secret: str = "change-this-n8n-webhook-secret"
    n8n_dispatch_interval_seconds: int = 10
    internal_api_secret: str = "change-this-internal-api-secret"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


def validate_settings() -> None:
    if settings.is_production:
        if settings.seed_demo_data:
            raise RuntimeError("SEED_DEMO_DATA must be false in production")
        if len(settings.secret_key) < 32 or settings.secret_key.startswith("replace-this"):
            raise RuntimeError("Set a unique SECRET_KEY of at least 32 characters in production")
        if not settings.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true in production behind HTTPS")
        if not settings.ai_api_base_url or not settings.ai_api_key or not settings.ai_model:
            raise RuntimeError("Production requires a configured AI provider; demo responses are disabled")
        if not settings.embedding_api_base_url or not settings.embedding_model:
            raise RuntimeError("Production requires a configured real embedding provider")
        if not settings.pinecone_api_key or not settings.pinecone_index_name:
            raise RuntimeError("Production requires a configured Pinecone index")
        if not settings.pinecone_query_vectors_enabled:
            raise RuntimeError("Enable Pinecone query vectors only after privacy review; see PINECONE_QUERY_VECTORS_ENABLED")
        if not settings.pinecone_cross_border_approved:
            raise RuntimeError("Pinecone query-vector processing needs documented cross-border/privacy approval before production")
        if settings.pinecone_dimension != 384:
            # The default embedding adapter asks for the configured dimension. Verify that
            # the selected embedding provider actually supports it before changing this.
            raise RuntimeError("The MVP embedding adapter expects 384 dimensions; update and verify the embedding provider before changing PINECONE_DIMENSION")
        if settings.voice_enabled and not settings.stt_api_base_url:
            raise RuntimeError("VOICE_ENABLED requires a configured speech-to-text provider in production")
        if settings.internal_api_secret.startswith("change-this") or len(settings.internal_api_secret) < 32:
            raise RuntimeError("Set INTERNAL_API_SECRET to a unique 32+ character value in production")
        if not settings.n8n_enabled:
            raise RuntimeError("Production requires the reviewed n8n Cloud notification integration to be enabled; do not deploy with case notifications disabled")
        if settings.n8n_enabled:
            if not (settings.n8n_webhook_url and settings.n8n_report_webhook_url and settings.n8n_health_webhook_url):
                raise RuntimeError("N8N_ENABLED requires all three published n8n Cloud Production Webhook URLs")
            if settings.n8n_webhook_secret.startswith("change-this") or len(settings.n8n_webhook_secret) < 32:
                raise RuntimeError("Set a unique N8N_WEBHOOK_SECRET when n8n Cloud is enabled")


settings = Settings()
