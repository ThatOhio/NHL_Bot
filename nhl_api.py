import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
ROSTER_CACHE = {"teams": None, "players": [], "last_updated": None}

async def fetch_next_game(team_abbr: str):
    # Using the week/now endpoint first as it's lighter
    url = f"https://api-web.nhle.com/v1/club-schedule/{team_abbr}/week/now"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                games = data.get("games", [])
                
                now = datetime.now(timezone.utc)
                
                next_game = None
                for game in games:
                    game_time = datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00"))
                    if game_time > now:
                        next_game = game
                        break
                
                if next_game:
                    return format_game_info(next_game)
                
                # If no upcoming games this week, we could fetch the season schedule
                # We try month/now if week/now failed to find an upcoming game
                month_url = f"https://api-web.nhle.com/v1/club-schedule/{team_abbr}/month/now"
                async with session.get(month_url, headers=headers) as m_response:
                    if m_response.status == 200:
                        m_data = await m_response.json()
                        m_games = m_data.get("games", [])
                        for game in m_games:
                            game_time = datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00"))
                            if game_time > now:
                                return format_game_info(game)
                                
        return "No upcoming games found."
    except Exception as e:
        return f"Error fetching game: {str(e)}"

def format_game_info(game):
    home_team = game["homeTeam"]["abbrev"]
    away_team = game["awayTeam"]["abbrev"]
    start_time_utc = game["startTimeUTC"]
    
    dt_utc = datetime.fromisoformat(start_time_utc.replace("Z", "+00:00"))
    dt_et = dt_utc.astimezone(EASTERN)
    
    # Get current time in Eastern for comparison
    now_et = datetime.now(EASTERN)
    
    delta = dt_et.date() - now_et.date()
    
    if delta.days == 0:
        # Today @ TIME
        time_str = dt_et.strftime("%-I:%M:%S %p")
        formatted_time = f"Today @ {time_str}"
    elif 0 < delta.days < 7:
        # WEEKDAY @ TIME
        weekday = dt_et.strftime("%A")
        time_str = dt_et.strftime("%-I:%M:%S %p")
        formatted_time = f"{weekday} @ {time_str}"
    else:
        # EEEE, MMMM d, yyyy h:mm:ss a z
        formatted_time = dt_et.strftime("%A, %B %-d, %Y %-I:%M:%S %p %Z")
    
    return f"{away_team} @ {home_team} {formatted_time}"

async def search_player(name: str):
    """
    Searches for a player by name. Since direct search is unreliable,
    we fetch all team rosters and search through them.
    """
    now = datetime.now(timezone.utc)
    
    # Refresh cache if empty or older than 1 day
    if not ROSTER_CACHE["players"] or not ROSTER_CACHE["last_updated"] or (now - ROSTER_CACHE["last_updated"]) > timedelta(days=1):
        await update_roster_cache()
    
    matches = []
    search_name = name.lower()
    for player in ROSTER_CACHE["players"]:
        full_name = f"{player['firstName']} {player['lastName']}".lower()
        if search_name in full_name:
            matches.append(player)
            
    return matches

async def update_roster_cache():
    # Fetches all team rosters and updates the local cache.

    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession() as session:
        # Get all teams
        async with session.get("https://api-web.nhle.com/v1/standings/now", headers=headers) as response:
            if response.status != 200:
                return
            data = await response.json()
            teams = [s["teamAbbrev"]["default"] for s in data["standings"]]
        
        all_players = []
        tasks = []
        for team in teams:
            tasks.append(fetch_team_roster(session, team, headers))
        
        results = await asyncio.gather(*tasks)
        for roster in results:
            if roster:
                all_players.extend(roster)
        
        ROSTER_CACHE["players"] = all_players
        ROSTER_CACHE["last_updated"] = datetime.now(timezone.utc)

async def fetch_team_roster(session, team_abbr, headers):
    url = f"https://api-web.nhle.com/v1/roster/{team_abbr}/current"
    async with session.get(url, headers=headers) as response:
        if response.status != 200:
            return None
        data = await response.json()
        players = []
        for pos in ["forwards", "defensemen", "goalies"]:
            for p in data.get(pos, []):
                players.append({
                    "id": p["id"],
                    "firstName": p["firstName"]["default"],
                    "lastName": p["lastName"]["default"],
                    "teamAbbrev": team_abbr,
                    "position": p["positionCode"]
                })
        return players

async def get_player_details(player_id: int):
    url = f"https://api-web.nhle.com/v1/player/{player_id}/landing"
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                return None
            return await response.json()

async def get_standings():
    url = "https://api-web.nhle.com/v1/standings/now"
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                return None
            return await response.json()
