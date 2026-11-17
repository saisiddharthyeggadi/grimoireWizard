from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_service_role_key: str | None
    gemini_api_key: str | None
    llm_model: str
    supabase_anon_key: str | None = None
    auth_mode: str = "off"
    environment: str = "development"
    auth_dev_user_id: str = "00000000-0000-4000-8000-000000000001"
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @classmethod
    def from_environment(cls) -> Settings:
        load_dotenv(find_dotenv(usecwd=True))
        return cls(
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY"),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            llm_model=os.getenv(
                "LLM_MODEL",
                "gemini-4-hydrogen",
            ),
            auth_mode=os.getenv("AUTH_MODE", "off").strip().lower(),
            environment=os.getenv("ENV", "development").strip().lower(),
            auth_dev_user_id=os.getenv(
                "AUTH_DEV_USER_ID", "00000000-0000-4000-8000-000000000001"
            ),
            cors_origins=tuple(
                origin.strip()
                for origin in os.getenv(
                    "API_CORS_ORIGINS",
                    "http://localhost:5173,http://127.0.0.1:5173",
                ).split(",")
                if origin.strip()
            ),
        )

    def validate_supabase(self) -> None:
        if not self.supabase_url or not self.supabase_service_role_key:
            raise RuntimeError(
                "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY for the backend."
            )
        if self.supabase_service_role_key.startswith("sb_publishable_"):
            raise RuntimeError(
                "SUPABASE_SERVICE_ROLE_KEY must be a server-side secret key."
            )

    def validate_auth(self) -> None:
        if self.auth_mode not in {"off", "on"}:
            raise RuntimeError("AUTH_MODE must be either 'off' or 'on'.")
        if self.auth_mode == "off" and self.environment == "production":
            raise RuntimeError("AUTH_MODE=off is not permitted in production.")
        try:
            UUID(self.auth_dev_user_id)
        except ValueError as error:
            raise RuntimeError("AUTH_DEV_USER_ID must be a UUID.") from error
        if self.auth_mode == "on" and (
            not self.supabase_url or not self.supabase_anon_key
        ):
            raise RuntimeError(
                "Set SUPABASE_URL and SUPABASE_ANON_KEY when AUTH_MODE=on."
            )

    def validate_production(self) -> None:
        self.validate_auth()
        if self.environment != "production":
            return
        self.validate_supabase()
        if not self.gemini_api_key:
            raise RuntimeError("Set GEMINI_API_KEY in production.")
        if not self.cors_origins or "*" in self.cors_origins:
            raise RuntimeError(
                "Set API_CORS_ORIGINS to explicit frontend origins in production."
            )
        if any(
            "localhost" in origin or "127.0.0.1" in origin
            for origin in self.cors_origins
        ):
            raise RuntimeError(
                "Localhost origins are not permitted in production CORS settings."
            )
