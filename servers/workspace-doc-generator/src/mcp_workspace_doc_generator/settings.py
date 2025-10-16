# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/settings.py
from __future__ import annotations
import os
from dataclasses import dataclass

def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}

def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

@dataclass
class Settings:
    # LLM
    llm_provider: str = "none"
    llm_model: str = "none"
    temperature: float = 0.2
    max_tokens: int = 1600
    enable_real_llm: bool = False

    # LLM networking/retry controls
    llm_request_timeout: float = 120.0         # seconds
    llm_max_retries: int = 3
    llm_retry_backoff_initial: float = 0.75
    llm_retry_backoff_max: float = 8.0

    # Services
    artifact_service_url: str = "http://localhost:9020"

    # S3 / GarageHQ
    s3_enabled: bool = False
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str | None = None
    s3_prefix: str = "workspace-docs"
    s3_public_base_url: str | None = None   # e.g. http://localhost:3900/astradocs  OR http://localhost:3900/{bucket}
    s3_public_read: bool = True

    # Pre-signed URL controls
    s3_force_signed: bool = False                  # if true, always return pre-signed URL
    s3_presign_ttl_seconds: int = 7 * 24 * 3600   # default 7 days
    s3_presign_base_url: str | None = None        # optionally rewrite scheme+host (e.g., http://localhost:3900)

    @classmethod
    def from_env(cls) -> "Settings":
        # LLM core
        provider = os.getenv("LLM_PROVIDER", "none")
        model = os.getenv("LLM_MODEL", "none")
        temp = _float_env("LLM_TEMPERATURE", 0.2)
        max_toks = _int_env("LLM_MAX_TOKENS", 1600)
        enable = _truthy(os.getenv("ENABLE_REAL_LLM")) and provider.lower() == "openai" and model != "none"

        # LLM networking/retry
        llm_request_timeout = _float_env("LLM_TIMEOUT_SECONDS", 180.0)
        llm_max_retries = _int_env("LLM_MAX_RETRIES", 4)
        llm_retry_backoff_initial = _float_env("LLM_RETRY_BACKOFF_INITIAL", 0.8)
        llm_retry_backoff_max = _float_env("LLM_RETRY_BACKOFF_MAX", 10.0)

        # Artifact service
        svc_url = os.getenv("ARTIFACT_SERVICE_URL", "http://localhost:9020").strip() or "http://localhost:9020"

        # S3 / Garage (accept either S3_* or GARAGE_* aliases)
        s3_endpoint_url = (os.getenv("S3_ENDPOINT_URL") or os.getenv("GARAGE_S3_ENDPOINT") or "").strip() or None
        s3_region = (os.getenv("S3_REGION") or os.getenv("GARAGE_S3_REGION") or "garage").strip()
        s3_access_key = (os.getenv("S3_ACCESS_KEY") or os.getenv("GARAGE_S3_ACCESS_KEY") or "").strip() or None
        s3_secret_key = (os.getenv("S3_SECRET_KEY") or os.getenv("GARAGE_S3_SECRET_KEY") or "").strip() or None
        s3_bucket = (os.getenv("S3_BUCKET") or os.getenv("GARAGE_S3_BUCKET") or "").strip() or None
        s3_prefix = (os.getenv("S3_PREFIX") or os.getenv("GARAGE_S3_PREFIX") or "workspace-docs").strip()
        s3_public_base_url = (os.getenv("S3_PUBLIC_BASE_URL") or os.getenv("GARAGE_PUBLIC_BASE_URL") or "").strip() or None
        s3_public_read = _truthy(os.getenv("S3_PUBLIC_READ", "true"))

        # Pre-signed URL controls
        s3_force_signed = _truthy(os.getenv("S3_FORCE_SIGNED"))
        s3_presign_ttl_seconds = _int_env("S3_PRESIGN_TTL_SECONDS", 7 * 24 * 3600)
        s3_presign_base_url = (os.getenv("S3_PRESIGN_BASE_URL") or "").strip() or None

        # Enabled only if all required pieces are present
        s3_enabled = bool(s3_endpoint_url and s3_access_key and s3_secret_key and s3_bucket)

        return cls(
            llm_provider=provider,
            llm_model=model,
            temperature=temp,
            max_tokens=max_toks,
            enable_real_llm=enable,
            llm_request_timeout=llm_request_timeout,
            llm_max_retries=llm_max_retries,
            llm_retry_backoff_initial=llm_retry_backoff_initial,
            llm_retry_backoff_max=llm_retry_backoff_max,
            artifact_service_url=svc_url,
            s3_enabled=s3_enabled,
            s3_endpoint_url=s3_endpoint_url,
            s3_region=s3_region,
            s3_access_key=s3_access_key,
            s3_secret_key=s3_secret_key,
            s3_bucket=s3_bucket,
            s3_prefix=s3_prefix,
            s3_public_base_url=s3_public_base_url,
            s3_public_read=s3_public_read,
            s3_force_signed=s3_force_signed,
            s3_presign_ttl_seconds=s3_presign_ttl_seconds,
            s3_presign_base_url=s3_presign_base_url,
        )