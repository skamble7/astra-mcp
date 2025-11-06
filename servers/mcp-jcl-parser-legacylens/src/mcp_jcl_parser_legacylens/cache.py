#servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/cache.py
from __future__ import annotations
import os, json, pathlib, typing as t
from .settings import Settings

def run_dir(cfg: Settings, run_id: str) -> str:
    d = os.path.join(cfg.CACHE_DIR, "runs", run_id)
    pathlib.Path(d).mkdir(parents=True, exist_ok=True)
    return d

def artifacts_dir(cfg: Settings, run_id: str) -> str:
    d = os.path.join(run_dir(cfg, run_id), "artifacts")
    pathlib.Path(d).mkdir(parents=True, exist_ok=True)
    return d

def maps_dir(cfg: Settings, run_id: str) -> str:
    d = os.path.join(run_dir(cfg, run_id), "maps")
    pathlib.Path(d).mkdir(parents=True, exist_ok=True)
    return d

def source_index_path(cfg: Settings, run_id: str) -> str:
    return os.path.join(run_dir(cfg, run_id), "source-index.json")

def manifest_path(cfg: Settings, run_id: str) -> str:
    return os.path.join(run_dir(cfg, run_id), "manifest.json")

def artifact_path(cfg: Settings, run_id: str, sha256: str, kind: str, key_suffix: str | None = None) -> str:
    """
    For JCL, a single file can emit multiple jobs and many steps.
    We include a sanitized suffix (e.g., job or job_step) in the filename to keep artifacts distinct.
    """
    base = f"{sha256}.{kind}.json" if not key_suffix else f"{sha256}.{kind}.{key_suffix}.json"
    return os.path.join(artifacts_dir(cfg, run_id), base)

def write_json(path: str, obj: t.Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def read_json(path: str) -> t.Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def exists(path: str) -> bool:
    return os.path.exists(path)