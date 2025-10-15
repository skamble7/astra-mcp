from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional, List

from mcp.server.fastmcp import FastMCP

from ..engine.driver import generate_diagrams_llm_only
from ..models.diagram_instance import DiagramInstanceLike
from ..models.io_contracts import GenerateRequest, GenerateResponse
from ..settings import Settings
from ..engine.json_utils import minify_json
from ..utils.logging import preview, redact_env, want_verbose_inputs
from ..engine.sanity import build_view_header, sanitize_mermaid

log = logging.getLogger("mcp.mermaid.tools.generate")

DEFAULT_VIEWS: List[str] = ["flowchart"]

# ---------------- Dummy instruction builders (used when LLM is disabled) ----------------

def _dummy_flowchart(artifact: Dict[str, Any]) -> str:
    # Try to use paragraphs from COBOL artifacts; otherwise a minimal graph
    paras = (artifact or {}).get("paragraphs") or []
    names = [str((p or {}).get("name") or "").strip() for p in paras if str((p or {}).get("name") or "").strip()]
    names = names[:6]  # keep short
    if not names:
        return "flowchart TD\n  A[Start]\n  B[Work]\n  C[End]\n  A --> B\n  B --> C"
    lines = ["flowchart TD"]
    ids = []
    for i, n in enumerate(names):
        nid = f"N{i+1}"
        ids.append(nid)
        lines.append(f'  {nid}(["{n}"])')
    for i in range(len(ids) - 1):
        lines.append(f"  {ids[i]} --> {ids[i+1]}")
    return "\n".join(lines)

def _dummy_sequence(artifact: Dict[str, Any]) -> str:
    actors = []
    paras = (artifact or {}).get("paragraphs") or []
    for p in paras[:4]:
        nm = str((p or {}).get("name") or "").strip()
        if nm:
            actors.append(nm)
    if len(actors) < 2:
        actors = ["A", "B"]
    lines = ["sequenceDiagram"]
    # safe aliasing via build rules is handled downstream if needed
    for a in actors:
        lines.append(f'participant {a}')
    for i in range(len(actors) - 1):
        lines.append(f"{actors[i]}->>{actors[i+1]}: call")
    return "\n".join(lines)

def _dummy_mindmap(artifact: Dict[str, Any]) -> str:
    root = (
        artifact.get("program_id")
        or artifact.get("name")
        or artifact.get("title")
        or "MAIN"
    )
    paras = (artifact or {}).get("paragraphs") or []
    children = [str((p or {}).get("name") or "").strip() for p in paras if str((p or {}).get("name") or "").strip()]
    children = children[:6]
    lines = ["mindmap", f"  {root}"]
    for c in children:
        lines.append(f"    {c}")
    if not children:
        lines.append("    Node")
    return "\n".join(lines)

def _dummy_for_view(view: str, artifact: Dict[str, Any]) -> str:
    header = build_view_header(view)
    if header == "sequenceDiagram":
        return _dummy_sequence(artifact)
    if header == "mindmap":
        return _dummy_mindmap(artifact)
    # default to flowchart
    return _dummy_flowchart(artifact)

# ----------------------------------------------------------------------------------------

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

    # If LLM is enabled, prepare OpenAI client; otherwise we'll use dummy mode
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

    if not settings.enable_real_llm:
        log.info("tool.register.dummy_mode", extra={"reason": "ENABLE_REAL_LLM is false"})

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
        views = views or DEFAULT_VIEWS

        try:
            req = GenerateRequest(artifact=artifact, views=views, prompt=prompt)
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

        # ----- DUMMY MODE (LLM disabled) -----
        if not settings.enable_real_llm:
            diagrams = []
            for v in req.views:
                instr = _dummy_for_view(v, req.artifact)
                diagrams.append(
                    DiagramInstanceLike(
                        recipe_id=None,
                        view=v,
                        language="mermaid",
                        instructions=sanitize_mermaid(instr),
                        renderer_hints={"wrap": True},
                        generated_from_fingerprint=None,
                        prompt_rev=None,
                        provenance={"mode": "dummy"},
                    ).model_dump()
                )
            resp = GenerateResponse(diagrams=diagrams).model_dump()
            log.info("tool.response", extra={
                "took_ms": int((time.time() - t0) * 1000),
                "diagram_count": len(diagrams),
                "mode": "dummy",
            })
            return resp

        # ----- REAL LLM MODE -----
        if _llm_call is None:
            # If enable_real_llm is true but client failed to init, fail cleanly with dummy fallback
            log.warning("tool.execution.llm_unavailable_falling_back_to_dummy")
            diagrams = []
            for v in req.views:
                instr = _dummy_for_view(v, req.artifact)
                diagrams.append(
                    DiagramInstanceLike(
                        recipe_id=None,
                        view=v,
                        language="mermaid",
                        instructions=sanitize_mermaid(instr),
                        renderer_hints={"wrap": True},
                        generated_from_fingerprint=None,
                        prompt_rev=None,
                        provenance={"mode": "dummy-fallback"},
                    ).model_dump()
                )
            resp = GenerateResponse(diagrams=diagrams).model_dump()
            log.info("tool.response", extra={
                "took_ms": int((time.time() - t0) * 1000),
                "diagram_count": len(diagrams),
                "mode": "dummy-fallback",
            })
            return resp

        # inner shim to inject prompt into engine's first user message
        async def llm_with_prompt(system: str, user: str, temperature: float, max_tokens: int) -> str:
            if prompt:
                user = f"{user}\n\nUser guidance:\n{prompt}"
            return await _llm_call(system, user, temperature, max_tokens)

        try:
            diagrams_objs = await generate_diagrams_llm_only(
                artifact=req.artifact,
                views=req.views,
                temperature=settings.temperature,
                max_tokens=settings.max_tokens,
                llm_call=llm_with_prompt,
            )
            resp = GenerateResponse(diagrams=[d.model_dump() for d in diagrams_objs]).model_dump()
        except Exception as e:
            log.exception("tool.execution.failed_llm_mode_fallback_dummy", extra={"error": str(e)})
            # Gentle fallback even in LLM mode
            diagrams = []
            for v in req.views:
                instr = _dummy_for_view(v, req.artifact)
                diagrams.append(
                    DiagramInstanceLike(
                        recipe_id=None,
                        view=v,
                        language="mermaid",
                        instructions=sanitize_mermaid(instr),
                        renderer_hints={"wrap": True},
                        generated_from_fingerprint=None,
                        prompt_rev=None,
                        provenance={"mode": "dummy-on-error"},
                    ).model_dump()
                )
            resp = GenerateResponse(diagrams=diagrams).model_dump()

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
        })
        return resp