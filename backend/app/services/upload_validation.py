from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile


ALLOWED_EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
ALLOWED_EXCEL_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/octet-stream",
}

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ALLOWED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/bmp",
    "application/octet-stream",
}


def read_validated_upload(
    file: UploadFile,
    *,
    max_bytes: int,
    allowed_extensions: set[str],
    allowed_mime_types: set[str],
    purpose: str,
) -> tuple[bytes, str]:
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()
    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {purpose} extension. Allowed: {', '.join(sorted(allowed_extensions))}.",
        )

    mime = (file.content_type or "").lower().strip()
    if mime and mime not in allowed_mime_types:
        raise HTTPException(status_code=400, detail=f"Unsupported {purpose} MIME type: {mime}.")

    content = file.file.read(max_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail=f"Empty {purpose} file.")
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"{purpose.capitalize()} file exceeds size limit.")
    return content, extension
