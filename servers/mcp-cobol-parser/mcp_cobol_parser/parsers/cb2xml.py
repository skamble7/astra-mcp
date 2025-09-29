# File: servers/mcp-cobol-parser/mcp_cobol_parser/parsers/cb2xml.py
from __future__ import annotations
import os, subprocess, xmltodict
from typing import Any
from ..settings import Settings

def parse_copybook_with_cb2xml(copy_path: str, cfg: Settings) -> dict[str, Any]:
    jar = cfg.CB2XML_JAR
    if not jar or not os.path.exists(jar):
        raise RuntimeError("CB2XML_JAR not configured or missing.")

    # prefer classpath+main if provided (matches Renova variants)
    cp = os.getenv("CB2XML_CP")
    main = os.getenv("CB2XML_MAIN")

    if main and (cp or jar):
        classpath = ":".join([p for p in [jar, cp] if p])  # linux pathsep
        cmd = ["java", "-cp", classpath, main, copy_path]
    else:
        # assume jar is runnable
        cmd = ["java", "-jar", jar, copy_path]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"CB2XML failed: {proc.stderr[:800]}")

    # cb2xml sometimes prints XML on stdout; in some builds on stderr
    xml = proc.stdout if proc.stdout.strip().startswith("<") else proc.stderr
    if not xml.strip().startswith("<"):
        raise RuntimeError("CB2XML produced no XML output.")
    return xmltodict.parse(xml)
