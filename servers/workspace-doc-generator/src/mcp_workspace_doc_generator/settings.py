# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/settings.py
from __future__ import annotations
import os
from dataclasses import dataclass

def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}

@dataclass
class Settings:
    # LLM
    llm_provider: str = "none"
    llm_model: str = "none"
    temperature: float = 0.2
    max_tokens: int = 1600
    enable_real_llm: bool = False

    # Services
    artifact_service_url: str = "http://localhost:9020"

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.getenv("LLM_PROVIDER", "none")
        model = os.getenv("LLM_MODEL", "none")
        try:
            temp = float(os.getenv("LLM_TEMPERATURE", "0.2"))
        except Exception:
            temp = 0.2
        try:
            max_toks = int(os.getenv("LLM_MAX_TOKENS", "1600"))
        except Exception:
            max_toks = 1600

        enable = _truthy(os.getenv("ENABLE_REAL_LLM")) and provider.lower() == "openai" and model != "none"
        svc_url = os.getenv("ARTIFACT_SERVICE_URL", "http://localhost:9020").strip() or "http://localhost:9020"

        return cls(
            llm_provider=provider,
            llm_model=model,
            temperature=temp,
            max_tokens=max_toks,
            enable_real_llm=enable,
            artifact_service_url=svc_url,
        )