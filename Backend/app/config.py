from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str
    database_url: str
    cors_origins: str = "http://localhost:5173"
    debug: bool = False
    frontend_base_url: str = "http://localhost:5173"

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_starter_price_id: str = ""
    stripe_pro_price_id: str = ""
    stripe_elite_price_id: str = ""

    # Email (Resend)
    resend_api_key: str = ""
    email_from_address: str = ""
    email_mode: str = "log"  # "log" (default, safe for local dev) | "send"

    @property
    def stripe_price_to_plan(self) -> dict[str, str]:
        return {
            self.stripe_starter_price_id: "starter",
            self.stripe_pro_price_id: "pro",
            self.stripe_elite_price_id: "elite",
        }

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse cors_origins — supports both comma-separated and JSON array."""
        import json
        val = self.cors_origins.strip()
        if val.startswith("["):
            try:
                return json.loads(val)
            except Exception:
                pass
        return [v.strip() for v in val.split(",") if v.strip()]


settings = Settings()