"""
Supabase Storage helper — CSV upload + signed download URLs.
Uses the Storage REST API directly via httpx (no supabase-py needed).
"""

import httpx

from app.config import settings

_STORAGE_BASE = f"{settings.supabase_url.rstrip('/')}/storage/v1"
_BUCKET = "job-outputs"
_HEADERS = {
    "Authorization": f"Bearer {settings.supabase_service_role_key}",
}


async def upload_csv(storage_path: str, content: bytes) -> str:
    """
    Upload CSV bytes to Supabase Storage.
    storage_path: e.g. "user_id/job_id/with_website.csv"
    Returns the storage path on success.
    """
    url = f"{_STORAGE_BASE}/object/{_BUCKET}/{storage_path}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.put(
            url,
            content=content,
            headers={
                **_HEADERS,
                "Content-Type": "text/csv",
                "x-upsert": "true",   # overwrite if exists
            },
        )
        resp.raise_for_status()
    return storage_path


async def get_signed_url(storage_path: str, expires_in: int = 3600) -> str:
    """
    Get a temporary signed download URL (default: 1 hour).
    storage_path: e.g. "user_id/job_id/with_website.csv"
    Returns the full signed URL.
    """
    url = f"{_STORAGE_BASE}/object/sign/{_BUCKET}/{storage_path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            json={"expiresIn": expires_in},
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

    signed = data.get("signedURL") or data.get("signedUrl") or ""
    if signed.startswith("/"):
        signed = f"{settings.supabase_url.rstrip('/')}{signed}"
    return signed