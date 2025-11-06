# File: servers/mcp-cobol-parser/mcp_cobol_parser/resources/artifact_preview.py
from __future__ import annotations
import os, json, logging
from typing import Any, Dict
from ..settings import Settings
from ..cache import manifest_path, exists, artifact_path
from ..hashing import sha256_file

log = logging.getLogger("mcp.cobol.artifact_preview")

# short -> full kind_id mapping
_VALID_KINDS = {
    "copybook": "cam.cobol.copybook",
    "program": "cam.cobol.program",
    "error":   "cam.error",
}

_DEFAULT_SCHEMA = {
    "cam.cobol.copybook": "1.0.0",
    "cam.cobol.program": "1.0.0",
    "cam.error": "1.0.0",
}

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

def _ensure_envelope(obj: Dict[str, Any], *, kind_id: str, relpath: str, sha: str) -> Dict[str, Any]:
    # If the cached object already looks enveloped, return as-is
    if isinstance(obj, dict) and "kind_id" in obj and "data" in obj:
        return obj
    # Otherwise wrap legacy raw payloads to keep resources stable
    return {
        "kind_id": kind_id,
        "schema_version": _DEFAULT_SCHEMA.get(kind_id, "1.0.0"),
        "key": relpath,
        "provenance": {
            "producer": "mcp.cobol.parse_repo",
            "parsers": {},
            "source": {"relpath": relpath, "sha256": sha},
        },
        "data": obj,
    }

def _maybe_log_full(prefix: str, payload_obj: Dict[str, Any]) -> None:
    if os.getenv("ARTIFACT_LOG_FULL", "").lower() in {"1", "true", "yes"}:
        limit = int(os.getenv("ARTIFACT_LOG_FULL_LIMIT", "0"))
        try:
            s = json.dumps(payload_obj, ensure_ascii=False)
            if limit and len(s) > limit:
                log.info("%s (truncated to %d chars): %s", prefix, limit, s[:limit])
            else:
                log.info("%s: %s", prefix, s)
        except Exception as e:
            log.warning("%s logging failed: %s", prefix, e)

def register_artifact_preview_resources(mcp: Any) -> None:
    @mcp.resource(
        uri="artifact://{run_id}/{kind}/{relpath}",
        name="Artifact (by relpath)",
        description="Returns the normalized artifact envelope for the requested file.",
        mime_type="application/json",
    )
    def read_artifact_by_relpath(run_id: str, kind: str, relpath: str) -> dict[str, Any]:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Unsupported kind: {kind}")
        kind_id = _VALID_KINDS[kind]
        cfg = Settings()
        root = _paths_root_from_manifest(cfg, run_id)
        sha = _sha_for_relpath(root, relpath)
        ap = artifact_path(cfg, run_id, sha, kind)
        if not exists(ap):
            ep = artifact_path(cfg, run_id, sha, "error")
            if exists(ep):
                with open(ep, "r", encoding="utf-8") as f:
                    err = json.load(f)
                # ensure error envelope
                if "kind_id" not in err:
                    err = _ensure_envelope(err, kind_id="cam.error", relpath=relpath, sha=sha)
                _maybe_log_full("artifact_preview relpath response", err)
                return err
            raise FileNotFoundError(f"No cached {kind} artifact for {relpath} (sha={sha[:8]}...)")
        with open(ap, "r", encoding="utf-8") as f:
            raw = json.load(f)
        env = _ensure_envelope(raw, kind_id=kind_id, relpath=relpath, sha=sha)
        _maybe_log_full("artifact_preview relpath response", env)
        return env

    @mcp.resource(
        uri="artifact://{run_id}/by-sha/{sha}.{kind}",
        name="Artifact (by sha)",
        description="Returns an artifact envelope by its sha256 and kind (copybook|program|error).",
        mime_type="application/json",
    )
    def read_artifact_by_sha(run_id: str, sha: str, kind: str) -> dict[str, Any]:
        if kind not in _VALID_KINDS:
            raise ValueError(f"Unsupported kind: {kind}")
        kind_id = _VALID_KINDS[kind]
        cfg = Settings()
        ap = artifact_path(cfg, run_id, sha, kind)
        if not exists(ap):
            raise FileNotFoundError(f"Artifact not found: {sha}.{kind}")
        with open(ap, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # We don't have relpath here; key stays as sha-kind hint when wrapping
        key = f"{sha}.{kind}"
        env = raw if ("kind_id" in raw and "data" in raw) else {
            "kind_id": kind_id,
            "schema_version": _DEFAULT_SCHEMA.get(kind_id, "1.0.0"),
            "key": key,
            "provenance": {"producer": "mcp.cobol.parse_repo", "parsers": {}, "source": {"relpath": None, "sha256": sha}},
            "data": raw,
        }
        _maybe_log_full("artifact_preview sha response", env)
        return env