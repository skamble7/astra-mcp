# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    config_ref: str = ""  # ConfigForge canonical ref; empty = dummy mode

    @property
    def enable_real_llm(self) -> bool:
        return bool(self.config_ref)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(config_ref=os.getenv("LLM_CONFIG_REF", ""))
