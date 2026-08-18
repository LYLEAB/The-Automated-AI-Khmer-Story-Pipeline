"""
storage.py — Cloudflare R2 & Supabase Storage integration.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import config
from utils import setup_logger

logger = setup_logger("storage")


class StorageClient:
    def __init__(self) -> None:
        self.r2_client = None
        if config.R2_ACCOUNT_ID and config.R2_ACCESS_KEY_ID and config.R2_SECRET_ACCESS_KEY:
            try:
                import boto3
                self.r2_client = boto3.client(
                    "s3",
                    endpoint_url=f"https://{config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
                    aws_access_key_id=config.R2_ACCESS_KEY_ID,
                    aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
                    region_name="auto",
                )
                logger.info("[INFO] Cloudflare R2 client initialized.")
            except Exception as exc:
                logger.warning(f"[WARN] Failed to initialize Cloudflare R2: {exc}")

    def upload_file(self, local_path: Path, object_key: str, content_type: str = "video/mp4") -> Optional[str]:
        if not local_path.exists():
            logger.error(f"[ERROR] File not found: {local_path}")
            return None

        if self.r2_client:
            try:
                self.r2_client.upload_file(
                    str(local_path),
                    config.R2_BUCKET_NAME,
                    object_key,
                    ExtraArgs={"ContentType": content_type},
                )
                public_url = f"{config.R2_PUBLIC_URL.rstrip('/')}/{object_key}" if config.R2_PUBLIC_URL else object_key
                logger.info(f"[SUCCESS] Uploaded to Cloudflare R2: {public_url}")
                return public_url
            except Exception as exc:
                logger.error(f"[ERROR] Cloudflare R2 upload error: {exc}")

        return None
