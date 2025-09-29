# servers/mcp-cobol-parser/mcp_cobol_parser/parsers/proleap.py
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import logging
from typing import Any, Dict, List, Optional

from ..settings import Settings

logger = logging.getLogger("mcp.cobol.proleap")


def _classpath(jar: str, cp_extra: str | None) -> str:
    parts: List[str] = [jar]
    if cp_extra:
        parts.append(cp_extra)
    return ":".join([p for p in parts if p])


def _build_cmd(cbl_path: str, cfg: Settings) -> List[str]:
    """
    Prefer classpath+main (works for both bridges):
      - com.astra.proleap.JsonCli  -> richer JSON (programId, sourceFormat, divisions, paragraphs, copybooks_used, rawSource)
      - com.renova.proleap.CLI     -> minimal JSON (status, file)
    """
    jar = cfg.PROLEAP_JAR
    main = os.getenv("PROLEAP_MAIN", "") or (cfg.PROLEAP_MAIN or "")
    cp_extra = os.getenv("PROLEAP_CP", "") or (cfg.PROLEAP_CP or "")

    if not jar or not os.path.exists(jar):
        raise RuntimeError(f"ProLeap JAR missing or not configured: {jar!r}")
    if not main:
        raise RuntimeError("PROLEAP_MAIN not configured.")

    cp = _classpath(jar, cp_extra or None)
    return ["java", "-cp", cp, main, cbl_path]


def _extract_json_line(s: str) -> Optional[str]:
    """
    Be tolerant to any stray text: find the LAST JSON object line.
    Bridges print exactly ONE JSON object to stdout at the end.
    """
    s = (s or "").strip()
    if not s:
        return None
    if s.startswith("{") and s.endswith("}"):
        return s
    cand = None
    for line in s.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            cand = line
    return cand


def _get_timeout_seconds(env: dict) -> int:
    """
    Per-file Java timeout precedence:
      1) COBOL_JAVA_TIMEOUT_SEC
      2) PROLEAP_JAVA_TIMEOUT_SEC (legacy)
      3) default 60
    """
    raw = env.get("COBOL_JAVA_TIMEOUT_SEC") or env.get("PROLEAP_JAVA_TIMEOUT_SEC") or "60"
    try:
        val = int(raw)
    except Exception:
        val = 60
    return max(5, val)


def _add_hints_to_error(msg: str) -> str:
    # Helpful note for IMS EXEC DLI and some CICS oddities
    if "EXEC DLI" in msg:
        return f"{msg} [Hint: IMS/EXEC DLI statements are not supported by the stock ProLeap grammar.]"
    if "SEND-PLAIN-TEXT" in msg:
        return (f"{msg} [Hint: This looks like a CICS BMS macro form. "
                "The stock grammar doesn't accept 'SEND-PLAIN-TEXT' as a verb; "
                "you may need vendor extensions or to preprocess CICS macros.]")
    return msg


def _engine_from_env() -> str:
    main = os.getenv("PROLEAP_MAIN", "")
    if "com.astra.proleap.JsonCli" in main:
        return "JsonCli"
    if "com.renova.proleap.CLI" in main:
        return "RenovaCLI"
    return main or "unknown"


def _to_internal_obj_from_bridge(bridge_obj: dict, rel_file: str) -> dict:
    """
    Normalize the Java bridge output into the shape expected by normalize_program_obj().
    For JsonCli, pass through the richer details; for minimal CLI, return a skeletal object.
    """
    status = bridge_obj.get("status")
    if status != "ok":
        msg = bridge_obj.get("message", "unknown error")
        raise RuntimeError(_add_hints_to_error(str(msg)))

    engine = _engine_from_env()

    # Common fields
    program_id = (bridge_obj.get("programId") or bridge_obj.get("program_id") or "").strip().upper()
    source_format = bridge_obj.get("sourceFormat")

    # Start with a minimal shape and then enrich if fields are present
    obj: dict = {
        "program_id": program_id,
        "divisions": {},
        "paragraphs": [],
        "copybooks_used": [],
        "notes": [],
        "engine": engine,          # helpful marker for downstream/logs
    }

    # Pass through sourceFormat so the normalizer can record it as a note
    if source_format:
        obj["sourceFormat"] = source_format

    # If the bridge provided richer details, preserve them
    if isinstance(bridge_obj.get("divisions"), dict):
        obj["divisions"] = bridge_obj["divisions"]

    if isinstance(bridge_obj.get("paragraphs"), list):
        obj["paragraphs"] = bridge_obj["paragraphs"]

    # Accept either key and normalize casing to what the normalizer expects
    if isinstance(bridge_obj.get("copybooks_used"), list):
        obj["copybooks_used"] = bridge_obj["copybooks_used"]
    elif isinstance(bridge_obj.get("copybooks"), list):
        obj["copybooks_used"] = bridge_obj["copybooks"]

    # Keep rawSource EXACTLY named so normalize_program_obj can detect it
    if isinstance(bridge_obj.get("rawSource"), str):
        obj["rawSource"] = bridge_obj["rawSource"]

    # Add informational notes
    if "file" in bridge_obj and bridge_obj["file"] != rel_file:
        obj["notes"].append(f"resolvedFile={bridge_obj['file']}")

    return obj


def parse_program_with_proleap(cbl_path: str, cfg: Settings) -> Dict[str, Any]:
    """
    Invoke the ProLeap bridge and return a normalized JSON object ready for
    normalize_program_obj(). STRICT: raises on any issue.
    """
    cmd = _build_cmd(cbl_path, cfg)

    # Environment hints (source format, etc.)
    env = os.environ.copy()
    if "COBOL_SOURCE_FORMAT" not in env:
        env["COBOL_SOURCE_FORMAT"] = "FIXED"

    per_file_timeout = _get_timeout_seconds(env)
    pretty = " ".join(shlex.quote(p) for p in cmd)
    logger.info("ProLeap exec: %s (timeout=%ss)", pretty, per_file_timeout)

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=per_file_timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as te:
        dt = time.time() - t0
        logger.error("ProLeap timeout after %.2fs on %s", dt, cbl_path)
        raise RuntimeError(f"ProLeap timeout after {dt:.2f}s") from te
    except Exception as e:
        dt = time.time() - t0
        logger.exception("ProLeap spawn failed after %.2fs: %s", dt, e)
        raise RuntimeError("ProLeap spawn failed") from e

    dt = time.time() - t0
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    json_text = _extract_json_line(stdout)

    if proc.returncode != 0:
        if not json_text:
            logger.error(
                "ProLeap non-zero exit (%s) in %.2fs.\n--- stdout(400) ---\n%s\n--- stderr(400) ---\n%s",
                proc.returncode, dt, stdout[:400], stderr[:400]
            )
            raise RuntimeError("ProLeap returned non-JSON output.")
        try:
            raw = json.loads(json_text)
        except Exception:
            logger.error(
                "ProLeap non-zero exit (%s) + invalid JSON in %.2fs.\n--- stdout(400) ---\n%s\n--- stderr(400) ---\n%s",
                proc.returncode, dt, stdout[:400], stderr[:400]
            )
            raise RuntimeError("ProLeap returned invalid JSON.")
        if raw.get("status") != "ok":
            raise RuntimeError(_add_hints_to_error(str(raw.get("message", "unknown error"))))
        return _to_internal_obj_from_bridge(raw, rel_file=cbl_path)

    if not json_text:
        logger.error(
            "ProLeap returned non-JSON output in %.2fs.\n--- stdout(400) ---\n%s\n--- stderr(400) ---\n%s",
            dt, stdout[:400], stderr[:400]
        )
        raise RuntimeError("ProLeap returned non-JSON output.")
    try:
        raw = json.loads(json_text)
    except Exception as e:
        logger.error(
            "ProLeap JSON parse failed in %.2fs.\n--- stdout(400) ---\n%s\n--- stderr(400) ---\n%s",
            dt, stdout[:400], stderr[:400]
        )
        raise RuntimeError("ProLeap returned invalid JSON.") from e

    # Normalize bridge-specific shape to our internal shape
    obj = _to_internal_obj_from_bridge(raw, rel_file=cbl_path)
    logger.debug(
        "ProLeap ok in %.2fs for %s; engine=%s; program_id=%r; paras=%d; copybooks=%d",
        dt,
        cbl_path,
        obj.get("engine"),
        obj.get("program_id"),
        len(obj.get("paragraphs") or []),
        len(obj.get("copybooks_used") or []),
    )
    return obj