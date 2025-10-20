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

@dataclass
class Settings:
    # HTTP client
    http_timeout_seconds: float = 30.0
    http_follow_redirects: bool = True
    default_auth_bearer: str | None = None

    # Artifact cosmetics
    artifact_name_prefix: str = "Raina Input"
    artifact_tags: list[str] | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        timeout = _float_env("HTTP_TIMEOUT_SECONDS", 30.0)
        redirects = _truthy(os.getenv("HTTP_FOLLOW_REDIRECTS", "true"))
        bearer = (os.getenv("DEFAULT_AUTH_BEARER") or "").strip() or None
        name_prefix = os.getenv("ARTIFACT_NAME_PREFIX", "Raina Input").strip()
        tags_raw = (os.getenv("ARTIFACT_TAGS") or "inputs,raina,discovery").strip()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        return cls(
            http_timeout_seconds=timeout,
            http_follow_redirects=redirects,
            default_auth_bearer=bearer,
            artifact_name_prefix=name_prefix,
            artifact_tags=tags,
        )