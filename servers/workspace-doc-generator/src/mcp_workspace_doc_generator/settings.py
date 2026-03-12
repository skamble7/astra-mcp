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
    # LLM — ConfigForge ref; empty = LLM disabled
    config_ref: str = ""

    # LLM networking/retry controls (applied in the generation loop)
    llm_request_timeout: float = 120.0
    llm_max_retries: int = 3
    llm_retry_backoff_initial: float = 0.75
    llm_retry_backoff_max: float = 8.0

    @property
    def enable_real_llm(self) -> bool:
        return bool(self.config_ref)

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
    s3_public_base_url: str | None = None
    s3_public_read: bool = True

    # Pre-signed URL controls
    s3_force_signed: bool = False
    s3_presign_ttl_seconds: int = 7 * 24 * 3600
    s3_presign_base_url: str | None = None

    # -----------------------------------------
    # Option C++: server-driven retrieval paging
    # -----------------------------------------
    doc_max_turns: int = 10
    doc_request_max_items: int = 12
    doc_slice_max_chars: int = 14000
    doc_total_retrieved_max_chars: int = 180000

    # Index / preview controls
    doc_index_top_keys_limit: int = 40
    doc_large_array_preview_items: int = 40
    doc_large_object_preview_keys: int = 80

    # Server-driven auto paging:
    doc_auto_page_enabled: bool = True
    doc_auto_page_batch_size: int = 8
    doc_auto_page_paths: tuple[str, ...] = ("data", "diagrams")

    @classmethod
    def from_env(cls) -> "Settings":
        config_ref = os.getenv("LLM_CONFIG_REF", "")

        llm_request_timeout = _float_env("LLM_TIMEOUT_SECONDS", 180.0)
        llm_max_retries = _int_env("LLM_MAX_RETRIES", 4)
        llm_retry_backoff_initial = _float_env("LLM_RETRY_BACKOFF_INITIAL", 0.8)
        llm_retry_backoff_max = _float_env("LLM_RETRY_BACKOFF_MAX", 10.0)

        svc_url = os.getenv("ARTIFACT_SERVICE_URL", "http://localhost:9020").strip() or "http://localhost:9020"

        s3_endpoint_url = (os.getenv("S3_ENDPOINT_URL") or os.getenv("GARAGE_S3_ENDPOINT") or "").strip() or None
        s3_region = (os.getenv("S3_REGION") or os.getenv("GARAGE_S3_REGION") or "garage").strip()
        s3_access_key = (os.getenv("S3_ACCESS_KEY") or os.getenv("GARAGE_S3_ACCESS_KEY") or "").strip() or None
        s3_secret_key = (os.getenv("S3_SECRET_KEY") or os.getenv("GARAGE_S3_SECRET_KEY") or "").strip() or None
        s3_bucket = (os.getenv("S3_BUCKET") or os.getenv("GARAGE_S3_BUCKET") or "").strip() or None
        s3_prefix = (os.getenv("S3_PREFIX") or os.getenv("GARAGE_S3_PREFIX") or "workspace-docs").strip()
        s3_public_base_url = (os.getenv("S3_PUBLIC_BASE_URL") or os.getenv("GARAGE_PUBLIC_BASE_URL") or "").strip() or None
        s3_public_read = _truthy(os.getenv("S3_PUBLIC_READ", "true"))

        s3_force_signed = _truthy(os.getenv("S3_FORCE_SIGNED"))
        s3_presign_ttl_seconds = _int_env("S3_PRESIGN_TTL_SECONDS", 7 * 24 * 3600)
        s3_presign_base_url = (os.getenv("S3_PRESIGN_BASE_URL") or "").strip() or None

        s3_enabled = bool(s3_endpoint_url and s3_access_key and s3_secret_key and s3_bucket)

        # Retrieval env overrides
        doc_max_turns = _int_env("DOC_MAX_TURNS", 10)
        doc_request_max_items = _int_env("DOC_REQUEST_MAX_ITEMS", 12)
        doc_slice_max_chars = _int_env("DOC_SLICE_MAX_CHARS", 14000)
        doc_total_retrieved_max_chars = _int_env("DOC_TOTAL_RETRIEVED_MAX_CHARS", 180000)

        doc_index_top_keys_limit = _int_env("DOC_INDEX_TOP_KEYS_LIMIT", 40)
        doc_large_array_preview_items = _int_env("DOC_LARGE_ARRAY_PREVIEW_ITEMS", 40)
        doc_large_object_preview_keys = _int_env("DOC_LARGE_OBJECT_PREVIEW_KEYS", 80)

        doc_auto_page_enabled = _truthy(os.getenv("DOC_AUTO_PAGE_ENABLED", "true"))
        doc_auto_page_batch_size = _int_env("DOC_AUTO_PAGE_BATCH_SIZE", 8)

        return cls(
            config_ref=config_ref,
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
            doc_max_turns=doc_max_turns,
            doc_request_max_items=doc_request_max_items,
            doc_slice_max_chars=doc_slice_max_chars,
            doc_total_retrieved_max_chars=doc_total_retrieved_max_chars,
            doc_index_top_keys_limit=doc_index_top_keys_limit,
            doc_large_array_preview_items=doc_large_array_preview_items,
            doc_large_object_preview_keys=doc_large_object_preview_keys,
            doc_auto_page_enabled=doc_auto_page_enabled,
            doc_auto_page_batch_size=doc_auto_page_batch_size,
        )