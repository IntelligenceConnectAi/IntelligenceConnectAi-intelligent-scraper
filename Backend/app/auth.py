"""
Supabase JWT verification.
Supports both HS256 (legacy) and ES256/RS256 (modern) automatically.
"""

import jwt
from fastapi import HTTPException, status
from jwt import PyJWKClient
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.config import settings

_JWKS_URL = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
_jwks_client = PyJWKClient(_JWKS_URL, cache_keys=True, lifespan=300)


def verify_jwt(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
        alg = (header.get("alg") or "").upper()

        if alg == "HS256":
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )

        if alg in ("ES256", "RS256"):
            signing_key = _jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=[alg],
                audience="authenticated",
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unsupported JWT algorithm: {alg}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )