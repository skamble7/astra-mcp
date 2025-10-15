# MCP: Workspace Document Generator (LLM)

Generates a workspace-wide document from artifacts and returns a `cam.asset.file_detail` artifact
describing the generated Markdown file. Uses OpenAI when enabled; otherwise falls back to a deterministic stub.

## Tool

`generate.workspace.document`
- **params**: `{ "workspace_id": "uuid", "prompt": "string" }`
- **returns**: `cam.asset.file_detail` JSON

## Artifact source

GET `${ARTIFACT_SERVICE_URL}/artifact/{workspace_id}?include_deleted=false&limit=50&offset=0`  
This server extracts only each artifact's **`data`** property and feeds the collection to the LLM.

Defaults: `ARTIFACT_SERVICE_URL=http://localhost:9020`

## LLM

- Toggle with `ENABLE_REAL_LLM=true|false`
- `LLM_PROVIDER=OpenAI`
- `LLM_MODEL=gpt-4o-mini` (or any available)
- Requires `OPENAI_API_KEY`

## Quickstart

```bash
uv pip install -e servers/workspace-doc-generator

# LLM on
ENABLE_REAL_LLM=true \
LLM_PROVIDER=OpenAI \
LLM_MODEL=gpt-4o-mini \
OPENAI_API_KEY=sk-... \
ARTIFACT_SERVICE_URL=http://localhost:9020 \
OUTPUT_DIR=/tmp/mcp-docs \
MCP_TRANSPORT=stdio \
mcp-workspace-doc-generator