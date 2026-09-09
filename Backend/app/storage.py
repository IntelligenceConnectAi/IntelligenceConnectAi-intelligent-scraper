from urllib.parse import quote

import httpx
from app.config import settings

_STORAGE_BASE = f"{settings.supabase_url.rstrip('/')}/storage/v1"
_BUCKET = "job-outputs"
_HEADERS = {"Authorization": f"Bearer {settings.supabase_service_role_key}"}


async def upload_csv(storage_path: str, content: bytes, content_type: str = "text/csv") -> str:
    url = f"{_STORAGE_BASE}/object/{_BUCKET}/{storage_path}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.put(
            url, content=content,
            headers={**_HEADERS, "Content-Type": content_type, "x-upsert": "true"},
        )
        resp.raise_for_status()
    return storage_path


async def try_download_object(storage_path: str) -> bytes | None:
    """Returns the object's raw bytes, or None if it doesn't exist (404). Used for
    resumable-job checkpoints — worker/runner.py checks for one of these before
    deciding whether to run a phase from scratch or skip straight past it."""
    url = f"{_STORAGE_BASE}/object/{_BUCKET}/{storage_path}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url, headers=_HEADERS)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content


async def delete_object(storage_path: str) -> None:
    """Best-effort delete — 404 (already gone / never existed) is not an error."""
    url = f"{_STORAGE_BASE}/object/{_BUCKET}/{storage_path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(url, headers=_HEADERS)
    if resp.status_code not in (200, 404):
        resp.raise_for_status()


async def get_signed_url(storage_path: str, expires_in: int = 3600, download_filename: str | None = None) -> str:
    url = f"{_STORAGE_BASE}/object/sign/{_BUCKET}/{storage_path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url, json={"expiresIn": expires_in}, headers=_HEADERS
        )
        resp.raise_for_status()
        data = resp.json()
    signed = data.get("signedURL") or data.get("signedUrl") or ""
    # Supabase returns a path RELATIVE to /storage/v1 (e.g. "/object/sign/bucket/path?token=...")
    # so we must prepend _STORAGE_BASE, NOT the bare supabase_url.
    if signed.startswith("/"):
        signed = f"{_STORAGE_BASE}{signed}"
    if download_filename:
        # Supabase Storage's object-serving endpoint honors a `download` query param
        # to control the Content-Disposition filename, independent of the actual
        # storage object name — this is how a browser saves the file locally as
        # something human-readable ("Plumbers_FL_with_website.csv") without us having
        # to rename/move the underlying stored object. The signed URL already carries
        # its own `?token=...`, so append with `&`, never a second `?`.
        sep = "&" if "?" in signed else "?"
        signed = f"{signed}{sep}download={quote(download_filename)}"
    return signed 