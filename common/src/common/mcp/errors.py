"""MCP-specific error definitions."""

from typing import Optional, Dict, Any


class MCPError(Exception):
    """Base exception for MCP-related errors."""
    
    def __init__(
        self,
        message: str,
        code: int = -32603,
        data: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data or {}
    
    def to_json_rpc_error(self, request_id: Optional[str] = None) -> Dict[str, Any]:
        """Convert to JSON-RPC error response."""
        error_response = {
            "jsonrpc": "2.0",
            "error": {
                "code": self.code,
                "message": self.message,
            },
            "id": request_id,
        }
        
        if self.data:
            error_response["error"]["data"] = self.data
        
        return error_response


class ValidationError(MCPError):
    """Error for input validation failures."""
    
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=-32602, data=data)


class ToolError(MCPError):
    """Error for tool execution failures."""
    
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=-32001, data=data)


class ResourceError(MCPError):
    """Error for resource access failures."""
    
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=-32002, data=data)


class NotFoundError(MCPError):
    """Error for missing resources or tools."""
    
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=-32003, data=data)


class PermissionError(MCPError):
    """Error for permission/authorization failures."""
    
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=-32004, data=data)


class TimeoutError(MCPError):
    """Error for operation timeouts."""
    
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=-32005, data=data)


class RateLimitError(MCPError):
    """Error for rate limiting."""
    
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=-32006, data=data)


class InternalError(MCPError):
    """Error for internal server errors."""
    
    def __init__(self, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=-32603, data=data)


def handle_exception(
    exception: Exception,
    request_id: Optional[str] = None,
    default_message: str = "Internal server error"
) -> Dict[str, Any]:
    """Convert any exception to an MCP error response.
    
    Args:
        exception: Exception to convert
        request_id: Request ID for the response
        default_message: Default error message
        
    Returns:
        JSON-RPC error response
    """
    if isinstance(exception, MCPError):
        return exception.to_json_rpc_error(request_id)
    
    # Convert common exceptions to appropriate MCP errors
    if isinstance(exception, ValueError):
        error = ValidationError(str(exception))
    elif isinstance(exception, FileNotFoundError):
        error = NotFoundError(str(exception))
    elif isinstance(exception, PermissionError):
        error = PermissionError(str(exception))
    elif isinstance(exception, TimeoutError):
        error = TimeoutError(str(exception))
    else:
        # Generic internal error
        error = InternalError(default_message, data={"original_error": str(exception)})
    
    return error.to_json_rpc_error(request_id)