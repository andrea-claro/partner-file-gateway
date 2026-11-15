"""Move an object inside the transfer bucket (copy, then delete the source)."""

from __future__ import annotations

from typing import Any

# S3 user metadata must be ASCII and is limited to 2 KB per object.
_MAX_METADATA_VALUE = 512


def ascii_metadata(value: str) -> str:
    cleaned = value.encode("ascii", "replace").decode("ascii")
    cleaned = "".join(ch if ch.isprintable() else " " for ch in cleaned)
    return cleaned[:_MAX_METADATA_VALUE]


def move_object(
    s3: Any,
    *,
    bucket: str,
    source_key: str,
    source_version_id: str,
    destination_key: str,
    metadata: dict[str, str],
) -> str:
    """Copy one exact source version to ``destination_key`` and delete the source.

    Copying by version id keeps the move correct even if the partner uploads a
    newer file under the same name meanwhile. Deleting by key adds a delete
    marker (the bucket is versioned), so the original stays recoverable until
    the noncurrent-version lifecycle rule expires it.

    Returns the version id of the new object ("" if the bucket is unversioned).
    """
    copy_source: dict[str, str] = {"Bucket": bucket, "Key": source_key}
    head_args: dict[str, str] = {"Bucket": bucket, "Key": source_key}
    if source_version_id:
        copy_source["VersionId"] = source_version_id
        head_args["VersionId"] = source_version_id

    content_type = s3.head_object(**head_args).get("ContentType", "application/octet-stream")
    response = s3.copy_object(
        Bucket=bucket,
        Key=destination_key,
        CopySource=copy_source,
        MetadataDirective="REPLACE",
        Metadata={name: ascii_metadata(value) for name, value in metadata.items()},
        ContentType=content_type,
        TaggingDirective="REPLACE",
    )
    s3.delete_object(Bucket=bucket, Key=source_key)
    return response.get("VersionId") or ""
