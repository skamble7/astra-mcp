from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional, List

from mcp.server.fastmcp import FastMCP

from ..engine.driver import generate_diagrams_llm_only
from ..models.io_contracts import GenerateRequest, GenerateResponse
from ..settings import Settings
from ..engine.json_utils import minify_json
from ..utils.logging import preview, redact_env, want_verbose_inputs

log = logging.getLogger("mcp.mermaid.tools.generate")

DEFAULT_VIEWS: List[str] = ["flowchart"]

def register_mermaid_generate(mcp: FastMCP) -> None:
    settings = Settings.from_env()
    log.info("tool.register", extra={
        "tool": "diagram.mermaid.generate",
        "llm_enabled": settings.enable_real_llm,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
    })

    _provider = (settings.llm_provider or "").strip().lower()
    _model = settings.llm_model
    _llm_call: Optional[Any] = None

    if settings.enable_real_llm and _provider == "openai":
        try:
            from openai import AsyncOpenAI  # type: ignore
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            client = AsyncOpenAI(api_key=api_key)

            async def _llm_call(system: str, user: str, temperature: float, max_tokens: int) -> str:
                _ = redact_env(system), redact_env(user)
                resp = await client.chat.completions.create(
                    model=_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return (resp.choices[0].message.content or "").strip()

            log.info("tool.register.llm_ready", extra={"provider": "OpenAI"})
        except Exception as e:
            log.error("tool.register.llm_init_failed", extra={"error": str(e)})
            _llm_call = None

    if _llm_call is None:
        log.error("tool.register.llm_disabled", extra={
            "hint": "Set ENABLE_REAL_LLM=true, LLM_PROVIDER=OpenAI, LLM_MODEL, and OPENAI_API_KEY."
        })
        async def _disabled_llm_call(*_args, **_kwargs) -> str:
            raise RuntimeError("LLM disabled or not initialized")
        _llm_call = _disabled_llm_call

    @mcp.tool(name="diagram.mermaid.generate", title="Generate Mermaid Diagrams")
    async def diagram_mermaid_generate(
        artifact: Dict[str, Any],
        views: Optional[List[str]] = None,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Simplified tool:
          - artifact: JSON payload to visualize
          - views: list of diagram views to produce (default: ["flowchart"])
          - prompt: optional extra user guidance for the LLM
        """
        t0 = time.time()

        try:
            req = GenerateRequest(artifact=artifact, views=views or DEFAULT_VIEWS, prompt=prompt)
            art_min = minify_json(req.artifact)
            if want_verbose_inputs():
                log.info("tool.request.verbose", extra={
                    "views": req.views,
                    "prompt_preview": preview(prompt or "", 300),
                    "artifact": req.artifact,
                    "artifact_size": len(art_min),
                })
            else:
                log.info("tool.request", extra={
                    "views": req.views,
                    "prompt_preview": preview(prompt or "", 120),
                    "artifact_preview": preview(art_min),
                    "artifact_size": len(art_min),
                })
        except Exception as e:
            log.exception("tool.request.invalid")
            return {"error": f"invalid_request: {e}", "diagrams": []}

        # inner shim to inject prompt into engine's first user message
        # (we keep it simple by temporarily passing prompt via closure)
        async def llm_with_prompt(system: str, user: str, temperature: float, max_tokens: int) -> str:
            # prepend extra guidance once
            if prompt:
                user = f"{user}\n\nUser guidance:\n{prompt}"
            return await _llm_call(system, user, temperature, max_tokens)

        try:
            diagrams = await generate_diagrams_llm_only(
                artifact=req.artifact,
                views=req.views or DEFAULT_VIEWS,
                temperature=settings.temperature,
                max_tokens=settings.max_tokens,
                llm_call=llm_with_prompt,  # required
            )
        except Exception as e:
            log.exception("tool.execution.failed")
            return {"error": f"generation_failed: {e}", "diagrams": []}

        resp = GenerateResponse(diagrams=[d.model_dump() for d in diagrams]).model_dump()

        previews = [
            {
                "view": d.get("view"),
                "language": d.get("language"),
                "len": len(d.get("instructions") or ""),
                "preview": preview(d.get("instructions") or "", 600),
            }
            for d in resp.get("diagrams", [])
        ]
        log.info("tool.response", extra={
            "took_ms": int((time.time() - t0) * 1000),
            "diagram_count": len(previews),
            "diagrams": previews,
        })

        return resp