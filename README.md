# Astra MCP

A collection of Model Context Protocol (MCP) servers providing various tools and capabilities.

## Architecture

This monorepo contains:

- **common/**: Shared Python library for all servers
- **servers/**: Individual MCP servers with isolated environments
  - **git-repo-snapshot/**: Server for cloning and managing git repositories
- **examples/**: Client integration examples
- **scripts/**: Development and utility scripts
- **compose/**: Docker composition files for running servers

## Development

### Setup

Run the development setup script:

```bash
./scripts/dev-setup.sh
```

### Running Servers

#### STDIO Mode (Default)
```bash
./scripts/run-stdio.sh git-repo-snapshot
```

#### SSE Mode (HTTP Server)
```bash
./scripts/run-sse.sh git-repo-snapshot
```

### Formatting and Linting

```bash
./scripts/fmt.sh
```

## License

See [LICENSE](LICENSE) file for details.