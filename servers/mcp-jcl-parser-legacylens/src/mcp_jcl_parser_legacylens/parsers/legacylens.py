# servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/parsers/legacylens.py
from __future__ import annotations
from typing import List, Dict, Any

# Robust imports for the LegacyLens JCL parser
JCLParser = None  # type: ignore[assignment]
_import_err: Exception | None = None
for modpath in ("legacylens_jcl_parser", "jcl_parser", "legacylens.jcl_parser"):
    try:
        _mod = __import__(modpath, fromlist=["JCLParser"])
        JCLParser = getattr(_mod, "JCLParser")
        break
    except Exception as e:  # noqa: BLE001
        _import_err = e
        continue
if JCLParser is None:
    raise ImportError(
        "Could not import JCLParser. Please ensure the 'legacylens-jcl-parser' package is installed."
    ) from _import_err

from ..settings import Settings
from ..hashing import sha256_text
from ..models.cam_jcl_job import CamJclJob, JclStep
from ..models.cam_jcl_step import CamJclStep
from ..models.jcl_shared import JclDD
from ..models.common import SourceRef

"""
LegacyLens adapter: uses `JCLParser` (legacylens-jcl-parser) to parse a JCL file and
convert it to our cam.jcl.job and cam.jcl.step artifacts.

Direction heuristics:
  - SYSOUT -> OUT
  - DISP contains NEW|OLD|MOD -> OUT
  - DISP contains SHR -> IN
  - DSN present -> IN
"""

def _infer_direction_from_params(params: Dict[str, Any]) -> str | None:
    if not params:
        return None
    norm = {str(k).strip().upper(): (str(v).strip() if v is not None else None)
            for k, v in params.items()}
    if "SYSOUT" in norm:
        return "OUT"
    disp = norm.get("DISP")
    if disp:
        disp_u = str(disp).upper()
        if any(k in disp_u for k in ("NEW", "OLD", "MOD")):
            return "OUT"
        if "SHR" in disp_u:
            return "IN"
    if "DSN" in norm:
        return "IN"
    return None

def parse_jcl_file(abs_path: str, relpath: str, cfg: Settings) -> Dict[str, Any]:
    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read(cfg.LEGACYLENS_MAX_JOB_BYTES)

    parser = JCLParser()
    parsed = parser.parse_file(abs_path)

    src = SourceRef(relpath=relpath, sha256=sha256_text(raw))
    jobs_out: List[CamJclJob] = []
    steps_out: List[CamJclStep] = []

    job_data: Dict[str, Any] = parsed.get("job") or {}
    job_name: str | None = job_data.get("name") if job_data else None

    steps_data: List[Dict[str, Any]] = parsed.get("steps") or []

    steps_cam: List[JclStep] = []
    for idx, step in enumerate(steps_data, start=1):
        step_name: str | None = step.get("name")
        seq = step.get("seq") or idx

        params: Dict[str, Any] = step.get("parameters") or {}
        params_u = {str(k).strip().upper(): v for k, v in params.items()}
        program = params_u.get("PGM") or (f"PROC({params_u['PROC']})" if "PROC" in params_u else None)
        condition = params_u.get("COND")

        dd_list: List[JclDD] = []
        for dd in (step.get("dd_statements") or []):
            dd_name = dd.get("name") or dd.get("ddname")
            dd_params: Dict[str, Any] = dd.get("parameters") or {}
            dsn = dd_params.get("DSN")
            if dsn is None and "SYSOUT" in dd_params:
                dsn = "SYSOUT"
            direction = _infer_direction_from_params(dd_params)
            dd_list.append(JclDD(ddname=dd_name, dataset=dsn, direction=direction))

        # Build the job's step model
        steps_cam.append(
            JclStep(
                step_name=step_name,
                seq=seq,
                program=program,
                condition=condition,
                dds=dd_list or None,
            )
        )

        # Emit step artifact — pass dicts to avoid cross-class issues
        steps_out.append(
            CamJclStep(
                job_name=job_name,
                step_name=step_name,
                seq=seq,
                program=program,
                dds=[dd.model_dump() for dd in (dd_list or [])] or None,
            )
        )

    # Emit job artifact
    jobs_out.append(CamJclJob(job_name=job_name, source=src, steps=steps_cam or None))

    return {
        "jobs": [j.model_dump() for j in jobs_out],
        "steps": [s.model_dump() for s in steps_out],
    }