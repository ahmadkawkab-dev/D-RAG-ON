"""Environment-driven backend settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated server-side configuration.

    Browser clients never choose service hosts, filesystem paths, or model IDs.
    Production refuses to start with the development JWT secret.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RAG_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Local RAG API"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    connect_external_services_on_startup: bool = True

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "rag_app"
    mongodb_connect_timeout_ms: int = Field(default=5000, ge=500, le=60000)

    weaviate_host: str = "localhost"
    weaviate_http_port: int = Field(default=8080, ge=1, le=65535)
    weaviate_grpc_port: int = Field(default=50051, ge=1, le=65535)
    weaviate_secure: bool = False
    weaviate_collection: str = "DocumentChunks"

    ollama_host: str = "http://localhost:11434"
    embedding_model: str = "embeddinggemma"
    light_reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"
    heavy_reranker_model: str = "Qwen/Qwen3-Reranker-4B"
    answer_model: str = "qwen2.5:1.5b"
    rerank_device: str | None = None
    llm_request_timeout_seconds: float = Field(default=900.0, ge=1.0, le=3600.0)
    retrieve_k: int = Field(default=20, ge=1, le=200)
    top_n: int = Field(default=5, ge=1, le=50)
    hybrid_alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    relevance_threshold: float = Field(default=0.20, ge=0.0, le=1.0)

    keep_models_warm: bool = True
    fast_retrieve_k: int = Field(default=8, ge=1, le=50)
    fast_top_n: int = Field(default=3, ge=1, le=10)
    fast_query_max_words: int = Field(default=24, ge=5, le=100)
    fast_answer_max_tokens: int = Field(default=160, ge=32, le=1024)
    complex_answer_max_tokens: int = Field(default=640, ge=64, le=4096)
    fast_answer_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    complex_answer_timeout_seconds: float = Field(default=900.0, ge=60.0, le=900.0)
    answer_keep_alive: str = "30m"
    answer_context_chars_per_chunk: int = Field(default=1800, ge=200, le=10000)
    answer_cache_size: int = Field(default=128, ge=0, le=2048)

    jwt_secret_key: str = Field(
        default="dev-only-change-this-secret-key-before-production",
        min_length=32,
        repr=False,
    )
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)

    @model_validator(mode="after")
    def validate_runtime_contract(self) -> "Settings":
        if self.top_n > self.retrieve_k:
            raise ValueError("top_n cannot exceed retrieve_k")
        if self.fast_top_n > self.fast_retrieve_k:
            raise ValueError("fast_top_n cannot exceed fast_retrieve_k")
        if (
            self.environment == "production"
            and self.jwt_secret_key.startswith("dev-only-")
        ):
            raise ValueError("RAG_JWT_SECRET_KEY must be changed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
