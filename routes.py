"""Flask routes for BlitzGremlin Yahoo Fantasy API."""
import json
import logging
from flask import Flask, redirect, request, session, jsonify

from config import (
    CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, AUTH_BASE_URL, TOKEN_URL,
    VALID_POSITIONS, VALID_STATUSES, DEFAULT_POSITION, DEFAULT_STATUS, YAHOO_BASE_URL
)
from auth import save_token, yahoo_session
from utils import normalize_league_id, extract_league_id_from_team_key
from models import Player
from yahoo_api import (
    fetch_yahoo, parse_yahoo_players_response, batch_fetch_player_stats,
    collect_player_keys_from_request, _fetch_players_stats
)

logger = logging.getLogger(__name__)


# ============================================================================
# Authentication routes
# ============================================================================

def register_auth_routes(app: Flask) -> None:
    """Register authentication-related routes."""
    
    @app.route("/login")
    def login():
        """Initiate Yahoo OAuth login flow."""
        from requests_oauthlib import OAuth2Session
        yahoo = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI)
        authorization_url, state = yahoo.authorization_url(AUTH_BASE_URL)
        session["oauth_state"] = state
        return redirect(authorization_url)
    
    @app.route("/callback")
    def callback():
        """Handle Yahoo OAuth callback."""
        from requests_oauthlib import OAuth2Session
        yahoo = OAuth2Session(
            CLIENT_ID,
            state=session.get("oauth_state"),
            redirect_uri=REDIRECT_URI
        )
        token = yahoo.fetch_token(
            TOKEN_URL,
            client_secret=CLIENT_SECRET,
            authorization_response=request.url
        )
        save_token(token)
        return "Authentication complete! You can now use the API."


# ============================================================================
# Basic info routes
# ============================================================================

def register_info_routes(app: Flask) -> None:
    """Register basic info routes."""
    
    @app.route("/")
    def index():
        return "BlitzGremlin Yahoo Fantasy API is live 🎉"
    
    @app.route("/profile")
    def profile():
        """Get user profile information."""
        url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1"
        return jsonify(fetch_yahoo(url))
    
    @app.route("/my-leagues")
    def my_leagues():
        """Get user's leagues."""
        url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games;game_keys=nfl/leagues"
        return jsonify(fetch_yahoo(url))
    
    @app.route("/my-team")
    def my_team():
        """Get user's team."""
        url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games;game_keys=nfl/teams"
        return jsonify(fetch_yahoo(url))


# ============================================================================
# League routes
# ============================================================================

def register_league_routes(app: Flask) -> None:
    """Register league-related routes."""
    
    @app.route("/league/<league_id>")
    def get_league(league_id):
        """Get league information."""
        league_id = normalize_league_id(league_id)
        url = f"{YAHOO_BASE_URL}/league/{league_id}"
        return jsonify(fetch_yahoo(url))
    
    @app.route("/matchups/<league_id>/<week>")
    def get_matchups(league_id, week):
        """Get matchups for a specific week."""
        league_id = normalize_league_id(league_id)
        url = f"{YAHOO_BASE_URL}/league/{league_id}/scoreboard;week={week}"
        return jsonify(fetch_yahoo(url))
    
    @app.route("/standings/<league_id>")
    def get_standings(league_id):
        """Get league standings."""
        league_id = normalize_league_id(league_id)
        url = f"{YAHOO_BASE_URL}/league/{league_id}/standings"
        return jsonify(fetch_yahoo(url))
    
    @app.route("/transactions/<league_id>")
    def get_transactions(league_id):
        """Get league transactions."""
        league_id = normalize_league_id(league_id)
        url = f"{YAHOO_BASE_URL}/league/{league_id}/transactions"
        return jsonify(fetch_yahoo(url))
    
    @app.route("/teams/<league_id>")
    def get_teams(league_id):
        """Get all teams in a league."""
        league_id = normalize_league_id(league_id)
        url = f"{YAHOO_BASE_URL}/league/{league_id}/teams"
        return jsonify(fetch_yahoo(url))


# ============================================================================
# Roster routes
# ============================================================================

def register_roster_routes(app: Flask) -> None:
    """Register roster-related routes."""
    
    @app.route("/roster/<team_key>")
    def get_roster(team_key):
        """Get roster for a specific team with enriched stats.
        
        Query params:
          week  – Optional week number for week-specific stats
        """
        url = f"{YAHOO_BASE_URL}/team/{team_key}/roster"
        data = fetch_yahoo(url)
        
        if isinstance(data, dict) and data.get("error"):
            return jsonify(data), 500
        
        league_id = extract_league_id_from_team_key(team_key)
        week = request.args.get("week")
        
        if league_id:
            try:
                teams = data.get("fantasy_content", {}).get("team", {})
                roster = teams.get("roster", {})
                players_data = roster.get("players", {})
                player_entries = players_data.get("player")
                
                if player_entries:
                    player_list = player_entries if isinstance(player_entries, list) else [player_entries]
                    player_objects = [Player.from_yahoo_data(p) for p in player_list]
                    
                    if player_objects:
                        batch_fetch_player_stats(player_objects, league_id, week=week)
                    
                    players = [
                        player_obj.to_dict(include_stats=True, league_id=league_id, week=week)
                        for player_obj in player_objects
                    ]
                    
                    if players:
                        return jsonify({
                            "team_key": team_key,
                            "league_id": league_id,
                            "week": week,
                            "count": len(players),
                            "players": players,
                            "raw": data
                        })
            except Exception as e:
                logger.error(f"Error parsing roster with stats: {e}")
        
        return jsonify(data)
    
    @app.route("/all-rosters/<league_id>")
    def all_rosters(league_id):
        """Get all rosters in a league with enriched stats.
        
        Query params:
          week  – Optional week number for week-specific stats
        """
        league_id = normalize_league_id(league_id)
        week = request.args.get("week")
        url = f"{YAHOO_BASE_URL}/league/{league_id}/teams/roster"
        data = fetch_yahoo(url)

        try:
            teams = data["fantasy_content"]["league"]["teams"]["team"]
            if isinstance(teams, dict):
                teams = [teams]

            # Collect all players from all teams first
            all_players_data = []
            for team_idx, team in enumerate(teams):
                players = team.get("roster", {}).get("players", {}).get("player", [])
                if isinstance(players, dict):
                    players = [players]
                for p in players:
                    all_players_data.append((team_idx, p))
            
            # Create all Player objects
            player_objects = [Player.from_yahoo_data(p) for _, p in all_players_data]
            
            # Batch fetch stats for all players
            # This populates the cache for all players in one or few API calls
            if player_objects:
                try:
                    batch_fetch_player_stats(player_objects, league_id, week=week)
                except Exception as e:
                    logger.error(f"Error in batch fetch for all-rosters: {e}")
                    # Continue without stats rather than failing entirely
            
            # Organize players back by team
            # Stats should be cached from batch fetch, so to_dict() will use cache
            simplified = []
            for team_idx, team in enumerate(teams):
                simplified_players = []
                
                for i, (t_idx, p) in enumerate(all_players_data):
                    if t_idx == team_idx:
                        player_obj = player_objects[i]
                        try:
                            player_dict = player_obj.to_dict(
                                include_stats=True,
                                league_id=league_id,
                                week=week
                            )
                        except Exception as e:
                            logger.warning(f"Error getting stats for player {player_obj.player_key}: {e}")
                            # Return player without stats if there's an error
                            player_dict = player_obj.to_dict(include_stats=False)
                        
                        # Add additional fields for backward compatibility
                        player_dict.update({
                            "player_id": p.get("player_id"),
                            "team_abbr": p.get("editorial_team_abbr"),
                        })
                        
                        # Preserve original field names
                        _preserve_roster_fields(player_dict, p)
                        simplified_players.append(player_dict)
                
                simplified.append({
                    "team_key": team.get("team_key"),
                    "team_id": team.get("team_id"),
                    "name": team.get("name"),
                    "manager": team.get("managers", {}).get("manager", {}).get("nickname"),
                    "players": simplified_players
                })

            return jsonify({
                "league_id": league_id,
                "week": week,
                "teams": simplified
            })
        except Exception as e:
            return jsonify({"error": str(e), "raw": data}), 500


def _preserve_roster_fields(player_dict: dict, original_data: dict) -> None:
    """Preserve original field names for backward compatibility."""
    if "position" not in player_dict:
        player_dict["position"] = original_data.get("display_position")
    if "primary_position" not in player_dict:
        player_dict["primary_position"] = original_data.get("primary_position")
    if "bye_week" not in player_dict:
        player_dict["bye_week"] = original_data.get("bye_weeks", {}).get("week")
    if "slot" not in player_dict:
        player_dict["slot"] = original_data.get("selected_position", {}).get("position")


# ============================================================================
# Player routes
# ============================================================================

def register_player_routes(app: Flask) -> None:
    """Register player-related routes."""
    
    @app.route("/available-players/<league_id>")
    def available_players(league_id):
        """Get available players in a league.
        
        Query params:
          week  – Optional week number for week-specific stats
          Other params are passed through to Yahoo API as filters
        """
        league_id = normalize_league_id(league_id)
        week = request.args.get("week")
        params = request.args.to_dict()
        # Remove week from filters since we handle it separately
        filters_dict = {k: v for k, v in params.items() if k != "week"}
        filters = ";".join([f"{k}={v}" for k, v in filters_dict.items()])
        url = f"{YAHOO_BASE_URL}/league/{league_id}/players{';' + filters if filters else ''}"
        data = fetch_yahoo(url)
        
        if isinstance(data, dict) and data.get("error"):
            return jsonify(data), 500
        
        try:
            parsed_players = parse_yahoo_players_response(data)
            if parsed_players:
                batch_fetch_player_stats(parsed_players, league_id, week=week)
                
                return jsonify({
                    "league_id": league_id,
                    "week": week,
                    "count": len(parsed_players),
                    "players": [
                        player.to_dict(
                            include_stats=True,
                            league_id=league_id,
                            week=week
                        )
                        for player in parsed_players
                    ],
                    "raw": data
                })
        except Exception as e:
            logger.error(f"Error parsing available players: {e}")
        
        return jsonify(data)
    
    @app.route("/waivers", methods=["GET"])
    def get_waivers():
        """Fetch available players (waivers/free agents) filtered by position and status.
        
        Query params:
          league_id  – Yahoo league ID (required)
          position   – QB, RB, WR, TE, DEF, K (optional, defaults to ALL)
          status     – A (all available), FA (free agents), W (waivers) (optional, defaults to A)
          week       – Optional week number for week-specific stats
        """
        league_id = normalize_league_id(request.args.get("league_id"))
        position = request.args.get("position", DEFAULT_POSITION)
        status = request.args.get("status", DEFAULT_STATUS)
        week = request.args.get("week")
        
        # Validate parameters
        is_valid, error_message = _validate_waivers_params(league_id, position, status)
        if not is_valid:
            return jsonify({"error": error_message}), 400
        
        try:
            yahoo_url = _build_waivers_url(league_id, position, status)
            data = fetch_yahoo(yahoo_url)
            
            if "error" in data:
                return jsonify(data), 500
            
            parsed_players = parse_yahoo_players_response(data)
            
            if parsed_players:
                batch_fetch_player_stats(parsed_players, league_id, week=week)
            
            return jsonify({
                "league_id": league_id,
                "position": position,
                "status": status,
                "week": week,
                "count": len(parsed_players),
                "players": [
                    player.to_dict(
                        include_stats=True,
                        league_id=league_id,
                        week=week
                    )
                    for player in parsed_players
                ]
            })
            
        except Exception as e:
            logger.error(f"Error in get_waivers: {e}")
            return jsonify({"error": "Failed to fetch waivers data"}), 500
    
    @app.route("/player", methods=["GET"])
    def get_player_stats():
        """Get one or more players' stats in the context of a specific league.
        
        Query params:
          league_id    – Yahoo league ID (required; digits or full key like 461.l.XXXX)
          player_key   – optional; repeatable key(s)
          player_keys  – optional; comma-separated keys
          type         – optional; season or week
          week         – optional; required if type=week
        """
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
            
            returned_keys = {p.get("player_key") for p in enriched if p.get("player_key")}
            requested_keys = set(player_keys)
            missing_keys = requested_keys - returned_keys
            
            response = {
                "count": len(enriched),
                "players": enriched
            }
            
            if missing_keys:
                response["warnings"] = {
                    "skipped_players": list(missing_keys),
                    "message": f"Could not fetch stats for {len(missing_keys)} player(s). They may not exist or may not have stats available."
                }
            
            return jsonify(response)
        except RuntimeError as upstream:
            try:
                return jsonify(json.loads(str(upstream))), 502
            except Exception:
                return jsonify({"error": "Upstream error"}), 502
        except Exception as e:
            logger.error(f"Error in get_player_stats: {e}")
            return jsonify({"error": "Failed to fetch player stats"}), 500
    
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


# ============================================================================
# Helper functions
# ============================================================================

def _validate_waivers_params(league_id: str, position: str, status: str) -> tuple[bool, str]:
    """Validate waivers endpoint parameters."""
    if not league_id:
        return False, "league_id is required"
    
    if position != DEFAULT_POSITION and position not in VALID_POSITIONS:
        return False, f"Invalid position '{position}'. Must be one of: {', '.join(VALID_POSITIONS)}"
    
    if status not in VALID_STATUSES:
        return False, f"Invalid status '{status}'. Must be one of: {', '.join(VALID_STATUSES)}"
    
    return True, ""


def _build_waivers_url(league_id: str, position: str, status: str) -> str:
    """Build the Yahoo API URL for fetching waivers/free agents."""
    resource_path = f"league/{league_id}/players;status={status}"
    if position != DEFAULT_POSITION:
        resource_path += f";position={position}"
    return f"{YAHOO_BASE_URL}/{resource_path}"


def register_test_routes(app: Flask) -> None:
    """Register test/debugging routes."""
    
    @app.route("/test/player", methods=["GET"])
    def test_player_fetch():
        """Test endpoint that checks auth, confirms login, and fetches player data without cache.
        
        Uses hardcoded values:
        - Player key: 461.p.7200
        - League ID: 461.l.1157326
        
        Returns:
            JSON with auth status, login confirmation, and player data
        """
        from auth import load_token, yahoo_session, save_token
        from requests_oauthlib import OAuth2Session
        import time
        from config import CLIENT_ID, CLIENT_SECRET, TOKEN_URL
        from models import Player
        from yahoo_api import fetch_yahoo, build_player_stats_url, parse_player_stats_response, get_league_stat_categories
        
        response_data = {
            "test": "player_fetch",
            "timestamp": time.time(),
            "auth_status": {},
            "login_confirmed": False,
            "player_data": None,
            "errors": []
        }
        
        # Check if token exists
        token = load_token()
        if not token:
            response_data["auth_status"] = {
                "has_token": False,
                "message": "No token found. Please visit /login to authenticate."
            }
            response_data["errors"].append("No authentication token found")
            return jsonify(response_data), 401
        
        # Check if token is expired or expiring soon
        expires_at = token.get("expires_at")
        current_time = time.time()
        token_age = expires_at - current_time if expires_at else None
        
        if expires_at and token_age is not None:
            if token_age < 0:
                response_data["auth_status"] = {
                    "has_token": True,
                    "expired": True,
                    "expired_seconds_ago": abs(token_age),
                    "message": "Token expired. Attempting refresh..."
                }
                response_data["errors"].append("Token has expired")
            elif token_age < 300:  # Less than 5 minutes
                response_data["auth_status"] = {
                    "has_token": True,
                    "expiring_soon": True,
                    "expires_in_seconds": token_age,
                    "message": "Token expiring soon. Refreshing..."
                }
            else:
                response_data["auth_status"] = {
                    "has_token": True,
                    "valid": True,
                    "expires_in_seconds": token_age,
                    "message": "Token is valid"
                }
        
        # Attempt to refresh token if needed
        try:
            yahoo = yahoo_session()
            if not yahoo:
                response_data["auth_status"]["session_created"] = False
                response_data["errors"].append("Failed to create Yahoo session")
                return jsonify(response_data), 401
            
            response_data["auth_status"]["session_created"] = True
            
            # Verify login by fetching profile (simple check)
            try:
                profile_url = "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1"
                profile_data = fetch_yahoo(profile_url)
                
                if isinstance(profile_data, dict) and profile_data.get("error"):
                    response_data["login_confirmed"] = False
                    response_data["errors"].append(f"Login verification failed: {profile_data.get('error')}")
                    return jsonify(response_data), 401
                
                response_data["login_confirmed"] = True
                response_data["auth_status"]["verified"] = True
                response_data["auth_status"]["message"] = "Login confirmed successfully"
                
            except Exception as e:
                response_data["login_confirmed"] = False
                response_data["errors"].append(f"Failed to verify login: {str(e)}")
                return jsonify(response_data), 401
            
        except Exception as e:
            response_data["auth_status"]["refresh_failed"] = True
            response_data["errors"].append(f"Token refresh failed: {str(e)}")
            return jsonify(response_data), 401
        
        # Now fetch player data without cache
        try:
            player_key = "461.p.7200"
            league_id = "461.l.1157326"
            
            # Create a Player object
            player = Player(player_key=player_key)
            
            # Fetch stats with force_refresh=True to bypass cache
            stats = player.get_stats(league_id, force_refresh=True)
            
            if stats:
                response_data["player_data"] = {
                    "player_key": player_key,
                    "league_id": league_id,
                    "stats": stats
                }
                response_data["success"] = True
            else:
                response_data["errors"].append("Failed to fetch player stats")
                response_data["player_data"] = {
                    "player_key": player_key,
                    "league_id": league_id,
                    "stats": None
                }
            
        except Exception as e:
            logger.error(f"Error fetching player data in test endpoint: {e}")
            response_data["errors"].append(f"Error fetching player data: {str(e)}")
            response_data["player_data"] = {
                "player_key": "461.p.7200",
                "league_id": "461.l.1157326",
                "error": str(e)
            }
        
        status_code = 200 if response_data.get("success") and response_data["login_confirmed"] else 500
        return jsonify(response_data), status_code


def register_all_routes(app: Flask) -> None:
    """Register all routes with the Flask app."""
    register_auth_routes(app)
    register_info_routes(app)
    register_league_routes(app)
    register_roster_routes(app)
    register_player_routes(app)
    register_test_routes(app)

