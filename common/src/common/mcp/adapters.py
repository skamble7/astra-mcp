"""Thin wrappers for Model Context Protocol STDIO and SSE transports."""

import asyncio
import json
import sys
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Protocol, runtime_checkable

from ..logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class MCPServer(Protocol):
    """Protocol for MCP server implementations."""
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle an MCP request and return a response."""
        ...
    
    async def initialize(self) -> None:
        """Initialize the server."""
        ...
    
    async def shutdown(self) -> None:
        """Shutdown the server."""
        ...


class MCPTransport(ABC):
    """Base class for MCP transport adapters."""
    
    def __init__(self, server: MCPServer):
        self.server = server
        self.running = False
    
    @abstractmethod
    async def start(self) -> None:
        """Start the transport."""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport."""
        pass


class STDIOTransport(MCPTransport):
    """STDIO transport adapter for MCP."""
    
    def __init__(self, server: MCPServer):
        super().__init__(server)
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
    
    async def start(self) -> None:
        """Start the STDIO transport."""
        logger.info("Starting STDIO transport")
        
        # Initialize server
        await self.server.initialize()
        
        # Set up STDIO streams
        self.reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self.reader)
        
        loop = asyncio.get_event_loop()
        transport, _ = await loop.connect_read_pipe(
            lambda: protocol, sys.stdin
        )
        
        self.writer = asyncio.StreamWriter(
            transport=None,
            protocol=None,
            reader=None,
            loop=loop
        )
        
        # Replace with direct stdout writing
        self.running = True
        
        try:
            while self.running:
                # Read JSON-RPC message
                line = await self.reader.readline()
                if not line:
                    break
                
                try:
                    request = json.loads(line.decode().strip())
                    logger.debug("Received request", request_id=request.get("id"))
                    
                    # Handle request
                    response = await self.server.handle_request(request)
                    
                    # Send response
                    response_json = json.dumps(response, separators=(',', ':'))
                    sys.stdout.write(response_json + '\n')
                    sys.stdout.flush()
                    
                    logger.debug("Sent response", request_id=request.get("id"))
                    
                except json.JSONDecodeError as e:
                    logger.error("Invalid JSON received", error=str(e))
                    error_response = {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32700,
                            "message": "Parse error"
                        },
                        "id": None
                    }
                    response_json = json.dumps(error_response, separators=(',', ':'))
                    sys.stdout.write(response_json + '\n')
                    sys.stdout.flush()
                
                except Exception as e:
                    logger.error("Error handling request", error=str(e))
                    error_response = {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32603,
                            "message": "Internal error"
                        },
                        "id": request.get("id") if 'request' in locals() else None
                    }
                    response_json = json.dumps(error_response, separators=(',', ':'))
                    sys.stdout.write(response_json + '\n')
                    sys.stdout.flush()
        
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """Stop the STDIO transport."""
        if self.running:
            logger.info("Stopping STDIO transport")
            self.running = False
            await self.server.shutdown()


class SSETransport(MCPTransport):
    """Server-Sent Events transport adapter for MCP."""
    
    def __init__(self, server: MCPServer, host: str = "0.0.0.0", port: int = 8000):
        super().__init__(server)
        self.host = host
        self.port = port
        self.app: Optional[Any] = None
    
    async def start(self) -> None:
        """Start the SSE transport."""
        logger.info("Starting SSE transport", host=self.host, port=self.port)
        
        try:
            import uvicorn
            from fastapi import FastAPI, Request
            from fastapi.responses import StreamingResponse
        except ImportError:
            raise ImportError(
                "SSE transport requires FastAPI and uvicorn. "
                "Install with: pip install fastapi uvicorn"
            )
        
        # Initialize server
        await self.server.initialize()
        
        # Create FastAPI app
        self.app = FastAPI(title="MCP SSE Server")
        
        @self.app.post("/mcp")
        async def handle_mcp_request(request: Request):
            """Handle MCP request over HTTP."""
            try:
                request_data = await request.json()
                logger.debug("Received SSE request", request_id=request_data.get("id"))
                
                response = await self.server.handle_request(request_data)
                
                logger.debug("Sent SSE response", request_id=request_data.get("id"))
                return response
                
            except Exception as e:
                logger.error("Error handling SSE request", error=str(e))
                return {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": "Internal error"
                    },
                    "id": request_data.get("id") if 'request_data' in locals() else None
                }
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {"status": "healthy"}
        
        # Store app for potential external access
        self.running = True
    
    async def stop(self) -> None:
        """Stop the SSE transport."""
        if self.running:
            logger.info("Stopping SSE transport")
            self.running = False
            await self.server.shutdown()
    
    def get_app(self):
        """Get the FastAPI app instance for external use."""
        return self.app


def create_stdio_server(server: MCPServer) -> STDIOTransport:
    """Create a STDIO transport for an MCP server.
    
    Args:
        server: MCP server instance
        
    Returns:
        Configured STDIO transport
    """
    return STDIOTransport(server)


def create_sse_server(
    server: MCPServer,
    host: str = "0.0.0.0",
    port: int = 8000
) -> SSETransport:
    """Create an SSE transport for an MCP server.
    
    Args:
        server: MCP server instance
        host: Host to bind to
        port: Port to bind to
        
    Returns:
        Configured SSE transport
    """
    return SSETransport(server, host, port)


async def run_server(transport: MCPTransport) -> None:
    """Run an MCP server with the given transport.
    
    Args:
        transport: Transport adapter to use
    """
    try:
        await transport.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error("Server error", error=str(e))
        raise
    finally:
        await transport.stop()