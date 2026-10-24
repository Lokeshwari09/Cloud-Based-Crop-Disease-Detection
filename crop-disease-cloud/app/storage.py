"""
Object storage abstraction.

Default: a local folder that behaves like an S3 bucket (data/uploads/).
Set USE_S3=true (+ S3_BUCKET, AWS_REGION and AWS credentials / IAM role) to
store uploads in a real Amazon S3 bucket instead. Needs: pip install boto3
"""
from __future__ import annotations

import os
from pathlib import Path


class LocalStorage:
    kind = "local"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        (self.root / key).write_bytes(data)
        return f"/uploads/{key}"

    def read(self, key: str) -> bytes | None:
        p = self.root / key
        return p.read_bytes() if p.exists() else None


class S3Storage:
    kind = "s3"

    def __init__(self, bucket: str, region: str):
        import boto3  # imported lazily so the project runs without it

        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=region)

    def save(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        self.s3.put_object(Bucket=self.bucket, Key=f"uploads/{key}", Body=data, ContentType=content_type)
        return f"/uploads/{key}"  # served back through the app (bucket stays private)

    def read(self, key: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=f"uploads/{key}")["Body"].read()
        except Exception:
            return None


def get_storage(data_dir: Path):
    if os.getenv("USE_S3", "false").lower() == "true":
        return S3Storage(os.environ["S3_BUCKET"], os.getenv("AWS_REGION", "ap-south-1"))
    return LocalStorage(Path(data_dir) / "uploads")
