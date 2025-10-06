# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/settings.py# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass

def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}

@dataclass
class Settings:
    llm_provider: str = "none"
    llm_model: str = "none"
    temperature: float = 0.1
    max_tokens: int = 1200
    enable_real_llm: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.getenv("LLM_PROVIDER", "none")
        model = os.getenv("LLM_MODEL", "none")
        try:
            temp = float(os.getenv("LLM_TEMPERATURE", "0.1"))
        except Exception:
            temp = 0.1
        try:
            max_toks = int(os.getenv("LLM_MAX_TOKENS", "1200"))
        except Exception:
            max_toks = 1200

        enable = _truthy(os.getenv("ENABLE_REAL_LLM")) and provider != "none" and model != "none"
        return cls(
            llm_provider=provider,
            llm_model=model,
            temperature=temp,
            max_tokens=max_toks,
            enable_real_llm=enable,
        )
