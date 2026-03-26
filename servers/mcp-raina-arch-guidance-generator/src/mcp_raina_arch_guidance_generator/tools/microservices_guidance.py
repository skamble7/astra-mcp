# tools/microservices_guidance.py
#
# MCP tool: generate_microservices_arch_guidance
#
# Instantiates ArchGuidanceGenerator with the microservices arch style and exposes
# the tool function used by server.py.
#
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from ..models.arch_guidance import GenerateGuidanceResult
from ..models.params import GenerateGuidanceParams
from ..settings import Settings
from .base_generator import ArchGuidanceGenerator

log = logging.getLogger("mcp.raina.arch.guidance.microservices")

# Arch style directory — relative to this file's location
_STYLE_DIR = Path(__file__).resolve().parent.parent / "arch_styles" / "microservices"


async def generate_microservices_arch_guidance(params: GenerateGuidanceParams) -> Dict[str, Any]:
    """
    Generate a cam.governance.microservices_arch_guidance artifact from the workspace
    artifacts produced by the Microservices Architecture Discovery Pack.

    Steps:
    1. Load microservices arch style config + prompts from arch_styles/microservices/
    2. Fetch workspace artifacts from the artifact service
    3. Validate all hard-dependency artifact kinds are present
    4. Run multi-turn agentic LLM retrieval to generate the guidance document
    5. Inject Mermaid diagrams from artifact metadata
    6. Upload the Markdown document to Garage / S3
    7. Return the cam.governance.microservices_arch_guidance artifact payload

    Returns:
        dict with "artifacts" key containing one cam.governance.microservices_arch_guidance artifact
    """
    settings = Settings.from_env()
    log.info(
        "tool.call workspace_id=%s output_kind=cam.governance.microservices_arch_guidance "
        "llm_enabled=%s config_ref=%s",
        params.workspace_id,
        settings.enable_real_llm,
        settings.config_ref,
    )
    generator = ArchGuidanceGenerator(style_dir=_STYLE_DIR, settings=settings)
    return await generator.generate(params.workspace_id)
