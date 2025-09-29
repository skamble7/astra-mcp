# File: servers/mcp-cobol-parser/mcp_cobol_parser/cache.py
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

def artifact_path(cfg: Settings, run_id: str, sha256: str, kind: str) -> str:
    return os.path.join(artifacts_dir(cfg, run_id), f"{sha256}.{kind}.json")

def write_json(path: str, obj: t.Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def read_json(path: str) -> t.Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def exists(path: str) -> bool:
    return os.path.exists(path)
