"""Player model for Yahoo Fantasy API."""
import time
from typing import Optional

from config import CACHE_TTL
from utils import normalize_league_id
from yahoo_api import (
    fetch_yahoo, build_player_stats_url, parse_player_stats_response,
    get_league_stat_categories
)


class Player:
    """Represents a fantasy football player from Yahoo Fantasy API."""
    
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
        **kwargs
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
        
        # Cache for player stats (cache_key: {"stats": {...}, "timestamp": float})
        self._stats_cache: dict[str, dict] = {}
        self._cache_ttl = CACHE_TTL
        
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
        name = name_info.get("full") if isinstance(name_info, dict) else name_info
        
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
    
    def to_dict(
        self,
        include_stats: bool = False,
        league_id: str | None = None,
        stats_type: str | None = None,
        week: str | None = None
    ) -> dict:
        """Convert Player instance to dictionary for JSON serialization.
        
        Args:
            include_stats: If True, include player stats in the output (requires league_id)
            league_id: League ID needed when include_stats is True
            stats_type: Optional stats type ("season" or "week") when including stats
            week: Optional week number for week-specific stats
        
        Returns:
            Dictionary representation of the player, optionally with stats
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
        
        # Include stats if requested and league_id is provided
        if include_stats and league_id:
            try:
                # Use week if provided, or determine stats_type from week
                if week:
                    stats_type = "week"
                stats = self.get_stats(league_id, stats_type=stats_type, week=week)
                if stats:
                    result["stats"] = stats.get("stats", [])
                    result["stats_type"] = stats.get("stats_type")
                    if stats.get("week"):
                        result["week"] = stats.get("week")
            except Exception as e:
                print(f"⚠️ Error including stats for player {self.player_key}: {e}")
        
        return result
    
    def get_stats(
        self,
        league_id: str,
        stats_type: str | None = None,
        week: str | None = None,
        force_refresh: bool = False
    ) -> dict | None:
        """Fetch player stats for a given league with caching.
        
        Args:
            league_id: Yahoo league ID (will be normalized)
            stats_type: Optional; "season" or "week"
            week: Optional; required if stats_type is "week"
            force_refresh: If True, bypass cache and fetch fresh data
        
        Returns:
            Dictionary with enriched stats including stat names, or None if error
        """
        if not self.player_key:
            print("⚠️ Player key is required to fetch stats")
            return None
        
        normalized_league_id = normalize_league_id(league_id)
        cache_key = f"{normalized_league_id}_{stats_type or 'season'}_{week or 'all'}"
        
        # Check cache if not forcing refresh
        if not force_refresh and cache_key in self._stats_cache:
            cached_data = self._stats_cache[cache_key]
            cache_age = time.time() - cached_data.get("timestamp", 0)
            
            if cache_age < self._cache_ttl:
                return cached_data.get("stats")
        
        # Cache miss or expired - fetch fresh data
        try:
            url = build_player_stats_url(normalized_league_id, self.player_key, stats_type, week)
            data = fetch_yahoo(url)
            
            if isinstance(data, dict) and data.get("error"):
                print(f"⚠️ Error fetching stats: {data.get('error')}")
                return None
            
            parsed_stats = parse_player_stats_response(data)
            stat_categories = get_league_stat_categories(normalized_league_id)
            
            # Enrich stats with stat names
            enriched_stats = []
            for stat in parsed_stats.get("stats", []):
                stat_id = stat.get("stat_id")
                enriched_stats.append({
                    "stat_id": stat_id,
                    "stat_name": stat_categories.get(stat_id),
                    "value": stat.get("value"),
                })
            
            result = {
                "league_id": normalized_league_id,
                "player_key": self.player_key,
                "name": parsed_stats.get("name") or self.name,
                "team": parsed_stats.get("team") or self.team,
                "positions": parsed_stats.get("positions", []),
                "stats_type": parsed_stats.get("stats_type") or stats_type,
                "week": parsed_stats.get("week") or week,
                "stats": enriched_stats,
            }
            
            # Store in cache with timestamp
            self._stats_cache[cache_key] = {
                "stats": result,
                "timestamp": time.time()
            }
            
            return result
            
        except Exception as e:
            print(f"⚠️ Error fetching player stats for {self.player_key}: {e}")
            return None
    
    def clear_stats_cache(self, cache_key: str | None = None) -> None:
        """Clear stats cache.
        
        Args:
            cache_key: Optional specific cache key to clear. If None, clears all.
        """
        if cache_key:
            self._stats_cache.pop(cache_key, None)
        else:
            self._stats_cache.clear()
    
    def __repr__(self) -> str:
        """String representation of the Player."""
        return f"Player(key={self.player_key}, name={self.name}, position={self.position}, team={self.team})"

