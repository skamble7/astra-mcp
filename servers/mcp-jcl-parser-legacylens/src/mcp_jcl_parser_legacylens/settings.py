#servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/settings.py
from __future__ import annotations
import os
import pathlib
import logging
from pydantic_settings import BaseSettings
from pydantic import Field

def _configure_root_logging(level: str | None = None) -> None:
    lvl = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    root = logging.getLogger()
    if getattr(root, "_astra_logging_configured", False):
        root.setLevel(lvl)
        return
    handler = logging.StreamHandler()
    fmt = "%(asctime)s | %(levelname)s | %(name)s: %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    root.handlers[:] = [handler]
    root.setLevel(lvl)
    setattr(root, "_astra_logging_configured", True)

_configure_root_logging()
log = logging.getLogger("mcp.jcl.settings")

class Settings(BaseSettings):
    # paging & workers
    PAGE_SIZE: int = Field(default=100)
    MAX_PAGE_SIZE: int = Field(default=500)
    WORKERS: int = Field(default=8)

    # cache & logging
    CACHE_DIR: str = Field(default=os.getenv("CACHE_DIR", "/app/.cache"))
    LOG_LEVEL: str = Field(default=os.getenv("LOG_LEVEL", "INFO"))

    # service name (optional)
    SERVICE_NAME: str = Field(default=os.getenv("SERVICE_NAME", "mcp.jcl.parser.legacylens"))

    # parsing heuristics
    LEGACYLENS_DIALECT: str | None = Field(default=os.getenv("LEGACYLENS_DIALECT", "zos"))
    LEGACYLENS_STRICT: bool = Field(default=os.getenv("LEGACYLENS_STRICT", "true").lower() in {"1","true","yes"})
    LEGACYLENS_MAX_JOB_BYTES: int = Field(default=int(os.getenv("LEGACYLENS_MAX_JOB_BYTES", "2097152")))  # 2MiB

    class Config:
        extra = "ignore"

    def __init__(self, **data):
        super().__init__(**data)
        pathlib.Path(self.CACHE_DIR).mkdir(parents=True, exist_ok=True)
        logging.getLogger().setLevel(self.LOG_LEVEL.upper())
        log.info("Cache dir: %s", self.CACHE_DIR)
        log.info("LEGACYLENS_STRICT=%s DIALECT=%s", self.LEGACYLENS_STRICT, self.LEGACYLENS_DIALECT)