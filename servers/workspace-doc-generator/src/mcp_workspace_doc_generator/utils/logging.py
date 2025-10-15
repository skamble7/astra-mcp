# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/utils/logging.py
from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path
import yaml

_DEFAULT_FMT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

def setup_logging() -> None:
    """
    Load logging.yaml if present; fall back to basicConfig.
    LOG_LEVEL env can override root and console handler levels.
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    here = Path(__file__).resolve()
    # .../src/mcp_workspace_doc_generator/utils/logging.py
    base = here.parent.parent  # mcp_workspace_doc_generator/
    cfg = base / "config" / "logging.yaml"

    if cfg.exists():
        with cfg.open("r", encoding="utf-8") as f:
            cfg_dict = yaml.safe_load(f) or {}
        # Apply LOG_LEVEL override if provided
        try:
            cfg_dict.setdefault("root", {}).setdefault("level", log_level)
            # also bump console handler if present
            handlers = cfg_dict.get("handlers", {})
            if "console" in handlers:
                handlers["console"]["level"] = log_level
            logging.config.dictConfig(cfg_dict)
            return
        except Exception:
            # Fall through to basic config below
            pass

    logging.basicConfig(level=log_level, format=_DEFAULT_FMT)