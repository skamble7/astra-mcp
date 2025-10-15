#servers/workspace-doc-generator/src/mcp_workspace_doc_generator/models/file_detail.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class Checksum(BaseModel):
    md5: Optional[str] = None
    sha1: Optional[str] = None
    sha256: Optional[str] = None

class RelatedAsset(BaseModel):
    id: Optional[str] = None
    relation: Optional[str] = None

class Preview(BaseModel):
    thumbnail_url: Optional[str] = None
    text_excerpt: Optional[str] = None
    page_count: Optional[int | str] = None

class FileDetail(BaseModel):
    # Only the most relevant properties for our generator; schema allows others.
    name: Optional[str] = None
    description: Optional[str] = None
    filename: Optional[str] = None
    path: Optional[str] = None
    storage_uri: Optional[str] = None
    download_url: Optional[str] = None
    download_expires_at: Optional[str] = None
    size_bytes: Optional[int | str] = None
    mime_type: Optional[str] = None
    encoding: Optional[str] = None
    checksum: Optional[Checksum] = None
    revision: Optional[str] = None
    source_system: Optional[str] = None
    owner: Optional[str] = None
    tags: Optional[List[str]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    access_policy: Optional[str | Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    preview: Optional[Preview] = None
    related_assets: Optional[List[RelatedAsset]] = None

    def as_cam(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)