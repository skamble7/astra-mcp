# models/arch_guidance.py
#
# Pydantic model for the cam.governance.microservices_arch_guidance artifact kind.
# Matches the JSON schema defined in schema_versions[0].json_schema.
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class Checksum(BaseModel):
    model_config = ConfigDict(extra="allow")

    md5: Optional[str] = None
    sha1: Optional[str] = None
    sha256: Optional[str] = None


class PreviewInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    thumbnail_url: Optional[str] = None
    text_excerpt: Optional[str] = None
    page_count: Optional[Union[int, str]] = None


class RelatedAsset(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    relation: Optional[str] = None


class ArchGuidanceData(BaseModel):
    """
    Data payload for a cam.governance.microservices_arch_guidance artifact.
    The `content` field holds the full Markdown guidance document.
    """

    model_config = ConfigDict(extra="allow")

    # Required by schema
    name: Optional[str] = Field(None, description="Human-friendly file name.")

    # Core file metadata
    description: Optional[str] = Field(None, description="Optional description of the file contents.")
    filename: Optional[str] = Field(None, description="Actual filename including extension.")
    path: Optional[str] = Field(None, description="Logical or repository path.")
    storage_uri: Optional[str] = Field(None, description="Canonical storage URI.")
    download_url: Optional[str] = Field(None, description="Direct link to download the file.")
    download_expires_at: Optional[str] = Field(None, description="Expiry of the download link.")
    size_bytes: Optional[Union[int, str]] = Field(None, description="Size of the file in bytes.")
    mime_type: Optional[str] = Field(None, description="IANA media type.")
    encoding: Optional[str] = Field(None, description="Text/binary encoding if relevant.")
    checksum: Optional[Checksum] = None
    revision: Optional[str] = Field(None, description="File revision/version identifier.")
    source_system: Optional[str] = Field(None, description="Originating system.")
    owner: Optional[str] = None
    tags: Optional[List[str]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    access_policy: Optional[Any] = None
    metadata: Optional[Dict[str, Any]] = None
    preview: Optional[PreviewInfo] = None
    related_assets: Optional[List[RelatedAsset]] = None

    # The actual guidance document content (Markdown)
    content: Optional[str] = Field(None, description="Full Markdown guidance document content.")


class ArchGuidanceArtifact(BaseModel):
    """Wrapper artifact as returned to the Astra runtime."""

    model_config = ConfigDict(extra="allow")

    kind_id: str = "cam.governance.microservices_arch_guidance"
    name: Optional[str] = None
    data: ArchGuidanceData
    preview: Optional[Dict[str, Any]] = None
    mime_type: Optional[str] = None
    encoding: Optional[str] = None
    filename: Optional[str] = None
    path: Optional[str] = None
    storage_uri: Optional[str] = None
    download_url: Optional[str] = None
    checksum: Optional[Checksum] = None
    tags: Optional[List[str]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class GenerateGuidanceResult(BaseModel):
    """Top-level MCP tool response wrapping one or more artifacts."""

    artifacts: List[ArchGuidanceArtifact]
