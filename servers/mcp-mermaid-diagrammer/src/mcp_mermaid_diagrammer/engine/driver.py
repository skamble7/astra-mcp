from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..models.diagram_instance import DiagramInstanceLike
from .json_utils import minify_json, split_artifact_for_prompt
from .sanity import (
    build_view_header,
    sanitize_mermaid,
    is_valid_mermaid,
    normalize_mindmap,
    normalize_sequence,
    normalize_flowchart,
)
from ..utils.logging import preview, want_verbose_llm

log = logging.getLogger("mcp.mermaid.engine.driver")

LLMCallable = Callable[[str, str, float, int], Awaitable[str]]

def _default_system_for_view(view_header: str) -> str:
    vh = view_header
    if vh == "sequenceDiagram":
        return (
            "You output Mermaid 'sequenceDiagram' only. "
            "Declare participants with safe IDs (letters, digits, underscores). "
            "If an original label has spaces/hyphens, map to a safe ID and declare: "
            'participant SAFE as \"Original\". '
            "Every message MUST include text after the arrow, like: A->>B: call. "
            "No prose. No code fences."
        )
    if vh == "mindmap":
        return (
            "You output Mermaid 'mindmap' only. "
            "Exactly one root line below the 'mindmap' directive. "
            "Use indentation (two spaces per level) for hierarchy. "
            "Never use arrows (-->). "
            "No prose. No code fences."
        )
    # default flowchart
    return (
        "You output Mermaid 'flowchart TD' only. "
        "Use stable node IDs (letters, digits, underscores). "
        "Put human-readable names in labels. "
        "No prose. No code fences."
    )

def _default_user_for_view(view_header: str, artifact_json_min: str, extra_prompt: Optional[str]) -> str:
    extra = f"\nAdditional guidance:\n{extra_prompt}\n" if extra_prompt else ""
    if view_header == "sequenceDiagram":
        return (
            "VIEW: sequenceDiagram\n"
            "Derive participants and messages from obvious interactions in the JSON "
            "(e.g., paragraphs + performs, calls, io_ops). "
            "Ensure each arrow has a message after ':'. "
            f"{extra}"
            "Artifact JSON:\n" + artifact_json_min
        )
    if view_header == "mindmap":
        return (
            "VIEW: mindmap\n"
            "Pick a stable root name from the JSON like program_id/name/title. "
            "Represent hierarchy using indentation only.\n"
            f"{extra}"
            "Artifact JSON:\n" + artifact_json_min
        )
    return (
        "VIEW: flowchart TD\n"
        "Create nodes for key items in the JSON and edges for obvious relationships "
        "(e.g., performs edges between paragraphs). "
        "Every node must have a non-empty label; do not emit empty nodes like H().\n"
        f"{extra}"
        "Artifact JSON:\n" + artifact_json_min
    )

async def generate_diagrams_llm_only(
    *,
    artifact: Dict[str, Any],
    views: List[str],
    temperature: float,
    max_tokens: int,
    llm_call: LLMCallable,   # required
) -> List[DiagramInstanceLike]:
    """
    LLM-only generation for the requested views over the given artifact.
    """
    if not views:
        views = ["flowchart"]

    out: List[DiagramInstanceLike] = []

    for view in views:
        header = build_view_header(view)
        data_chunks = split_artifact_for_prompt(artifact, view=view)
        log.debug("engine.chunks", extra={
            "view": view,
            "header": header,
            "chunks": len(data_chunks),
            "first_chunk_size": len(minify_json(data_chunks[0][1])) if data_chunks else 0,
        })

        sys_prompt = _default_system_for_view(header)
        user_prompt_first = _default_user_for_view(header, minify_json(data_chunks[0][1]), extra_prompt=None)

        composed_parts: List[str] = []

        for idx, (_label, chunk) in enumerate(data_chunks, start=1):
            is_first = idx == 1

            rules = [
                "Output Mermaid only. No prose. No code fences.",
                "If this is NOT the first chunk, DO NOT include the diagram directive; only append lines that fit under the same diagram.",
            ]
            if header == "mindmap":
                rules += [
                    "Mindmap must have exactly ONE root below the 'mindmap' line.",
                    "Indent children by two spaces per level.",
                    "Do NOT use arrows like 'A --> B'.",
                ]
            elif header == "sequenceDiagram":
                rules += [
                    "Every message MUST have text after the arrow, e.g., 'A->>B: call'.",
                    "Avoid spaces/hyphens in actor IDs; map to safe IDs and use aliases.",
                ]
            elif header.lower().startswith("flowchart"):
                rules += [
                    "Every node must have a non-empty label; do not emit empty nodes like H().",
                ]

            rules_text = "\n".join(f"- {x}" for x in rules)
            user_prompt = (
                (user_prompt_first if is_first else "")
                + ("" if is_first else "\nAppend only (no directive).")
                + f"\nConstraints:\n{rules_text}\n"
                + f"\nArtifact JSON for this chunk:\n{minify_json(chunk)}"
            )

            if want_verbose_llm():
                log.info("engine.llm.request.verbose", extra={
                    "view": view,
                    "chunk_index": idx,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "system_preview": preview(sys_prompt),
                    "user_preview": preview(user_prompt),
                })
            else:
                log.info("engine.llm.request", extra={
                    "view": view,
                    "chunk_index": idx,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                })

            text = await llm_call(sys_prompt, user_prompt, temperature, max_tokens)

            s = sanitize_mermaid(text or "")
            log.info("engine.llm.response", extra={
                "view": view,
                "chunk_index": idx,
                "len": len(s),
                "preview": preview(s, 600),
            })

            if not is_first:
                if header.lower().startswith("flowchart"):
                    for h in ("flowchart TD", "flowchart LR", "flowchart BT", "flowchart RL"):
                        if s.startswith(h):
                            s = s[len(h):].lstrip("\n")
                elif s.startswith("sequenceDiagram"):
                    s = s[len("sequenceDiagram"):].lstrip("\n")
                elif s.startswith("mindmap"):
                    s = s[len("mindmap"):].lstrip("\n")
            composed_parts.append(s)

        # Merge + normalize
        merged = []
        for j, part in enumerate(composed_parts, start=1):
            if j > 1:
                if part.startswith("sequenceDiagram"):
                    part = part[len("sequenceDiagram"):].lstrip("\n")
                elif part.startswith("mindmap"):
                    part = part[len("mindmap"):].lstrip("\n")
                elif part.startswith(("flowchart TD", "flowchart LR", "flowchart BT", "flowchart RL")):
                    part = part.split("\n", 1)[1] if "\n" in part else ""
            merged.append(part)
        final = "\n".join(merged).strip()
        if not final.startswith(header):
            final = f"{header}\n{final}".strip()

        # Post-process and validate
        if header == "mindmap":
            final = normalize_mindmap(final)
        elif header == "sequenceDiagram":
            final = normalize_sequence(final)
        elif header.lower().startswith("flowchart"):
            final = normalize_flowchart(final)

        valid = is_valid_mermaid(final, view=view)
        if not valid:
            candidate = f"{header}\n{final}"
            if is_valid_mermaid(candidate, view=view):
                final = candidate
            else:
                log.warning("engine.output.invalid", extra={"view": view, "len": len(final), "preview": preview(final, 400)})
                continue

        log.info("engine.output.accepted", extra={"view": view, "len": len(final), "preview": preview(final, 600)})

        out.append(
            DiagramInstanceLike(
                recipe_id=None,
                view=view,
                language="mermaid",
                instructions=final,
                renderer_hints={"wrap": True},
                generated_from_fingerprint=None,
                prompt_rev=None,
                provenance=None,
            )
        )

    return out