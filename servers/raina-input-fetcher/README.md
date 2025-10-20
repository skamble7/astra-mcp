# MCP: Raina Input Fetcher

Fetches a Raina input JSON (AVC/FSS/PSS) from a given URL, validates against the registry schema
`cam.inputs.raina`, and returns a persist-ready artifact payload (wrapped under `artifacts`).

## Tools

- `raina.input.fetch`
  - **params**: `{ "url": "https://...", "name": "optional title", "auth_bearer": "optional" }`
  - **returns**: `{ "artifacts": [ { kind_id: "cam.inputs.raina", data: { inputs: {...} }, ... } ] }`

## Run (stdio)

```bash
uv pip install -e servers/raina-input-fetcher
MCP_TRANSPORT=stdio \
LOG_LEVEL=INFO \
mcp-raina-input-fetcher