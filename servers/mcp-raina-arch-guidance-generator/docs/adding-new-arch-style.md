# Developer Guide: Adding a New Architecture Style Tool

This guide explains how to extend `mcp-raina-arch-guidance-generator` with a new architecture style (e.g., `event_streaming`, `serverless`, `ml_platform`) and how to switch the storage backend from Garage to AWS S3.

---

## 1. Overview

Every architecture style is self-contained under `arch_styles/<style_name>/`:

```
arch_styles/
├── microservices/
│   ├── config.yaml     ← artifact deps, output kind, doc metadata
│   └── prompts.yaml    ← retrieval protocol + LLM system prompt
└── data_engineering/
    ├── config.yaml
    └── prompts.yaml
```

`base_generator.py` reads these files at runtime. Adding a new style requires **zero changes** to `base_generator.py`.

---

## 2. Step-by-Step: Adding a New Architecture Style

### Step 1 — Create `arch_styles/<style>/config.yaml`

```yaml
# arch_styles/event_streaming/config.yaml

# CAM artifact kind that this generator produces
output_kind: cam.governance.event_streaming_arch_guidance

# Output file name for the uploaded Markdown document
output_filename: event-streaming-architecture-guidance.md

# MIME type of the output (always text/markdown)
output_mime_type: text/markdown

# Artifact paths fetched during auto-paging (default: narratives + diagrams)
# Use "narratives" (not "data") — narratives are token-efficient prose summaries.
auto_page_paths:
  - narratives
  - diagrams

# Tags attached to the output artifact
tags:
  - architecture
  - guidance
  - event-streaming

# Hard dependency artifact kinds — all must exist in the workspace.
# If any are missing, the generator logs a warning and notes gaps in the document.
depends_on:
  hard:
    - cam.asset.raina_input
    - cam.catalog.event_catalog
    - cam.domain.bounded_context_map
    - cam.architecture.event_flow_diagram
    - cam.contract.event_schema
    # ... add all required kinds for this style
```

**Key rules:**
- `output_kind` must match the artifact kind registered in the artifact service.
- `auto_page_paths` should always include `narratives` and `diagrams` (not `data`).
- `depends_on.hard` lists the artifact kinds the LLM needs to author a complete document. Missing kinds are noted as gaps rather than aborting generation.

---

### Step 2 — Create `arch_styles/<style>/prompts.yaml`

Two top-level keys are required:

```yaml
# arch_styles/event_streaming/prompts.yaml

protocol_preamble: |
  You are generating a comprehensive architecture guidance document for a workspace.
  You will first receive an artifact_index. You will then receive artifact slices in batches.

  OUTPUT MUST ALWAYS BE ONE JSON OBJECT (no prose).

  Two allowed shapes:
  1) Ask for more details:
  { "requests": [ { "artifact_id":"...", "paths":["narratives","diagrams"], "max_chars": 14000 } ], "notes":"..." }
  2) Produce final:
  { "final": { "name":"...", "description":"...", "filename":"...", "mime_type":"text/markdown", "tags":[...], "content":"...markdown...", "covered_artifact_ids":[...], "coverage_map": { "<artifact_id>": { "kind":"...", "used_in_sections":[...], "key_points":[...] } } } }

  CRITICAL COVERAGE RULES:
  - You MUST base the document on ALL artifacts.
  - You may NOT produce final until you have been given slices for every artifact.
  - In final, `covered_artifact_ids` must match ALL artifact IDs exactly.

  ARTIFACT REPRESENTATION NOTES:
  - Each artifact slice contains a `narratives` field with LLM-generated prose summaries. Use this as your primary information source.
  - Raw `data` (JSON) is NOT sent.
  - When requesting artifact slices, always request `paths: ["narratives", "diagrams"]`.

  DIAGRAM RULES:
  - Embed every diagram verbatim as a fenced mermaid code block.
  - Place each diagram immediately after the section that discusses the artifact it came from.

system: |
  You are to author a comprehensive **Architecture Guidance Document** for an *event streaming*
  platform as the lead architect instructing delivery teams.

  # Grounding sources (MUST cite both)
  1) `=== RUN INPUTS (authoritative, from request.inputs) ===`
  2) `=== DEPENDENCIES (discovered artifacts) ===`

  # Output CONTRACT (STRICT)
  - Output exactly one JSON object. No text before or after.
  - The JSON MUST include:
    - `name`: "Event Streaming Architecture Guidance"
    - `description`: one-line summary
    - `filename`: "event-streaming-architecture-guidance.md"
    - `mime_type`: "text/markdown"
    - `tags`: ["architecture","guidance","event-streaming"]
    - `content`: valid GitHub-Flavored Markdown string

  # Document SECTIONS (REQUIRED)
  1. Executive Summary
  2. Architecture Overview
  3. Event Catalog
  # ... define all required sections for this style

  # Self-Validation CHECKLIST
  - [ ] Output is a single JSON object
  - [ ] `content` field is a string starting with `# Event Streaming Architecture Guidance`
  - [ ] All diagrams are inside fenced ```mermaid blocks
  - [ ] Required sections 1–N all present

  Now produce the JSON.

  === RUN INPUTS (authoritative, from request.inputs) ===
  {{RUN_INPUTS}}

  === DEPENDENCIES (discovered artifacts) ===
  {{DEPENDENCIES}}
```

**Key rules for `prompts.yaml`:**
- `protocol_preamble` is prepended to every multi-turn retrieval session. Copy the CRITICAL COVERAGE RULES and ARTIFACT REPRESENTATION NOTES verbatim — these control LLM retrieval behavior.
- `system` is the final generation prompt. It receives `{{RUN_INPUTS}}` (workspace inputs/constraints) and `{{DEPENDENCIES}}` (artifact index + slices) substituted at runtime.
- Define all required sections in the system prompt. The LLM validates against this checklist before emitting JSON.

---

### Step 3 — Create the Tool Function

Create `src/mcp_raina_arch_guidance_generator/tools/event_streaming_guidance.py`:

```python
# tools/event_streaming_guidance.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from ..models.params import GenerateGuidanceParams
from ..settings import Settings
from .base_generator import ArchGuidanceGenerator

log = logging.getLogger("mcp.raina.arch.guidance.event_streaming")

_STYLE_DIR = Path(__file__).resolve().parent.parent / "arch_styles" / "event_streaming"


async def generate_event_streaming_arch_guidance(params: GenerateGuidanceParams) -> Dict[str, Any]:
    """
    Generate a cam.governance.event_streaming_arch_guidance artifact from the workspace
    artifacts produced by the Event Streaming Architecture Discovery Pack.
    """
    settings = Settings.from_env()
    log.info(
        "tool.call workspace_id=%s output_kind=cam.governance.event_streaming_arch_guidance "
        "llm_enabled=%s config_ref=%s",
        params.workspace_id,
        settings.enable_real_llm,
        settings.config_ref,
    )
    generator = ArchGuidanceGenerator(style_dir=_STYLE_DIR, settings=settings)
    return await generator.generate(params.workspace_id)
```

---

### Step 4 — Register the Tool in `server.py`

Add the import and three tool registrations (async start, status poll, blocking):

```python
# In server.py — add import
from .tools.event_streaming_guidance import generate_event_streaming_arch_guidance

# --- job runner ---
async def _run_event_streaming_guidance_job(job_id: str, workspace_id: str) -> None:
    job = _JOBS[job_id]
    job["status"] = "running"
    job["progress"] = 10.0
    job["message"] = "Generating event streaming architecture guidance document…"
    try:
        params = GenerateGuidanceParams(workspace_id=workspace_id)
        result = await generate_event_streaming_arch_guidance(params)
        job["status"] = "done"
        job["progress"] = 100.0
        job["message"] = "Event streaming architecture guidance document generated."
        job["result"] = result
        job["artifacts"] = result.get("artifacts", [])
    except Exception as e:
        log.exception("job.failed job_id=%s", job_id)
        job["status"] = "error"
        job["message"] = "Generation failed."
        job["error"] = f"{e.__class__.__name__}: {e}"


# --- async start tool ---
@mcp.tool(
    name="event_streaming.arch.guidance.start",
    title="Start Event Streaming Architecture Guidance Generation",
)
async def event_streaming_arch_guidance_start(workspace_id: str) -> dict:
    """Queue a background job to generate event streaming architecture guidance."""
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {"status": "queued", "progress": 0.0, "message": "Queued", "workspace_id": workspace_id}
    asyncio.get_running_loop().create_task(_run_event_streaming_guidance_job(job_id, workspace_id))
    log.info("job.start job_id=%s workspace_id=%s", job_id, workspace_id)
    return {"job_id": job_id, "status": "queued", "progress": 0.0, "message": "Queued"}


# --- status poll tool ---
@mcp.tool(
    name="event_streaming.arch.guidance.status",
    title="Check Event Streaming Architecture Guidance Generation Job",
)
async def event_streaming_arch_guidance_status(job_id: str) -> dict:
    """Poll a background event streaming guidance generation job by job_id."""
    job = _JOBS.get(job_id)
    if not job:
        return {"job_id": job_id, "status": "error", "error": "Unknown job_id", "message": "Job not found."}
    out: dict = {"job_id": job_id, "status": job.get("status"), "progress": job.get("progress"), "message": job.get("message")}
    if job.get("status") == "done":
        out["result"] = job.get("result")
        out["artifacts"] = job.get("artifacts")
    if job.get("status") == "error":
        out["error"] = job.get("error")
    return out


# --- blocking tool ---
@mcp.tool(
    name="generate_event_streaming_arch_guidance",
    title="Generate Event Streaming Architecture Guidance (blocking)",
)
async def tool_generate_event_streaming_arch_guidance(workspace_id: str) -> dict:
    """Generate a cam.governance.event_streaming_arch_guidance artifact (blocking call)."""
    log.info("tool.call name=generate_event_streaming_arch_guidance workspace_id=%s", workspace_id)
    params = GenerateGuidanceParams(workspace_id=workspace_id)
    return await generate_event_streaming_arch_guidance(params)
```

That's it. No changes to `base_generator.py`, `settings.py`, or any shared utility.

---

## 3. Switching Storage: Garage → AWS S3

The server uses `boto3` for all storage operations and already supports both Garage (S3-compatible) and native AWS S3. Switching is purely configuration — no code changes needed.

### Environment Variable Changes

| Variable | Garage (local) | AWS S3 |
|---|---|---|
| `S3_ENDPOINT_URL` | `http://garage:3900` | *(unset — omit entirely)* |
| `S3_BUCKET` | `astra-docs` | `your-bucket-name` |
| `S3_PREFIX` | `arch-guidance-docs` | `arch-guidance-docs` |
| `S3_ACCESS_KEY` | `astra-docs-key` | AWS Access Key ID |
| `S3_SECRET_KEY` | `<garage secret>` | AWS Secret Access Key |
| `S3_REGION` | *(unset or `garage`)* | `us-east-1` (or your bucket region) |
| `S3_PUBLIC_BASE_URL` | `http://localhost:3902/astra-docs` | *(unset, or CloudFront URL)* |
| `S3_PUBLIC_READ` | `true` | `true` or `false` (see ACL note) |
| `S3_PRESIGN_BASE_URL` | *(unset)* | *(unset)* |

### What Happens Internally

When `S3_ENDPOINT_URL` is **unset**, `boto3` routes requests to the real AWS endpoint using virtual-hosted-style addressing (e.g., `https://your-bucket.s3.us-east-1.amazonaws.com/key`). When `S3_ENDPOINT_URL` **is set**, path-style addressing is used (required by Garage/MinIO).

This logic lives in `utils/storage.py::_build_client`:

```python
endpoint = endpoint_override or settings.s3_endpoint_url
addressing_style = "path" if endpoint else "auto"
```

### ACL / Public Read Note

AWS S3 buckets have **Block Public Access** enabled by default. If `S3_PUBLIC_READ=true`, the server sets `ACL=public-read` on uploaded objects. This will fail unless:

1. Block Public Access is disabled on the bucket **and** the bucket policy allows public reads, **or**
2. You use presigned URLs instead (set `S3_PUBLIC_READ=false` and unset `S3_PUBLIC_BASE_URL`).

For presigned URL delivery (recommended for private buckets):
- Set `S3_PUBLIC_READ=false`
- Leave `S3_PUBLIC_BASE_URL` unset
- The generator will fall back to `generate_presigned_url` for the `download_url` field

### Download URL Behavior

| Config | Download URL format |
|---|---|
| `S3_PUBLIC_BASE_URL` set | `{base}/{bucket}/{key}` (stable, permanent) |
| Unset + `S3_ENDPOINT_URL` set | `{endpoint}/{bucket}/{key}` (Garage path URL) |
| Unset + no endpoint (AWS) | Presigned SigV4 URL (expires per `S3_PRESIGN_EXPIRES_SECONDS`) |

### Docker Compose Example (AWS S3)

```yaml
mcp-raina-arch-guidance-generator:
  build: ../servers/mcp-raina-arch-guidance-generator
  ports: ["8004:8004"]
  environment:
    MCP_TRANSPORT: streamable-http
    MCP_PORT: 8004
    SERVICE_NAME: mcp.raina.arch.guidance.generator
    LLM_CONFIG_REF: ${LLM_CONFIG_REF}
    ARTIFACT_SERVICE_URL: http://host.docker.internal:9020
    CONFIG_FORGE_URL: http://host.docker.internal:8040
    # AWS S3 — no S3_ENDPOINT_URL
    S3_BUCKET: your-bucket-name
    S3_PREFIX: arch-guidance-docs
    S3_REGION: us-east-1
    S3_ACCESS_KEY: ${AWS_ACCESS_KEY_ID}
    S3_SECRET_KEY: ${AWS_SECRET_ACCESS_KEY}
    S3_PUBLIC_READ: "false"
    OUTPUT_DIR: /tmp/arch-guidance-docs
  extra_hosts:
    - host.docker.internal:host-gateway
```

### IAM Permissions Required

The AWS credentials need the following S3 permissions on the target bucket:

```json
{
  "Effect": "Allow",
  "Action": [
    "s3:PutObject",
    "s3:GetObject",
    "s3:PutObjectAcl"
  ],
  "Resource": "arn:aws:s3:::your-bucket-name/arch-guidance-docs/*"
}
```

Remove `s3:PutObjectAcl` if `S3_PUBLIC_READ=false`.
