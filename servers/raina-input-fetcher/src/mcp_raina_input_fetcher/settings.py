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
    http_timeout_seconds: float = 30.0
    http_follow_redirects: bool = True
    default_auth_bearer: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            http_timeout_seconds=_float_env("HTTP_TIMEOUT_SECONDS", 30.0),
            http_follow_redirects=_truthy(os.getenv("HTTP_FOLLOW_REDIRECTS", "true")),
            default_auth_bearer=(os.getenv("DEFAULT_AUTH_BEARER") or "").strip() or None,
        )
