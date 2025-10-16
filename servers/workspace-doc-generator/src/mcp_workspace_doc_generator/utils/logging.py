# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/utils/logging.py
from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path
import yaml

# Keep the format simple; we'll place key/vals directly in the message string.
_DEFAULT_FMT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

def setup_logging() -> None:
    """
    Load logging.yaml if present; fall back to basicConfig.
    LOG_LEVEL env can override root and console handler levels.
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    here = Path(__file__).resolve()
    base = here.parent.parent  # mcp_workspace_doc_generator/
    cfg = base / "config" / "logging.yaml"

    if cfg.exists():
        with cfg.open("r", encoding="utf-8") as f:
            cfg_dict = yaml.safe_load(f) or {}
        try:
            cfg_dict.setdefault("root", {}).setdefault("level", log_level)
            handlers = cfg_dict.get("handlers", {})
            if "console" in handlers:
                handlers["console"]["level"] = log_level
            logging.config.dictConfig(cfg_dict)
            return
        except Exception:
            pass

    logging.basicConfig(level=log_level, format=_DEFAULT_FMT)