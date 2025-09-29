# File: servers/mcp-cobol-parser/mcp_cobol_parser/logging.py
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime, timezone

class _TzFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        # ISO-like timestamp in UTC for consistency
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

def configure_root_logging(level: str | None = None) -> None:
    """
    Central logging config used by settings.py.
    """
    lvl = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    root = logging.getLogger()
    # Clear handlers only once for idempotency
    if getattr(root, "_astra_logging_configured", False):
        root.setLevel(lvl)
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    fmt = "%(asctime)s | %(levelname)s | %(name)s: %(message)s"
    handler.setFormatter(_TzFormatter(fmt))
    root.handlers[:] = [handler]
    root.setLevel(lvl)
    setattr(root, "_astra_logging_configured", True)

    # Make uvicorn/fastapi logs follow the same handler/level
    for n in ("uvicorn", "uvicorn.error", "uvicorn.access", "mcp", "mcp.server"):
        logging.getLogger(n).setLevel(lvl)
        logging.getLogger(n).handlers[:] = [handler]