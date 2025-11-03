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
# 🏈 Player Model
###############################################################

class Player:
    """Represents a fantasy football player from Yahoo Fantasy API.
    
    This class can be extended with additional attributes and methods as needed.
    """
    
    def __init__(
        self,
        player_key: str | None = None,
        player_id: str | None = None,
        name: str | None = None,
        team: str | None = None,
        position: str | None = None,
        primary_position: str | None = None,
        display_position: str | None = None,
        status: str | None = None,
        bye_week: str | int | None = None,
        slot: str | None = None,
        eligible_positions: list[str] | None = None,
        **kwargs  # Allow for future extensibility
    ):
        """Initialize a Player instance.
        
        Args:
            player_key: Yahoo player key (e.g., "nfl.p.30199")
            player_id: Yahoo player ID
            name: Player's full name
            team: Team abbreviation (e.g., "SF")
            position: Primary position
            primary_position: Primary position (alternative field)
            display_position: Display position
            status: Player status (FA, W, etc.)
            bye_week: Bye week number
            slot: Current roster slot
            eligible_positions: List of eligible positions
            **kwargs: Additional attributes for future expansion
        """
        self.player_key = player_key
        self.player_id = player_id
        self.name = name
        self.team = team
        self.position = position or primary_position or display_position
        self.primary_position = primary_position or position
        self.display_position = display_position
        self.status = status
        self.bye_week = bye_week
        self.slot = slot
        self.eligible_positions = eligible_positions or []
        
        # Store any additional kwargs as attributes for extensibility
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    @classmethod
    def from_yahoo_data(cls, player_data: dict) -> "Player":
        """Create a Player instance from Yahoo API player data.
        
        Args:
            player_data: Raw player dictionary from Yahoo API
            
        Returns:
            Player instance
        """
        name_info = player_data.get("name", {})
        if isinstance(name_info, dict):
            name = name_info.get("full")
        else:
            name = name_info
        
        bye_weeks = player_data.get("bye_weeks", {})
        bye_week = bye_weeks.get("week") if isinstance(bye_weeks, dict) else None
        
        selected_position = player_data.get("selected_position", {})
        slot = selected_position.get("position") if isinstance(selected_position, dict) else None
        
        eligible_positions = player_data.get("eligible_positions", {})
        if isinstance(eligible_positions, dict):
            positions = eligible_positions.get("position", [])
            if isinstance(positions, str):
                positions = [positions]
        else:
            positions = []
        
        return cls(
            player_key=player_data.get("player_key"),
            player_id=player_data.get("player_id"),
            name=name,
            team=player_data.get("editorial_team_abbr"),
            position=player_data.get("primary_position"),
            primary_position=player_data.get("primary_position"),
            display_position=player_data.get("display_position"),
            status=player_data.get("status", "FA"),
            bye_week=bye_week,
            slot=slot,
            eligible_positions=positions
        )
    
    def to_dict(self) -> dict:
        """Convert Player instance to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of the player
        """
        result = {
            "player_key": self.player_key,
            "name": self.name,
            "team": self.team,
            "position": self.position,
            "status": self.status,
        }
        
        # Add optional fields if they exist
        if self.player_id is not None:
            result["player_id"] = self.player_id
        if self.primary_position is not None and self.primary_position != self.position:
            result["primary_position"] = self.primary_position
        if self.display_position is not None:
            result["display_position"] = self.display_position
        if self.bye_week is not None:
            result["bye_week"] = self.bye_week
        if self.slot is not None:
            result["slot"] = self.slot
        if self.eligible_positions:
            result["eligible_positions"] = self.eligible_positions
        
        return result
    
    def __repr__(self) -> str:
        """String representation of the Player."""
        return f"Player(key={self.player_key}, name={self.name}, position={self.position}, team={self.team})"


###############################################################
# 🧠 Yahoo Waivers / Free Agents Endpoint
###############################################################

# Constants for waivers endpoint
VALID_POSITIONS = {"QB", "RB", "WR", "TE", "DEF", "K"}
VALID_STATUSES = {"A", "FA", "W"}
DEFAULT_POSITION = "ALL"
DEFAULT_STATUS = "A"
YAHOO_BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"

def validate_waivers_params(league_id: str, position: str, status: str) -> tuple[bool, str]:
    """Validate waivers endpoint parameters and return (is_valid, error_message)."""
    if not league_id:
        return False, "league_id is required"
    
    if position != DEFAULT_POSITION and position not in VALID_POSITIONS:
        return False, f"Invalid position '{position}'. Must be one of: {', '.join(VALID_POSITIONS)}"
    
    if status not in VALID_STATUSES:
        return False, f"Invalid status '{status}'. Must be one of: {', '.join(VALID_STATUSES)}"
    
    return True, ""

def build_waivers_url(league_id: str, position: str, status: str) -> str:
    """Build the Yahoo API URL for fetching waivers/free agents."""
    resource_path = f"league/{league_id}/players;status={status}"
    if position != DEFAULT_POSITION:
        resource_path += f";position={position}"
    return f"{YAHOO_BASE_URL}/{resource_path}"

def extract_player_info(player_data: dict) -> Player:
    """Extract relevant player information from Yahoo player data and return a Player instance."""
    return Player.from_yahoo_data(player_data)

def parse_yahoo_players_response(data: dict) -> list[Player]:
    """Parse Yahoo's Players Collection into a clean, flat list of Player objects."""
    players = []
    
    try:
        league = data.get("fantasy_content", {}).get("league", {})
        players_data = league.get("players", {})
        player_entries = players_data.get("player")
        
        if not player_entries:
            return players
        
        # Handle both list and dict formats from Yahoo API
        if isinstance(player_entries, list):
            # Direct list of players
            for player_data in player_entries:
                players.append(Player.from_yahoo_data(player_data))
        elif isinstance(player_entries, dict):
            # Keyed dictionary format
            for value in player_entries.values():
                if isinstance(value, dict) and "player" in value:
                    player_data = value["player"][0] if isinstance(value["player"], list) else value["player"]
                    players.append(Player.from_yahoo_data(player_data))
                    
    except Exception as e:
        print(f"⚠️ Error parsing Yahoo player data: {e}")
        # Return empty list instead of raising to maintain API stability
    
    return players


@app.route("/waivers", methods=["GET"])
def get_waivers():
    """
    Fetch available players (waivers/free agents) filtered by position and status.

    Query params:
      league_id  – Yahoo league ID (required)
      position   – QB, RB, WR, TE, DEF, K (optional, defaults to ALL)
      status     – A (all available), FA (free agents), W (waivers) (optional, defaults to A)
    
    Returns:
      JSON response with count and list of players
    """
    # Extract and normalize parameters
    league_id = normalize_league_id(request.args.get("league_id"))
    position = request.args.get("position", DEFAULT_POSITION)
    status = request.args.get("status", DEFAULT_STATUS)
    
    # Validate parameters
    is_valid, error_message = validate_waivers_params(league_id, position, status)
    if not is_valid:
        return jsonify({"error": error_message}), 400
    
    try:
        # Build API URL and fetch data
        yahoo_url = build_waivers_url(league_id, position, status)
        data = fetch_yahoo(yahoo_url)
        
        # Check for API errors
        if "error" in data:
            return jsonify(data), 500
        
        # Parse and return player data
        parsed_players = parse_yahoo_players_response(data)
        return jsonify({
            "league_id": league_id,
            "position": position,
            "status": status,
            "count": len(parsed_players),
            "players": [player.to_dict() for player in parsed_players]
        })
        
    except Exception as e:
        print(f"⚠️ Error in get_waivers: {e}")
        return jsonify({"error": "Failed to fetch waivers data"}), 500


###############################################################
# 🔎 Player Stats (league-scoped)
###############################################################

def build_player_stats_url(league_id: str, player_key: str, stats_type: str | None, week: str | None) -> str:
    """Build Yahoo API URL to fetch a player's stats within a league context.
    Uses the league-scoped players collection so stat ids/values align with the league's settings.
    """
    resource = f"league/{league_id}/players;player_keys={player_key}/stats"
    # Append optional stats selectors per Yahoo format
    if stats_type:
        resource += f";type={stats_type}"
    if week:
        resource += f";week={week}"
    return f"{YAHOO_BASE_URL}/{resource}"


def get_league_stat_categories(league_id: str) -> dict:
    """Return a mapping of stat_id -> display_name for the given league.
    Falls back to 'name' if 'display_name' is unavailable.
    """
    try:
        settings_url = f"{YAHOO_BASE_URL}/league/{league_id}/settings"
        data = fetch_yahoo(settings_url)
        league = data.get("fantasy_content", {}).get("league", {})
        stats_node = (
            league.get("settings", {})
                 .get("stat_categories", {})
                 .get("stats", {})
                 .get("stat")
        )
        if not stats_node:
            return {}
        if isinstance(stats_node, dict):
            stats_node = [stats_node]
        mapping = {}
        for s in stats_node:
            sid = str(s.get("stat_id")) if s.get("stat_id") is not None else None
            if not sid:
                continue
            disp = s.get("display_name") or s.get("name") or f"stat_{sid}"
            mapping[sid] = disp
        return mapping
    except Exception as e:
        print(f"⚠️ Failed to fetch league settings/categories: {e}")
        return {}



def parse_player_stats_response(data: dict) -> dict:
    """Parse Yahoo's league-scoped player stats response into a flat dict.
    Returns a dict with player metadata and raw stats entries.
    """
    result = {
        "player_key": None,
        "name": None,
        "team": None,
        "positions": [],
        "stats_type": None,
        "week": None,
        "stats": [],  # list of {stat_id, value}
    }
    try:
        league = data.get("fantasy_content", {}).get("league", {})
        players_node = league.get("players", {})
        player_entry = players_node.get("player")

        # Normalize to a single player dict
        if isinstance(player_entry, list):
            player = player_entry[0]
        elif isinstance(player_entry, dict):
            player = player_entry
        else:
            return result

        # Player key & identity
        result["player_key"] = player.get("player_key")
        name_node = player.get("name", {})
        if isinstance(name_node, dict):
            result["name"] = name_node.get("full")
        result["team"] = player.get("editorial_team_abbr")

        # Positions (eligibility)
        pos_node = player.get("eligible_positions")
        if isinstance(pos_node, dict):
            pos_list = pos_node.get("position")
            if isinstance(pos_list, list):
                result["positions"] = pos_list
            elif isinstance(pos_list, str):
                result["positions"] = [pos_list]

        # Stats payload
        ps = player.get("player_stats", {})
        # Capture type & week selectors if present
        result["stats_type"] = ps.get("coverage_type") or ps.get("stats", {}).get("coverage_type")
        result["week"] = ps.get("week") or ps.get("stats", {}).get("week")

        stats_node = ps.get("stats", {}).get("stat")
        if stats_node:
            if isinstance(stats_node, dict):
                stats_node = [stats_node]
            for s in stats_node:
                sid = str(s.get("stat_id")) if s.get("stat_id") is not None else None
                val = s.get("value")
                # Some categories may return "-" for N/A; keep as-is to preserve fidelity
                result["stats"].append({"stat_id": sid, "value": val})
    except Exception as e:
        print(f"⚠️ Error parsing player stats: {e}")
    return result


# ---- Unified helpers for single/multi player fetching ----

def collect_player_keys_from_request(args) -> list[str]:
    """Collect player keys from query args.
    Supports:
      - repeated `player_key=...&player_key=...`
      - `player_keys` as comma-separated list
    Returns a de-duplicated, order-preserved list.
    """
    keys: list[str] = []
    # repeated player_key
    repeated = args.getlist("player_key") if hasattr(args, "getlist") else []
    for k in repeated:
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
    # comma-separated player_keys
    csv = args.get("player_keys")
    if csv:
        for k in csv.split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
    return keys


def _fetch_players_stats(league_id: str, player_keys: list[str], stats_type: str | None, week: str | None) -> list[dict]:
    """Fetch and enrich stats for one or more players in a league."""
    url = build_multi_player_stats_url(league_id, player_keys, stats_type, week)
    raw = fetch_yahoo(url)
    if isinstance(raw, dict) and raw.get("error"):
        # Bubble upstream error shape to caller by raising
        raise RuntimeError(json.dumps(raw))
    parsed_list = parse_multi_player_stats_response(raw)
    id_to_name = get_league_stat_categories(league_id)

    enriched: list[dict] = []
    for parsed in parsed_list:
        stats = []
        for s in parsed.get("stats", []):
            sid = s.get("stat_id")
            stats.append({
                "stat_id": sid,
                "stat_name": id_to_name.get(sid),
                "value": s.get("value"),
            })
        enriched.append({
            "league_id": league_id,
            "player_key": parsed.get("player_key"),
            "name": parsed.get("name"),
            "team": parsed.get("team"),
            "positions": parsed.get("positions", []),
            "stats_type": parsed.get("stats_type") or stats_type,
            "week": parsed.get("week") or week,
            "stats": stats,
        })
    return enriched


@app.route("/player", methods=["GET"])
def get_player_stats():
    """
    Get one or more players' stats in the context of a specific league.

    Query params:
      league_id    – Yahoo league ID (required; digits or full key like 461.l.XXXX)
      player_key   – optional; repeatable key(s), e.g., player_key=nfl.p.30199&player_key=nfl.p.12345
      player_keys  – optional; comma-separated keys, e.g., nfl.p.30199,nfl.p.12345
      type         – optional; season or week
      week         – optional; required if type=week

    Returns:
      {"count": <n>, "players": [ PlayerStatsPayload, ... ]}
    """
    # Extract & validate
    raw_league_id = request.args.get("league_id")
    stats_type = request.args.get("type")
    week = request.args.get("week")

    player_keys = collect_player_keys_from_request(request.args)

    if not raw_league_id:
        return jsonify({"error": "league_id is required"}), 400
    if not player_keys:
        return jsonify({"error": "Provide player_key (repeatable) and/or player_keys (comma-separated)"}), 400

    league_id = normalize_league_id(raw_league_id)

    if stats_type == "week" and not week:
        return jsonify({"error": "week is required when type=week"}), 400

    try:
        enriched = _fetch_players_stats(league_id, player_keys, stats_type, week)
        return jsonify({"count": len(enriched), "players": enriched})
    except RuntimeError as upstream:
        # Upstream Yahoo error bubbled as JSON string; attempt to parse
        try:
            return jsonify(json.loads(str(upstream))), 502
        except Exception:
            return jsonify({"error": "Upstream error"}), 502
    except Exception as e:
        print(f"⚠️ Error in get_player_stats: {e}")
        return jsonify({"error": "Failed to fetch player stats"}), 500


###############################################################
# 👥 Multi-Player Stats + OpenAPI spec
###############################################################

def build_multi_player_stats_url(league_id: str, player_keys: list[str], stats_type: str | None, week: str | None) -> str:
    """Build Yahoo API URL for multiple players in a league context."""
    joined = ",".join(player_keys)
    resource = f"league/{league_id}/players;player_keys={joined}/stats"
    if stats_type:
        resource += f";type={stats_type}"
    if week:
        resource += f";week={week}"
    return f"{YAHOO_BASE_URL}/{resource}"


def parse_multi_player_stats_response(data: dict) -> list[dict]:
    """Parse Yahoo response where league->players->player can be a list of players."""
    results: list[dict] = []
    try:
        league = data.get("fantasy_content", {}).get("league", {})
        players_node = league.get("players", {})
        player_entries = players_node.get("player")
        if not player_entries:
            return results
        # Normalize to list
        if isinstance(player_entries, dict):
            player_entries = [player_entries]
        for entry in player_entries:
            # Reuse single-player parser by wrapping the shape the same way
            wrapped = {
                "fantasy_content": {
                    "league": {"players": {"player": entry}}
                }
            }
            results.append(parse_player_stats_response(wrapped))
    except Exception as e:
        print(f"⚠️ Error parsing multi-player stats: {e}")
    return results




# Only /player endpoint is documented in OpenAPI spec.
@app.route("/openapi.json", methods=["GET"])
def openapi_spec():
    """Serve a minimal OpenAPI 3.0 spec for the unified /player endpoint."""
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "BlitzGremlin Fantasy API",
            "version": "1.0.0",
            "description": "Yahoo Fantasy league-scoped player stats endpoints"
        },
        "paths": {
            "/player": {
                "get": {
                    "summary": "Get one or more players' stats (league-scoped)",
                    "parameters": [
                        {"name": "league_id", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "player_key", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Repeatable. Provide one or more player_key params."},
                        {"name": "player_keys", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Comma-separated Yahoo player keys."},
                        {"name": "type", "in": "query", "required": False, "schema": {"type": "string", "enum": ["season", "week"]}},
                        {"name": "week", "in": "query", "required": False, "schema": {"type": "string"}}
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/PlayersStatsResponse"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "EnrichedStat": {
                    "type": "object",
                    "properties": {
                        "stat_id": {"type": "string"},
                        "stat_name": {"type": ["string", "null"]},
                        "value": {"type": ["string", "number", "null"]}
                    }
                },
                "PlayerStatsPayload": {
                    "type": "object",
                    "properties": {
                        "league_id": {"type": "string"},
                        "player_key": {"type": "string"},
                        "name": {"type": ["string", "null"]},
                        "team": {"type": ["string", "null"]},
                        "positions": {"type": "array", "items": {"type": "string"}},
                        "stats_type": {"type": ["string", "null"]},
                        "week": {"type": ["string", "null"]},
                        "stats": {"type": "array", "items": {"$ref": "#/components/schemas/EnrichedStat"}}
                    }
                },
                "PlayerStatsResponse": {"$ref": "#/components/schemas/PlayerStatsPayload"},
                "PlayersStatsResponse": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer"},
                        "players": {"type": "array", "items": {"$ref": "#/components/schemas/PlayerStatsPayload"}}
                    }
                }
            }
        }
    }
    return jsonify(spec)

