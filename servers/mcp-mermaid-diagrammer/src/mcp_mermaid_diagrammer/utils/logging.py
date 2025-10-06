from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict

# ---------- small helpers ----------

def preview(s: str | bytes | Any, n: int = 300) -> str:
    try:
        if isinstance(s, bytes):
            s = s.decode("utf-8", "replace")
        s = str(s)
    except Exception:
        return "<unprintable>"
    s = s.strip()
    return s if len(s) <= n else (s[: n - 20] + "... <truncated>")

def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}

def want_verbose_inputs() -> bool:
    return _truthy(os.getenv("LOG_VERBOSE_INPUTS"))

def want_verbose_llm() -> bool:
    return _truthy(os.getenv("LOG_VERBOSE_LLM"))

def redact_env(s: str) -> str:
    """Minimal redaction for accidental secret leakage in logs."""
    import re
    try:
        s2 = re.sub(r"(sk-[a-zA-Z0-9_\-]{8,})", "sk-***REDACTED***", s)
        s2 = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)([A-Za-z0-9_\-]{6,})", r"\1***REDACTED***", s2)
        return s2
    except Exception:
        return s

# ---------- logging setup ----------

_STD_ATTRS = {
    "name","msg","args","levelname","levelno","pathname","filename","module","exc_info",
    "exc_text","stack_info","lineno","funcName","created","msecs","relativeCreated",
    "thread","threadName","processName","process","message","asctime"
}

class ExtraJSONFormatter(logging.Formatter):
    """
    Format: "YYYY-mm-dd HH:MM:SS.mmm | message | {json of extras}"
    """
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        # Build timestamp with millis (no %f)
        base_dt = self.formatTime(record, datefmt="%Y-%m-%d %H:%M:%S")
        ts = f"{base_dt}.{int(record.msecs):03d}"

        # Collect extras
        extras = {k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS}

        base = f"{ts} | {record.message}"
        if extras:
            try:
                j = json.dumps(extras, ensure_ascii=False, default=str)
            except Exception:
                j = '{"_format_error":"<unserializable extras>"}'
            return f"{base} | {j}"
        return base

def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    try:
        lvl = getattr(logging, level, logging.INFO)
    except Exception:
        lvl = logging.INFO

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(ExtraJSONFormatter())  # <-- remove datefmt with %f
    root = logging.getLogger()
    if not getattr(root, "_mcp_logging_configured", False):
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(lvl)
        root._mcp_logging_configured = True  # type: ignore[attr-defined]