# servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/resources/artifact_preview.py
from __future__ import annotations
import os, json
from typing import Any, List, Dict
from ..settings import Settings
from ..cache import manifest_path, exists, artifact_path, read_json
from ..utils.fs import safe_join
from ..hashing import sha256_file

_VALID_KINDS = {"job": "cam.jcl.job", "step": "cam.jcl.step"}

def _paths_root_from_manifest(cfg: Settings, run_id: str) -> str:
    mp = manifest_path(cfg, run_id)
    if not exists(mp):
        raise FileNotFoundError(f"Run not found: {run_id}")
    with open(mp, "r", encoding="utf-8") as f:
        data = json.load(f)
    root = (data.get("run", {}) or {}).get("paths_root") or data.get("paths_root")
    if not root or not os.path.isdir(root):
        raise FileNotFoundError("paths_root missing or invalid in manifest.")
    return root

def register_artifact_preview_resources(mcp: Any) -> None:
    @mcp.resource(
        uri="artifact://{run_id}/{kind}/{relpath}",
        name="Artifact(s) by relpath",
        description="Returns all artifacts of a given kind (job|step) for a file.",
        mime_type="application/json",
    )
    def read_artifacts_by_relpath(run_id: str, kind: str, relpath: str) -> Dict[str, Any]:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Unsupported kind: {kind}")

        cfg = Settings()
        root = _paths_root_from_manifest(cfg, run_id)
        abs_path = safe_join(root, relpath)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"File not found: {relpath}")

        sha = sha256_file(abs_path)
        idx = artifact_path(cfg, run_id, sha, kind, "_index")
        if not exists(idx):
            return {"kind": _VALID_KINDS[kind], "artifacts": []}

        keys = (read_json(idx).get("keys") or [])
        artifacts: List[Dict[str, Any]] = []
        for key in keys:
            ap = artifact_path(cfg, run_id, sha, kind, key)
            if exists(ap):
                artifacts.append(read_json(ap))

        return {"kind": _VALID_KINDS[kind], "artifacts": artifacts}

    @mcp.resource(
        uri="artifact://{run_id}/{kind}/{sha}/{key}",
        name="Artifact by sha+key",
        description="Returns a single artifact by sha and key. For steps, key is 'job__step'.",
        mime_type="application/json",
    )
    def read_artifact_by_sha_key(run_id: str, kind: str, sha: str, key: str) -> Dict[str, Any]:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Unsupported kind: {kind}")
        cfg = Settings()
        ap = artifact_path(cfg, run_id, sha, kind, key)
        if not exists(ap):
            raise FileNotFoundError(f"Artifact not found: {sha}.{kind}.{key}")
        return read_json(ap)

    @mcp.resource(
        uri="artifact://{run_id}/{kind}/{sha}",
        name="Artifact index by sha",
        description="Returns the index keys available for this sha and kind.",
        mime_type="application/json",
    )
    def read_artifact_index(run_id: str, kind: str, sha: str) -> Dict[str, Any]:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Unsupported kind: {kind}")
        cfg = Settings()
        idx = artifact_path(cfg, run_id, sha, kind, "_index")
        if not exists(idx):
            return {"keys": []}
        return read_json(idx)