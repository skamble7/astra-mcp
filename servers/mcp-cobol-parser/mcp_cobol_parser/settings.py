# File: servers/mcp-cobol-parser/mcp_cobol_parser/settings.py
from __future__ import annotations
import os
import pathlib
import logging
from datetime import datetime, timezone
from pydantic_settings import BaseSettings
from pydantic import Field
from .logging import configure_root_logging

configure_root_logging()
log = logging.getLogger("mcp.cobol.settings")

class Settings(BaseSettings):
    # paging & workers
    PAGE_SIZE: int = Field(default=100)
    MAX_PAGE_SIZE: int = Field(default=500)
    WORKERS: int = Field(default=8)

    # cache & logging
    CACHE_DIR: str = Field(default=os.getenv("CACHE_DIR", ".cache"))
    LOG_LEVEL: str = Field(default=os.getenv("LOG_LEVEL", "INFO"))

    # Java + parsers (pull from env)
    JAVA_HOME: str | None = Field(default=os.getenv("JAVA_HOME"))
    CB2XML_JAR: str | None = Field(default=os.getenv("CB2XML_JAR"))
    CB2XML_CP: str | None = Field(default=os.getenv("CB2XML_CP"))
    CB2XML_MAIN: str | None = Field(default=os.getenv("CB2XML_MAIN"))

    PROLEAP_JAR: str | None = Field(default=os.getenv("PROLEAP_JAR"))
    PROLEAP_CP: str | None = Field(default=os.getenv("PROLEAP_CP"))
    # IMPORTANT: your Renova bridge main class is `com.renova.proleap.CLI`
    PROLEAP_MAIN: str | None = Field(default=os.getenv("PROLEAP_MAIN", "com.renova.proleap.CLI"))

    # “real parser or nothing”
    STRICT_PROLEAP: bool = Field(default=os.getenv("STRICT_PROLEAP", "1") not in ("0","false","False"))
    STRICT_CB2XML: bool = Field(default=os.getenv("STRICT_CB2XML", "1") not in ("0","false","False"))

    PARSER_VERSION_PROLEAP: str = Field(default=os.getenv("PARSER_VERSION_PROLEAP", "proleap@unknown"))
    PARSER_VERSION_CB2XML: str = Field(default=os.getenv("PARSER_VERSION_CB2XML", "cb2xml@unknown"))

    class Config:
        extra = "ignore"

    def __init__(self, **data):
        super().__init__(**data)
        # ensure cache dir
        pathlib.Path(self.CACHE_DIR).mkdir(parents=True, exist_ok=True)
        logging.getLogger().setLevel(self.LOG_LEVEL.upper())
        log.info("Cache dir: %s", self.CACHE_DIR)
        log.info("STRICT_PROLEAP=%s STRICT_CB2XML=%s", self.STRICT_PROLEAP, self.STRICT_CB2XML)

        # Helpful visibility on configured jars
        def _ok(p: str | None) -> str:
            if not p:
                return "None"
            return f"{p} (exists={os.path.exists(p)})"

        log.info("CB2XML: JAR=%s CP=%s MAIN=%s", _ok(self.CB2XML_JAR), self.CB2XML_CP or "", self.CB2XML_MAIN or "")
        log.info("PROLEAP: JAR=%s CP=%s MAIN=%s", _ok(self.PROLEAP_JAR), self.PROLEAP_CP or "", self.PROLEAP_MAIN or "")


def make_run_id() -> str:
    # timestamp-only run id
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"cpr_{ts}"