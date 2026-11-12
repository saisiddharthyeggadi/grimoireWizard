from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_service_role_key: str | None
    llm_api_key: str | None
    llm_base_url: str | None
    llm_model: str
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @classmethod
    def from_environment(cls) -> Settings:
        load_dotenv(find_dotenv(usecwd=True))
        return cls(
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
            llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
            llm_base_url=os.getenv("LLM_BASE_URL"),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
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
