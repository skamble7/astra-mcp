# mcp-raina-arch-guidance-generator

MCP server that generates an architecture guidance document from a workspace's discovered artifacts.

## Tools

| Tool | Description |
|------|-------------|
| `generate_microservices_arch_guidance` | Generates a `cam.governance.microservices_arch_guidance` artifact from workspace artifacts |

## Usage

```
generate_microservices_arch_guidance(workspace_id="<workspace-id>")
```

Returns a `cam.governance.microservices_arch_guidance` artifact with a full Markdown guidance document uploaded to Garage/S3.

## Configuration

See `.env.example` for all environment variables. Key settings:

- `ARTIFACT_SERVICE_URL` — artifact service base URL (default: `http://host.docker.internal:9020`)
- `LLM_CONFIG_REF` — ConfigForge LLM profile ref (required)
- `CONFIG_FORGE_URL` — ConfigForge service URL
- `S3_*` — Garage/S3 storage settings

## Extensibility

Architecture styles live in `src/mcp_raina_arch_guidance_generator/arch_styles/`. To add a new style (e.g., data engineering):

1. Create `arch_styles/data_engineering/config.yaml` — specify output kind, artifact dependencies, tags
2. Create `arch_styles/data_engineering/prompts.yaml` — write the system prompt and retrieval protocol
3. Register a new MCP tool in `server.py` pointing to the new style directory

No code changes to `base_generator.py` or `utils/` are required.
