"""OAuth2 authentication and token management for Yahoo Fantasy API."""
import os
import json
import time
import logging
from requests_oauthlib import OAuth2Session

from config import (
    CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, TOKEN_URL, TOKEN_FILE,
    TOKEN_REFRESH_THRESHOLD
)

logger = logging.getLogger(__name__)


def save_token(token: dict) -> None:
    """Save OAuth token to file."""
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f)


def load_token() -> dict | None:
    """Load OAuth token from file."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return None


def yahoo_session() -> OAuth2Session | None:
    """Create and return an authenticated Yahoo OAuth2 session.
    
    Proactively refreshes the token if it's expiring soon.
    """
    token = load_token()
    if not token:
        return None

    # Proactive refresh if expiring within threshold
    if token.get("expires_at") and token["expires_at"] - time.time() < TOKEN_REFRESH_THRESHOLD:
        logger.info("Refreshing Yahoo OAuth token (expiring soon)")
        extra = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
        yahoo = OAuth2Session(CLIENT_ID, token=token)
        try:
            new_token = yahoo.refresh_token(TOKEN_URL, **extra)
            save_token(new_token)
            token = new_token
            logger.info("Yahoo OAuth token refreshed successfully")
        except Exception as e:
            logger.error(f"Yahoo OAuth token refresh failed: {e}")

    yahoo = OAuth2Session(
        CLIENT_ID,
        token=token,
        redirect_uri=REDIRECT_URI,
        auto_refresh_url=TOKEN_URL,
        auto_refresh_kwargs={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        token_updater=save_token
    )
    return yahoo

