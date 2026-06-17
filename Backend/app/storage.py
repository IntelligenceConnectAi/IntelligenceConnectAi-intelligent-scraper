import httpx
from app.config import settings

_STORAGE_BASE = f"{settings.supabase_url.rstrip('/')}/storage/v1"
_BUCKET = "job-outputs"
_HEADERS = {"Authorization": f"Bearer {settings.supabase_service_role_key}"}


async def upload_csv(storage_path: str, content: bytes) -> str:
    url = f"{_STORAGE_BASE}/object/{_BUCKET}/{storage_path}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.put(
            url, content=content,
            headers={**_HEADERS, "Content-Type": "text/csv", "x-upsert": "true"},
        )
        resp.raise_for_status()
    return storage_path


async def get_signed_url(storage_path: str, expires_in: int = 3600) -> str:
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
    return signed
    #storage file 