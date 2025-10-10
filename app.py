import os
import json
import time
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

TOKEN_FILE = "token.json"

# -------------------------------
# Helpers
# -------------------------------

def save_token(token):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f)

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return json.load(f)
    return None

def normalize_league_id(league_id: str) -> str:
    """Ensure league_id is in full Yahoo key format if only digits are provided."""
    if league_id.isdigit():
        return f"461.l.{league_id}"
    return league_id

def yahoo_session():
    token = load_token()
    if not token:
        return None

    # proactive refresh if expiring within 5 minutes
    if token.get("expires_at") and token["expires_at"] - time.time() < 300:
        extra = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
        yahoo = OAuth2Session(CLIENT_ID, token=token)
        try:
            new_token = yahoo.refresh_token(TOKEN_URL, **extra)
            save_token(new_token)
            token = new_token
        except Exception as e:
            print("⚠️ Token refresh failed:", e)

    yahoo = OAuth2Session(
        CLIENT_ID,
        token=token,
        redirect_uri=REDIRECT_URI,
        auto_refresh_url=TOKEN_URL,
        auto_refresh_kwargs={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        token_updater=save_token
    )
    return yahoo

def fetch_yahoo(url):
    yahoo = yahoo_session()
    if not yahoo:
        return {"error": "Not authenticated"}
    resp = yahoo.get(url)
    resp.raise_for_status()
    return xmltodict.parse(resp.content)

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

    try:
        teams = data["fantasy_content"]["league"]["teams"]["team"]
        if isinstance(teams, dict):
            teams = [teams]

        simplified = []
        for team in teams:
            players = team.get("roster", {}).get("players", {}).get("player", [])
            if isinstance(players, dict):
                players = [players]

            simplified_players = []
            for p in players:
                simplified_players.append({
                    "player_id": p.get("player_id"),
                    "player_key": p.get("player_key"),
                    "name": p.get("name", {}).get("full"),
                    "position": p.get("display_position"),
                    "primary_position": p.get("primary_position"),
                    "team_abbr": p.get("editorial_team_abbr"),
                    "bye_week": p.get("bye_weeks", {}).get("week"),
                    "slot": p.get("selected_position", {}).get("position"),
                    "status": p.get("status")
                })

            simplified.append({
                "team_key": team.get("team_key"),
                "team_id": team.get("team_id"),
                "name": team.get("name"),
                "manager": team.get("managers", {}).get("manager", {}).get("nickname"),
                "players": simplified_players
            })

        return jsonify({"league_id": league_id, "teams": simplified})
    except Exception as e:
        return jsonify({"error": str(e), "raw": data}), 500

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

###############################################################
# 🧠 Yahoo Waivers / Free Agents Endpoint
###############################################################

@app.route("/waivers", methods=["GET"])
def get_waivers():
    """
    Fetch available players (waivers/free agents) filtered by position and status.

    Query params:
      league_id  – Yahoo league ID (required)
      position   – QB, RB, WR, TE, DEF, K (optional, defaults to ALL)
      status     – A (all available), FA (free agents), W (waivers) (optional, defaults to A)
    """

    league_id = normalize_league_id(request.args.get("league_id"))
    position = request.args.get("position", "ALL")
    status = request.args.get("status", "A")

    if not league_id:
        return jsonify({"error": "league_id is required"}), 400

    # Build Yahoo Players Collection endpoint
    resource_path = f"league/{league_id}/players;status={status}"
    if position and position != "ALL":
        resource_path += f";position={position}"

    yahoo_url = f"https://fantasysports.yahooapis.com/fantasy/v2/{resource_path}"

    # Use the shared fetch_yahoo() helper — handles auth + errors automatically
    data = fetch_yahoo(yahoo_url)

    parsed_players = parse_yahoo_players_response(data)
    return jsonify({"count": len(parsed_players), "players": parsed_players})


def parse_yahoo_players_response(data):
    """Parse Yahoo's Players Collection into a clean, flat list using player_key."""
    players = []
    try:
        league = data.get("fantasy_content", {}).get("league", {})
        players_data = league.get("players", {})

        # Yahoo may return "player" as a list or keyed dict
        player_entries = players_data.get("player")

        if isinstance(player_entries, list):
            for p in player_entries:
                name_info = p.get("name", {})
                players.append({
                    "player_key": p.get("player_key"),
                    "name": name_info.get("full"),
                    "team": p.get("editorial_team_abbr"),
                    "position": p.get("primary_position"),
                    "status": p.get("status", "FA"),
                })
        elif isinstance(players_data, dict):
            for _, value in players_data.items():
                if isinstance(value, dict) and "player" in value:
                    p = value["player"][0]
                    name_info = p.get("name", {})
                    players.append({
                        "player_key": p.get("player_key"),
                        "name": name_info.get("full"),
                        "team": p.get("editorial_team_abbr"),
                        "position": p.get("primary_position"),
                        "status": p.get("status", "FA"),
                    })

    except Exception as e:
        print(f"⚠️ Error parsing Yahoo player data: {e}")

    return players

