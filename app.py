import os, json
from flask import Flask, redirect, request, session, url_for
from requests_oauthlib import OAuth2Session

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Load secrets from environment
CLIENT_ID = os.getenv("YAHOO_CLIENT_ID")
CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET")
REDIRECT_URI = os.getenv("YAHOO_REDIRECT_URI", "http://localhost:5000/callback")

AUTH_BASE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

# Token storage file
TOKEN_FILE = "token.json"

def save_token(token):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f)

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return None

@app.route("/")
def index():
    return "<h1>BlitzGremlin Yahoo Connector</h1><a href='/login'>Login with Yahoo</a>"

@app.route("/login")
def login():
    yahoo = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI, scope=["fspt-r fspt-w"])
    auth_url, state = yahoo.authorization_url(AUTH_BASE_URL)
    session["oauth_state"] = state
    return redirect(auth_url)

@app.route("/callback")
def callback():
    yahoo = OAuth2Session(CLIENT_ID, state=session["oauth_state"], redirect_uri=REDIRECT_URI)
    token = yahoo.fetch_token(TOKEN_URL,
                              client_secret=CLIENT_SECRET,
                              authorization_response=request.url)
    save_token(token)
    return "✅ Tokens saved. Try /profile, /league/{league_id}, or /roster/{team_key}"

def get_yahoo_session():
    token = load_token()
    if not token:
        return None

    yahoo = OAuth2Session(CLIENT_ID, token=token, auto_refresh_url=TOKEN_URL,
                          auto_refresh_kwargs={
                              'client_id': CLIENT_ID,
                              'client_secret': CLIENT_SECRET,
                          },
                          token_updater=save_token)
    return yahoo

@app.route("/profile")
def profile():
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    r = yahoo.get("https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1")
    return r.content

@app.route("/league/<league_id>")
def league(league_id):
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}"
    r = yahoo.get(url)
    return r.content

@app.route("/roster/<team_key>")
def roster(team_key):
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/team/{team_key}/roster"
    r = yahoo.get(url)
    return r.content

# Render/Production: app is served by gunicorn, so no app.run() here.

