# File: servers/mcp-cobol-parser/mcp_cobol_parser/resources/artifact_preview.py
from __future__ import annotations
import os, json
from typing import Any
from ..settings import Settings
from ..cache import manifest_path, exists, artifact_path
from ..hashing import sha256_file

_VALID_KINDS = {"copybook": "cam.cobol.copybook", "program": "cam.cobol.program", "error": "error"}

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

def _sha_for_relpath(root: str, relpath: str) -> str:
    relpath = relpath.replace("\\", "/").lstrip("/")
    abs_path = os.path.abspath(os.path.join(root, relpath))
    root_abs = os.path.abspath(root)
    if not (abs_path == root_abs or abs_path.startswith(root_abs + os.sep)):
        raise PermissionError("Path traversal detected.")
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"File not found: {relpath}")
    return sha256_file(abs_path)

def register_artifact_preview_resources(mcp: Any) -> None:
    @mcp.resource(
        uri="artifact://{run_id}/{kind}/{relpath}",  # ← no wildcard star
        name="Artifact (by relpath)",
        description="Returns the normalized artifact (copybook/program) for the requested file.",
        mime_type="application/json",
    )
    def read_artifact_by_relpath(run_id: str, kind: str, relpath: str) -> dict[str, Any]:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Unsupported kind: {kind}")
        cfg = Settings()
        root = _paths_root_from_manifest(cfg, run_id)
        sha = _sha_for_relpath(root, relpath)
        ap = artifact_path(cfg, run_id, sha, kind)
        if not exists(ap):
            ep = artifact_path(cfg, run_id, sha, "error")
            if exists(ep):
                with open(ep, "r", encoding="utf-8") as f:
                    return json.load(f)
            raise FileNotFoundError(f"No cached {kind} artifact for {relpath} (sha={sha[:8]}...)")
        with open(ap, "r", encoding="utf-8") as f:
            return json.load(f)

    @mcp.resource(
        uri="artifact://{run_id}/by-sha/{sha}.{kind}",
        name="Artifact (by sha)",
        description="Returns an artifact by its sha256 and kind (copybook|program|error).",
        mime_type="application/json",
    )
    def read_artifact_by_sha(run_id: str, sha: str, kind: str) -> dict[str, Any]:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Unsupported kind: {kind}")
        cfg = Settings()
        ap = artifact_path(cfg, run_id, sha, kind)
        if not exists(ap):
            raise FileNotFoundError(f"Artifact not found: {sha}.{kind}")
        with open(ap, "r", encoding="utf-8") as f:
            return json.load(f)
