import os
import json
import requests
import xmltodict
from flask import Flask, redirect, request, session, jsonify
from requests_oauthlib import OAuth2Session

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecret")

# Yahoo API credentials
CLIENT_ID = os.environ.get("YAHOO_CLIENT_ID")
CLIENT_SECRET = os.environ.get("YAHOO_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://blitzgremlin.onrender.com/callback")

AUTH_BASE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"

# -------------------------------
# Helpers
# -------------------------------

def save_token(token):
    with open("token.json", "w") as f:
        json.dump(token, f)

def load_token():
    if os.path.exists("token.json"):
        with open("token.json", "r") as f:
            return json.load(f)
    return None

def normalize_league_id(league_id: str) -> str:
    """Ensure league_id is in full Yahoo key format: 461.l.{league_id}"""
    if league_id.isdigit():
        return f"461.l.{league_id}"
    return league_id

def yahoo_session():
    token = load_token()
    return OAuth2Session(CLIENT_ID, token=token, redirect_uri=REDIRECT_URI, auto_refresh_url=TOKEN_URL,
                         auto_refresh_kwargs={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
                         token_updater=save_token)

def fetch_yahoo(url):
    yahoo = yahoo_session()
    resp = yahoo.get(url, params={"format": "json"})
    resp.raise_for_status()
    return resp.json()

# -------------------------------
# Routes
# -------------------------------

@app.route("/")
def index():
    return "BlitzGremlin Yahoo Fantasy API is live 🎉"

@app.route("/login")
def login():
    yahoo = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI)
    authorization_url, state = yahoo.authorization_url(AUTH_BASE_URL)
    session["oauth_state"] = state
    return redirect(authorization_url)

@app.route("/callback")
def callback():
    yahoo = OAuth2Session(CLIENT_ID, state=session.get("oauth_state"), redirect_uri=REDIRECT_URI)
    token = yahoo.fetch_token(TOKEN_URL, client_secret=CLIENT_SECRET,
                              authorization_response=request.url)
    save_token(token)
    return "Authentication complete! You can now use the API."

@app.route("/profile")
def profile():
    url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1"
    return jsonify(fetch_yahoo(url))

@app.route("/my-leagues")
def my_leagues():
    url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games;game_keys=nfl/leagues"
    return jsonify(fetch_yahoo(url))

@app.route("/my-team")
def my_team():
    url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games;game_keys=nfl/teams"
    return jsonify(fetch_yahoo(url))

@app.route("/league/<league_id>")
def get_league(league_id):
    league_id = normalize_league_id(league_id)
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}"
    return jsonify(fetch_yahoo(url))

@app.route("/matchups/<league_id>/<week>")
def get_matchups(league_id, week):
    league_id = normalize_league_id(league_id)
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/scoreboard;week={week}"
    return jsonify(fetch_yahoo(url))

@app.route("/standings/<league_id>")
def get_standings(league_id):
    league_id = normalize_league_id(league_id)
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/standings"
    return jsonify(fetch_yahoo(url))

@app.route("/transactions/<league_id>")
def get_transactions(league_id):
    league_id = normalize_league_id(league_id)
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/transactions"
    return jsonify(fetch_yahoo(url))

@app.route("/teams/<league_id>")
def get_teams(league_id):
    league_id = normalize_league_id(league_id)
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/teams"
    return jsonify(fetch_yahoo(url))

@app.route("/roster/<team_key>")
def get_roster(team_key):
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/team/{team_key}/roster"
    return jsonify(fetch_yahoo(url))

@app.route("/all-rosters/<league_id>")
def all_rosters(league_id):
    league_id = normalize_league_id(league_id)
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/teams/roster"
    data = fetch_yahoo(url)

    # Trim the fat (remove headshots, image urls, unnecessary metadata)
    try:
        teams = data["fantasy_content"]["league"]["teams"]["team"]
        for team in teams:
            if "roster" in team:
                players = team["roster"]["players"]["player"]
                for player in players:
                    player.pop("headshot", None)
                    player.pop("image_url", None)
                    player.pop("editorial_team_url", None)
                    player.pop("url", None)
                    player.pop("uniform_number", None)
    except Exception as e:
        return jsonify({"error": str(e), "raw": data}), 500

    return jsonify(data)

@app.route("/available-players/<league_id>")
def available_players(league_id):
    league_id = normalize_league_id(league_id)
    params = request.args.to_dict()
    filters = ";".join([f"{k}={v}" for k, v in params.items()])
    url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/players{';' + filters if filters else ''}"
    return jsonify(fetch_yahoo(url))

# -------------------------------
# Run
# -------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
