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
        """Get roster for a specific team with enriched stats."""
        url = f"{YAHOO_BASE_URL}/team/{team_key}/roster"
        data = fetch_yahoo(url)
        
        if isinstance(data, dict) and data.get("error"):
            return jsonify(data), 500
        
        league_id = extract_league_id_from_team_key(team_key)
        
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
                        batch_fetch_player_stats(player_objects, league_id)
                    
                    players = [
                        player_obj.to_dict(include_stats=True, league_id=league_id)
                        for player_obj in player_objects
                    ]
                    
                    if players:
                        return jsonify({
                            "team_key": team_key,
                            "league_id": league_id,
                            "count": len(players),
                            "players": players,
                            "raw": data
                        })
            except Exception as e:
                logger.error(f"Error parsing roster with stats: {e}")
        
        return jsonify(data)
    
    @app.route("/all-rosters/<league_id>")
    def all_rosters(league_id):
        """Get all rosters in a league with enriched stats."""
        league_id = normalize_league_id(league_id)
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
            if player_objects:
                batch_fetch_player_stats(player_objects, league_id)
            
            # Organize players back by team
            simplified = []
            for team_idx, team in enumerate(teams):
                simplified_players = []
                
                for i, (t_idx, p) in enumerate(all_players_data):
                    if t_idx == team_idx:
                        player_obj = player_objects[i]
                        player_dict = player_obj.to_dict(include_stats=True, league_id=league_id)
                        
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

            return jsonify({"league_id": league_id, "teams": simplified})
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
        """Get available players in a league."""
        league_id = normalize_league_id(league_id)
        params = request.args.to_dict()
        filters = ";".join([f"{k}={v}" for k, v in params.items()])
        url = f"{YAHOO_BASE_URL}/league/{league_id}/players{';' + filters if filters else ''}"
        data = fetch_yahoo(url)
        
        if isinstance(data, dict) and data.get("error"):
            return jsonify(data), 500
        
        try:
            parsed_players = parse_yahoo_players_response(data)
            if parsed_players:
                batch_fetch_player_stats(parsed_players, league_id)
                
                return jsonify({
                    "league_id": league_id,
                    "count": len(parsed_players),
                    "players": [
                        player.to_dict(include_stats=True, league_id=league_id)
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
        """
        league_id = normalize_league_id(request.args.get("league_id"))
        position = request.args.get("position", DEFAULT_POSITION)
        status = request.args.get("status", DEFAULT_STATUS)
        
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
                batch_fetch_player_stats(parsed_players, league_id)
            
            return jsonify({
                "league_id": league_id,
                "position": position,
                "status": status,
                "count": len(parsed_players),
                "players": [
                    player.to_dict(include_stats=True, league_id=league_id)
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


def register_all_routes(app: Flask) -> None:
    """Register all routes with the Flask app."""
    register_auth_routes(app)
    register_info_routes(app)
    register_league_routes(app)
    register_roster_routes(app)
    register_player_routes(app)

