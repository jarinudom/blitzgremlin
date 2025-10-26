import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from yfpy.query import YahooFantasySportsQuery

# ---- ENV (no dotenv) ---------------------------------------------------------
CLIENT_ID = os.environ["YAHOO_CLIENT_ID"]
CLIENT_SECRET = os.environ["YAHOO_CLIENT_SECRET"]
REDIRECT_URI = os.environ["YAHOO_REDIRECT_URI"]
GAME_CODE = os.environ.get("YAHOO_GAME_CODE", "nfl")
# Can be numeric ("12345"), a full key ("449.l.12345"), or absent (will resolve)
LEAGUE_ENV = os.environ.get("YAHOO_LEAGUE_ID", "").strip()
TOKEN_PATH = os.environ.get("YAHOO_TOKEN_DIR", ".yahoo_oauth")  # store tokens on disk (A1)

# ---- Singleton YFPY client ---------------------------------------------------
_yq = YahooFantasySportsQuery(
    consumer_key=CLIENT_ID,
    consumer_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    game_code=GAME_CODE,
    league_id=LEAGUE_ENV if LEAGUE_ENV else None,
    token_path=TOKEN_PATH,
)

# ---- Tiny in-process cache ---------------------------------------------------
_CACHE: Dict[str, Any] = {}
def _cache_get(k: str):
    v = _CACHE.get(k)
    if not v:
        return None
    data, exp = v
    if exp < time.time():
        _CACHE.pop(k, None)
        return None
    return data

def _cache_set(k: str, data: Any, ttl: int = 60):
    _CACHE[k] = (data, time.time() + ttl)

# ---- Auth helpers ------------------------------------------------------------
def get_auth_url() -> str:
    return _yq.oauth_helper.get_authorization_url()

# ---- League resolution (same behavior as your app) ---------------------------
def _looks_like_full_key(v: str) -> bool:
    return ".l." in v and v.split(".l.")[-1].isdigit()

def ensure_league_key() -> str:
    # already computed?
    if getattr(_yq, "league_key", None):
        return _yq.league_key
    # full key in env?
    if LEAGUE_ENV and _looks_like_full_key(LEAGUE_ENV):
        _yq.league_key = LEAGUE_ENV
        return _yq.league_key
    # numeric or blank: let YFPY resolve
    _yq.get_league_key()
    return _yq.league_key

# ---- Common lookups ----------------------------------------------------------
def current_week() -> int:
    weeks = _yq.get_game_weeks_by_game_id(_yq.current_game_id)
    today = datetime.utcnow().date()
    for w in weeks:
        try:
            if datetime.strptime(w["end"], "%Y-%m-%d").date() >= today:
                return int(w["week"])
        except Exception:
            continue
    return int(weeks[-1]["week"]) if weeks else 1

def league_metadata():
    key = ensure_league_key()
    ck = f"league_meta:{key}"
    if (hit := _cache_get(ck)) is not None:
        return hit
    data = _yq.get_league_metadata()
    _cache_set(ck, data, ttl=600)
    return data

def team_roster_with_stats(team_id: str, week: Optional[int] = None) -> List[Dict[str, Any]]:
    ensure_league_key()
    wk = week or current_week()
    roster = _yq.get_team_roster_player_info_by_week(team_id=team_id, week=wk)
    enriched: List[Dict[str, Any]] = []
    for p in roster:
        pkey = p["player_key"]
        try:
            stats = _yq.get_player_stats_by_week(player_key=pkey, week=wk)
        except Exception:
            stats = None
        try:
            ownership = _yq.get_player_ownership(player_key=pkey)
        except Exception:
            ownership = None
        enriched.append({**p, "stats": stats, "ownership": ownership})
    return enriched

def league_free_agents(limit: int = 100, position: Optional[str] = None) -> List[Dict[str, Any]]:
    ensure_league_key()
    players = _yq.get_league_players()
    results: List[Dict[str, Any]] = []
    for pl in players:
        try:
            own = _yq.get_player_ownership(player_key=pl["player_key"])
            otype = (own or {}).get("ownership", {}).get("ownership_type", "")
            percent = float((own or {}).get("ownership", {}).get("percent_owned", "0") or 0)
            is_fa = otype.lower() in ("free agent", "free agents") or percent == 0.0
            if not is_fa:
                continue
            if position:
                elig = [ep["position"] for ep in pl.get("eligible_positions", [])]
                if position.upper() not in elig:
                    continue
            results.append({**pl, "ownership": own})
            if len(results) >= limit:
                break
        except Exception:
            continue
    return results

# expose underlying client for advanced calls, if needed
yq = _yq
