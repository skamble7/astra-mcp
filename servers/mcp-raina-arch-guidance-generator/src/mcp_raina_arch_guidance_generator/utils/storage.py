# utils/storage.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from ..settings import Settings

log = logging.getLogger("mcp.raina.arch.guidance.storage")


def _build_client(settings: Settings, *, endpoint_override: str | None = None):
    """
    Create a boto3 S3 client.

    - For AWS S3: leave S3_ENDPOINT_URL unset; boto3 routes to the real AWS endpoint
      using virtual-hosted-style addressing (the AWS default).
    - For Garage / MinIO / other S3-compatible stores: set S3_ENDPOINT_URL to the
      store's address; path-style addressing is used (required by most self-hosted stores).

    If endpoint_override is provided, it is used as the endpoint_url (e.g., when
    generating presigned URLs that must be signed against the public-facing endpoint).
    """
    endpoint = endpoint_override or settings.s3_endpoint_url
    # Use path-style only for custom (non-AWS) endpoints; AWS prefers virtual-hosted.
    addressing_style = "path" if endpoint else "auto"
    cfg = Config(
        region_name=settings.s3_region or "us-east-1",
        s3={"addressing_style": addressing_style},
        retries={"max_attempts": 3, "mode": "standard"},
        signature_version="s3v4",
    )
    session = boto3.session.Session(
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region or "us-east-1",
    )
    return session.client("s3", endpoint_url=endpoint, config=cfg)


def upload_file_to_s3(
    settings: Settings,
    local_path: Path,
    bucket: str,
    key: str,
    content_type: str,
) -> bool:
    try:
        client = _build_client(settings)
        extra: dict = {"ContentType": content_type}
        if settings.s3_public_read:
            extra["ACL"] = "public-read"
        size = local_path.stat().st_size
        log.info(
            "s3.upload.begin",
            extra={"endpoint": settings.s3_endpoint_url, "bucket": bucket, "key": key, "bytes": size},
        )
        client.upload_file(str(local_path), bucket, key, ExtraArgs=extra)
        log.info("s3.upload.ok")
        return True
    except (BotoCoreError, ClientError) as e:
        log.warning("s3.upload.failed", extra={"bucket": bucket, "key": key, "error": str(e)})
        return False
    except Exception:
        log.exception("s3.upload.crash", extra={"bucket": bucket, "key": key})
        return False


def generate_presigned_get_url(
    settings: Settings,
    bucket: str,
    key: str,
    expires_seconds: int,
) -> Optional[str]:
    """
    Generate a SigV4 pre-signed GET URL.

    IMPORTANT: We sign using an endpoint whose host matches the URL the
    user will actually hit. If S3_PRESIGN_BASE_URL is set (e.g., http://localhost:3900),
    we build a client against that endpoint for signing.
    """
    try:
        presign_endpoint = settings.s3_presign_base_url or settings.s3_endpoint_url
        client = _build_client(settings, endpoint_override=presign_endpoint)
        url = client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )
        log.info(
            "s3.presign.ok",
            extra={
                "bucket": bucket,
                "key": key,
                "expires_sec": expires_seconds,
                "endpoint_used": presign_endpoint,
            },
        )
        return url
    except (BotoCoreError, ClientError) as e:
        log.warning("s3.presign.failed", extra={"bucket": bucket, "key": key, "error": str(e)})
        return None
    except Exception:
        log.exception("s3.presign.crash", extra={"bucket": bucket, "key": key})
        return None


def build_public_download_url(
    settings: Settings,
    bucket: str,
    key: str,
) -> Optional[str]:
    """Compose a stable download URL for the uploaded object."""
    base = (settings.s3_public_base_url or "").strip()
    if not base:
        ep = (settings.s3_endpoint_url or "").rstrip("/")
        return f"{ep}/{bucket}/{key}" if ep else None

    if "{bucket}" in base:
        return base.replace("{bucket}", bucket).rstrip("/") + "/" + key

    base = base.rstrip("/")
    if base.endswith("/" + bucket) or base.endswith("/" + bucket.rstrip("/")):
        return base + "/" + key

    return f"{base}/{bucket}/{key}"
