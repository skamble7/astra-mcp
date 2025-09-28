"""Opinionated JSON logging configuration for MCP servers."""

import logging
import sys
from typing import Any, Dict, Optional

try:
    import structlog
except ImportError:
    structlog = None


def configure_logging(
    level: str = "INFO",
    service_name: Optional[str] = None,
    structured: bool = True,
) -> None:
    """Configure logging for MCP servers.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        service_name: Name of the service for structured logs
        structured: Whether to use structured JSON logging
    """
    log_level = getattr(logging, level.upper())
    
    if structured and structlog:
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer()
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            context_class=dict,
            cache_logger_on_first_use=True,
        )
        
        # Configure stdlib logging
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=log_level,
        )
    else:
        # Fallback to simple logging
        logging.basicConfig(
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            stream=sys.stdout,
            level=log_level,
        )


def get_logger(name: str, **context: Any) -> logging.Logger:
    """Get a logger instance with optional context.
    
    Args:
        name: Logger name
        **context: Additional context to bind to the logger
        
    Returns:
        Configured logger instance
    """
    if structlog:
        logger = structlog.get_logger(name)
        if context:
            logger = logger.bind(**context)
        return logger
    else:
        return logging.getLogger(name)


def add_context(**context: Any) -> Dict[str, Any]:
    """Add context to the current logger.
    
    Args:
        **context: Context key-value pairs
        
    Returns:
        Context dictionary
    """
    return context