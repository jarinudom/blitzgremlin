"""Yahoo Fantasy API wrapper functions."""
import json
import logging
import requests
import xmltodict
from typing import TYPE_CHECKING

from config import YAHOO_BASE_URL
from auth import yahoo_session

if TYPE_CHECKING:
    from models import Player

logger = logging.getLogger(__name__)


def fetch_yahoo(url: str) -> dict:
    """Fetch data from Yahoo Fantasy API with logging.
    
    Args:
        url: Yahoo API URL to fetch
        
    Returns:
        Parsed XML response as dictionary, or {"error": ...} on failure
    """
    yahoo = yahoo_session()
    if not yahoo:
        logger.warning("Yahoo API request failed: Not authenticated")
        return {"error": "Not authenticated"}
    
    logger.info(f"Yahoo API request: {url}")
    
    try:
        resp = yahoo.get(url)
        status_code = resp.status_code
        
        if resp.ok:
            parsed_data = xmltodict.parse(resp.content)
            
            # Check for errors in parsed response (Yahoo sometimes returns 200 with errors)
            if isinstance(parsed_data, dict) and _has_error(parsed_data):
                logger.error(f"Yahoo API returned error in response: {status_code} - URL: {url}")
                logger.error(f"Yahoo API error response: {json.dumps(parsed_data, indent=2)}")
            else:
                logger.info(f"Yahoo API response: {status_code} OK")
            
            return parsed_data
        else:
            _log_error_response(resp, url)
            resp.raise_for_status()
            return xmltodict.parse(resp.content)
            
    except requests.exceptions.HTTPError as e:
        _log_http_error(e, url)
        raise
    except Exception as e:
        logger.error(f"Yahoo API request exception: {type(e).__name__}: {str(e)} - URL: {url}")
        raise


def _has_error(data: dict) -> bool:
    """Check if Yahoo API response contains an error."""
    if data.get("error"):
        return True
    
    fantasy_content = data.get("fantasy_content", {})
    if isinstance(fantasy_content, dict):
        return bool(fantasy_content.get("error"))
    
    return False


def _log_error_response(resp: requests.Response, url: str) -> None:
    """Log error response from Yahoo API."""
    logger.error(f"Yahoo API response: {resp.status_code} - URL: {url}")
    try:
        error_data = xmltodict.parse(resp.content)
        logger.error(f"Yahoo API error response: {json.dumps(error_data, indent=2)}")
    except Exception:
        content_preview = resp.text[:500] if resp.text else "No content"
        logger.error(f"Yahoo API error response (raw): {content_preview}")


def _log_http_error(e: requests.exceptions.HTTPError, url: str) -> None:
    """Log HTTP error from Yahoo API."""
    logger.error(f"Yahoo API HTTP error: {e.response.status_code} - URL: {url}")
    try:
        error_data = xmltodict.parse(e.response.content)
        logger.error(f"Yahoo API error response: {json.dumps(error_data, indent=2)}")
    except Exception:
        content_preview = e.response.text[:500] if e.response.text else "No content"
        logger.error(f"Yahoo API error response (raw): {content_preview}")


# ============================================================================
# Player parsing functions
# ============================================================================

def parse_yahoo_players_response(data: dict) -> list["Player"]:
    """Parse Yahoo's Players Collection into a clean, flat list of Player objects.
    
    Args:
        data: Raw Yahoo API response dictionary
        
    Returns:
        List of Player objects
    """
    from models import Player  # Import here to avoid circular dependency
    
    players = []
    
    try:
        league = data.get("fantasy_content", {}).get("league", {})
        players_data = league.get("players", {})
        player_entries = players_data.get("player")
        
        if not player_entries:
            return players
        
        # Handle both list and dict formats from Yahoo API
        if isinstance(player_entries, list):
            for player_data in player_entries:
                players.append(Player.from_yahoo_data(player_data))
        elif isinstance(player_entries, dict):
            # Keyed dictionary format
            for value in player_entries.values():
                if isinstance(value, dict) and "player" in value:
                    player_data = value["player"][0] if isinstance(value["player"], list) else value["player"]
                    players.append(Player.from_yahoo_data(player_data))
                    
    except Exception as e:
        logger.error(f"Error parsing Yahoo player data: {e}")
    
    return players


# ============================================================================
# Player stats functions
# ============================================================================

def build_player_stats_url(
    league_id: str,
    player_key: str,
    stats_type: str | None = None,
    week: str | None = None
) -> str:
    """Build Yahoo API URL to fetch a player's stats within a league context.
    
    Args:
        league_id: Yahoo league ID
        player_key: Yahoo player key
        stats_type: Optional stats type (not used in URL, but kept for consistency)
        week: Optional week number (not used in URL, but kept for consistency)
    
    Returns:
        Yahoo API URL string
    """
    resource = f"league/{league_id}/players;player_keys={player_key}/stats"
    return f"{YAHOO_BASE_URL}/{resource}"


def build_multi_player_stats_url(
    league_id: str,
    player_keys: list[str],
    stats_type: str | None = None,
    week: str | None = None
) -> str:
    """Build Yahoo API URL for multiple players in a league context.
    
    Note: Yahoo API doesn't support type/week as semicolon params after /stats.
    We fetch all available stats.
    
    Args:
        league_id: Yahoo league ID
        player_keys: List of Yahoo player keys
        stats_type: Optional stats type (not used, kept for consistency)
        week: Optional week number (not used, kept for consistency)
    
    Returns:
        Yahoo API URL string
    """
    joined = ",".join(player_keys)
    resource = f"league/{league_id}/players;player_keys={joined}/stats"
    return f"{YAHOO_BASE_URL}/{resource}"


def get_league_stat_categories(league_id: str) -> dict[str, str]:
    """Return a mapping of stat_id -> display_name for the given league.
    
    Args:
        league_id: Yahoo league ID
        
    Returns:
        Dictionary mapping stat_id to display_name
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
        logger.error(f"Failed to fetch league settings/categories: {e}")
        return {}


def parse_player_stats_response(data: dict) -> dict:
    """Parse Yahoo's league-scoped player stats response into a flat dict.
    
    Args:
        data: Raw Yahoo API response dictionary
        
    Returns:
        Dictionary with player metadata and raw stats entries
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
        result["stats_type"] = ps.get("coverage_type") or ps.get("stats", {}).get("coverage_type")
        result["week"] = ps.get("week") or ps.get("stats", {}).get("week")

        stats_node = ps.get("stats", {}).get("stat")
        if stats_node:
            if isinstance(stats_node, dict):
                stats_node = [stats_node]
            for s in stats_node:
                sid = str(s.get("stat_id")) if s.get("stat_id") is not None else None
                val = s.get("value")
                result["stats"].append({"stat_id": sid, "value": val})
                
    except Exception as e:
        logger.error(f"Error parsing player stats: {e}")
    
    return result


def parse_multi_player_stats_response(data: dict) -> list[dict]:
    """Parse Yahoo response where league->players->player can be a list of players.
    
    Args:
        data: Raw Yahoo API response dictionary
        
    Returns:
        List of parsed player stats dictionaries
    """
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
        logger.error(f"Error parsing multi-player stats: {e}")
    
    return results


# ============================================================================
# Batch stats fetching
# ============================================================================

def collect_player_keys_from_request(args) -> list[str]:
    """Collect player keys from query args.
    
    Supports:
      - repeated `player_key=...&player_key=...`
      - `player_keys` as comma-separated list
    
    Args:
        args: Flask request.args object
        
    Returns:
        De-duplicated, order-preserved list of player keys
    """
    keys: list[str] = []
    
    # Repeated player_key params
    repeated = args.getlist("player_key") if hasattr(args, "getlist") else []
    for k in repeated:
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
    
    # Comma-separated player_keys param
    csv = args.get("player_keys")
    if csv:
        for k in csv.split(","):
            k = k.strip()
            if k and k not in keys:
                keys.append(k)
    
    return keys


def _fetch_players_stats(
    league_id: str,
    player_keys: list[str],
    stats_type: str | None = None,
    week: str | None = None
) -> list[dict]:
    """Fetch and enrich stats for one or more players in a league.
    
    If batch request fails due to invalid player keys, will attempt individual requests
    for valid players.
    
    Args:
        league_id: Yahoo league ID
        player_keys: List of Yahoo player keys
        stats_type: Optional stats type ("season" or "week")
        week: Optional week number
    
    Returns:
        List of enriched stats dictionaries
    """
    if not player_keys:
        return []
    
    # Try batch request first
    try:
        url = build_multi_player_stats_url(league_id, player_keys, stats_type, week)
        raw = fetch_yahoo(url)
        
        if isinstance(raw, dict) and raw.get("error"):
            error = raw.get("error", {})
            error_desc = error.get("description", "") if isinstance(error, dict) else ""
            
            # If error mentions invalid player keys, try individual requests
            if "does not exist" in error_desc or "invalid" in error_desc.lower():
                logger.warning(f"Batch request failed with invalid player keys, trying individual requests: {error_desc}")
                return _fetch_players_stats_individual(league_id, player_keys, stats_type, week)
            
            raise RuntimeError(json.dumps(raw))
        
        # Successfully parsed batch response
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
        
    except requests.exceptions.HTTPError as e:
        # Check if it's a 400 error that might indicate invalid player keys
        if e.response.status_code == 400:
            try:
                error_data = xmltodict.parse(e.response.content)
                error = error_data.get("error", {})
                error_desc = error.get("description", "") if isinstance(error, dict) else ""
                
                if "does not exist" in error_desc or "invalid" in error_desc.lower():
                    logger.warning(f"Batch request HTTP 400 with invalid player keys, trying individual requests: {error_desc}")
                    return _fetch_players_stats_individual(league_id, player_keys, stats_type, week)
            except Exception:
                pass
        
        raise


def _fetch_players_stats_individual(
    league_id: str,
    player_keys: list[str],
    stats_type: str | None = None,
    week: str | None = None
) -> list[dict]:
    """Fetch stats for players one at a time, skipping invalid player keys.
    
    Args:
        league_id: Yahoo league ID
        player_keys: List of Yahoo player keys
        stats_type: Optional stats type
        week: Optional week number
    
    Returns:
        List of enriched stats dictionaries (only for valid players)
    """
    id_to_name = get_league_stat_categories(league_id)
    enriched: list[dict] = []
    
    for player_key in player_keys:
        try:
            url = build_player_stats_url(league_id, player_key, stats_type, week)
            raw = fetch_yahoo(url)
            
            if isinstance(raw, dict) and raw.get("error"):
                logger.warning(f"Skipping invalid player_key: {player_key} - {raw.get('error', {}).get('description', 'Unknown error')}")
                continue
            
            parsed = parse_player_stats_response(raw)
            
            # Only add if we got valid stats
            if parsed.get("player_key"):
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
        except Exception as e:
            logger.warning(f"Skipping player_key {player_key} due to error: {e}")
            continue
    
    return enriched


def batch_fetch_player_stats(
    players: list["Player"],
    league_id: str,
    stats_type: str | None = None,
    week: str | None = None
) -> dict[str, dict]:
    """Fetch stats for multiple players in a single API call and cache in Player objects.
    
    Args:
        players: List of Player objects
        league_id: League ID for fetching stats
        stats_type: Optional stats type ("season" or "week")
        week: Optional week number (required if stats_type is "week")
    
    Returns:
        Dictionary mapping player_key to stats dict
    """
    from models import Player  # Import here to avoid circular dependency
    
    if not players:
        return {}
    
    # Filter players with valid player_keys
    valid_players = [p for p in players if p.player_key]
    if not valid_players:
        return {}
    
    player_keys = [p.player_key for p in valid_players]
    
    try:
        from utils import normalize_league_id
        import time
        
        normalized_league_id = normalize_league_id(league_id)
        enriched_stats = _fetch_players_stats(normalized_league_id, player_keys, stats_type, week)
        
        # Create a dictionary keyed by player_key and update player caches
        stats_dict = {}
        cache_key = f"{normalized_league_id}_{stats_type or 'season'}_{week or 'all'}"
        
        for stat_data in enriched_stats:
            player_key = stat_data.get("player_key")
            if player_key:
                # Update cache for matching player objects
                for player in valid_players:
                    if player.player_key == player_key:
                        player._stats_cache[cache_key] = {
                            "stats": stat_data,
                            "timestamp": time.time()
                        }
                stats_dict[player_key] = stat_data
        
        return stats_dict
        
    except Exception as e:
        logger.error(f"Error batch fetching player stats: {e}")
        return {}

