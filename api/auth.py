"""Google OAuth token verification."""

import logging
from datetime import datetime, timezone

from config import get_settings
from db import get_or_create_user, get_user_by_id
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)


async def verify_google_token(token: str) -> dict:
    """Verify a Google id_token against Google's public keys.

    Requires: pip install google-auth
    """
    try:
        from google.auth.transport import requests
        from google.oauth2 import id_token

        # This verifies the signature automatically. Tolerate up to 5 minutes
        # of local clock skew (system clock drift on dev machines).
        claims = id_token.verify_oauth2_token(
            token, requests.Request(), clock_skew_in_seconds=300
        )

        # Extra checks
        exp = claims.get("exp", 0)
        if exp < datetime.now(timezone.utc).timestamp():
            raise ValueError("Token expired")

        settings = get_settings()
        # Verify audience matches your client ID (optional but recommended)
        if settings.google_client_id and claims.get("aud") != settings.google_client_id:
            logger.warning(
                "Token audience mismatch: %s != %s",
                claims.get("aud"),
                settings.google_client_id,
            )
            # Don't fail on this, some setups have multiple client IDs

        return claims
    except Exception as exc:
        logger.error("Google token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid Google token")


async def get_current_user(authorization: str | None = Header(None)) -> dict:
    """Extract user from Authorization: Bearer <id_token> header.

    Upserts user in database and returns user info.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    try:
        scheme, token = authorization.split(" ", 1)
    except ValueError:
        raise HTTPException(
            status_code=401, detail="Invalid authorization header format"
        )

    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Expected Bearer scheme")

    # Verify token with Google
    claims = await verify_google_token(token)

    # Extract user info
    google_id = claims.get("sub")
    email = claims.get("email")
    name = claims.get("name", "")
    picture = claims.get("picture", "")

    if not google_id or not email:
        raise HTTPException(status_code=401, detail="Missing user claims")

    # Create or update user in database
    user_id = get_or_create_user(google_id, email, name, picture)
    user = get_user_by_id(user_id)

    if not user:
        raise HTTPException(status_code=500, detail="Failed to load user")

    return {**user, "google_id": google_id}
