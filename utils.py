"""Utility functions for BlitzGremlin."""
from typing import Optional


def normalize_league_id(league_id: str) -> str:
    """Ensure league_id is in full Yahoo key format if only digits are provided.
    
    Args:
        league_id: League ID in either format (e.g., "12345" or "461.l.12345")
    
    Returns:
        League ID in full format (e.g., "461.l.12345")
    """
    if league_id.isdigit():
        return f"461.l.{league_id}"
    return league_id


def extract_league_id_from_team_key(team_key: str) -> Optional[str]:
    """Extract league_id from team_key.
    
    Args:
        team_key: Yahoo team key (e.g., "461.l.XXXX.t.Y")
    
    Returns:
        League ID (e.g., "461.l.XXXX") or None if parsing fails
    """
    try:
        if "." in team_key:
            parts = team_key.split(".")
            if len(parts) >= 3:
                return ".".join(parts[:3])
    except Exception:
        pass
    return None

