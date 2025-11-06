# mcp-jcl-parser-legacylens

A fast **MCP** server that parses **JCL** using lightweight "LegacyLens" heuristics and emits:
- `cam.jcl.job`
- `cam.jcl.step`

## Run (HTTP)

```bash
MCP_TRANSPORT=streamable-http MCP_PORT=8876 python -m mcp_jcl_parser_legacylens