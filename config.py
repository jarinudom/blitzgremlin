"""Configuration and constants for BlitzGremlin."""
import os

# Flask configuration
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "supersecret")
PORT = int(os.environ.get("PORT", 5000))

# Yahoo API credentials
CLIENT_ID = os.environ.get("YAHOO_CLIENT_ID")
CLIENT_SECRET = os.environ.get("YAHOO_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://blitzgremlin.onrender.com/callback")

# Yahoo API URLs
AUTH_BASE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"

# Token storage
TOKEN_FILE = "token.json"

# Waivers/Free Agents constants
VALID_POSITIONS = {"QB", "RB", "WR", "TE", "DEF", "K"}
VALID_STATUSES = {"A", "FA", "W"}
DEFAULT_POSITION = "ALL"
DEFAULT_STATUS = "A"

# Cache configuration
CACHE_TTL = 3600  # 1 hour in seconds
TOKEN_REFRESH_THRESHOLD = 300  # Refresh token if expiring within 5 minutes

