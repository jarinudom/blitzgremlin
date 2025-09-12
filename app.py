import os, json, time
from flask import Flask, redirect, request, session, url_for, jsonify
from requests_oauthlib import OAuth2Session
import xmltodict

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
TEAMS_CACHE_FILE = "teams.json"

def save_token(token):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f)

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return None

def save_teams(data):
    with open(TEAMS_CACHE_FILE, "w") as f:
        json.dump(data, f)

def load_teams():
    if os.path.exists(TEAMS_CACHE_FILE):
        with open(TEAMS_CACHE_FILE) as f:
            return json.load(f)
    return None

@app.route("/")
def index():
    return "<h1>BlitzGremlin Yahoo Connector</h1><a href='/login'>Login with Yahoo</a>"

@app.route("/login")
def login():
    yahoo = OAuth2Session(
        CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        scope="fspt-r"
    )
    auth_url, state = yahoo.authorization_url(AUTH_BASE_URL)
    session["oauth_state"] = state
    return redirect(auth_url)

@app.route("/callback")
def callback():
    yahoo = OAuth2Session(CLIENT_ID, state=session.get("oauth_state"), redirect_uri=REDIRECT_URI)
    token = yahoo.fetch_token(
        TOKEN_URL,
        client_secret=CLIENT_SECRET,
        authorization_response=request.url
    )
    save_token(token)
    return "✅ Tokens saved. Endpoints: /profile, /my-leagues, /my-team, /league/{league_id}, /teams/{league_id}, /all-rosters/{league_id}, /roster/{team_key}, /matchups/{league_id}/{week}, /standings/{league_id}, /transactions/{league_id}"

def get_yahoo_session():
    token = load_token()
    if not token:
        return None

    if token.get("expires_at") and token["expires_at"] - time.time() < 300:
        extra = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
        yahoo = OAuth2Session(CLIENT_ID, token=token)
        new_token = yahoo.refresh_token(TOKEN_URL, **extra)
        save_token(new_token)
        token = new_token

    yahoo = OAuth2Session(
        CLIENT_ID,
        token=token,
        auto_refresh_url=TOKEN_URL,
        auto_refresh_kwargs={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        token_updater=save_token
    )
    return yahoo

@app.route("/profile")
def profile():
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    r = yahoo.get("https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1")
    return jsonify(xmltodict.parse(r.content))

@app.route("/my-leagues")
def my_leagues():
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games/leagues"
    r = yahoo.get(url)
    return jsonify(xmltodict.parse(r.content))

@app.route("/my-team")
def my_team():
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games/leagues/teams"
    r = yahoo.get(url)
    data = xmltodict.parse(r.content)

    teams = []
    games = data["fantasy_content"]["users"]["user"]["games"]["game"]
    if isinstance(games, dict):
        games = [games]
    for game in games:
        if "leagues" in game:
            leagues = game["leagues"]["league"]
            if isinstance(leagues, dict):
                leagues = [leagues]
            for league in leagues:
                if "teams" in league:
                    teams_list = league["teams"]["team"]
                    if isinstance(teams_list, dict):
                        teams_list = [teams_list]
                    for team in teams_list:
                        if team.get("is_owned_by_current_login") == "1":
                            teams.append(team)

    return jsonify({"my_teams": teams})

@app.route("/league/<league_id>")
def league(league_id):
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}"
    r = yahoo.get(url)
    return jsonify(xmltodict.parse(r.content))

@app.route("/teams/<league_id>")
def teams(league_id):
    cached = load_teams()
    if cached and cached.get("league_id") == league_id:
        return jsonify(cached)

    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/teams"
    r = yahoo.get(url)
    data = xmltodict.parse(r.content)
    save_teams({"league_id": league_id, "teams": data})
    return jsonify(data)

@app.route("/all-rosters/<league_id>")
def all_rosters(league_id):
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))

    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/teams/roster"
    r = yahoo.get(url)
    data = xmltodict.parse(r.content)
    return jsonify(data)

@app.route("/roster/<team_key>")
def roster(team_key):
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/team/{team_key}/roster"
    r = yahoo.get(url)
    return jsonify(xmltodict.parse(r.content))

@app.route("/matchups/<league_id>/<week>")
def matchups(league_id, week):
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/scoreboard;week={week}"
    r = yahoo.get(url)
    return jsonify(xmltodict.parse(r.content))

@app.route("/standings/<league_id>")
def standings(league_id):
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/standings"
    r = yahoo.get(url)
    return jsonify(xmltodict.parse(r.content))

@app.route("/transactions/<league_id>")
def transactions(league_id):
    yahoo = get_yahoo_session()
    if not yahoo:
        return redirect(url_for("login"))
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/transactions"
    r = yahoo.get(url)
    return jsonify(xmltodict.parse(r.content))

# Render/Production: app is served by gunicorn, so no app.run() here.
