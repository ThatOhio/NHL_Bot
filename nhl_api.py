import aiohttp
import asyncio
import pycountry
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
ROSTER_CACHE = {"teams": None, "players": [], "last_updated": None}

async def fetch_next_game(team_abbr: str):
    game = await get_next_game_info(team_abbr)
    if game:
        return format_game_info(game)
    return "No upcoming games found."

async def get_next_game_info(team_abbr: str):
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
                
                for game in games:
                    game_time = datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00"))
                    if game_time > now:
                        return game
                
                # If no upcoming games this week, try month
                month_url = f"https://api-web.nhle.com/v1/club-schedule/{team_abbr}/month/now"
                async with session.get(month_url, headers=headers) as m_response:
                    if m_response.status == 200:
                        m_data = await m_response.json()
                        m_games = m_data.get("games", [])
                        for game in m_games:
                            game_time = datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00"))
                            if game_time > now:
                                return game
                                
        return None
    except Exception:
        return None

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
        time_str = dt_et.strftime("%-I:%M %p")
        formatted_time = f"Today @ {time_str}"
    elif 0 < delta.days < 7:
        # WEEKDAY @ TIME
        weekday = dt_et.strftime("%a")
        time_str = dt_et.strftime("%-I:%M %p")
        formatted_time = f"{weekday} @ {time_str}"
    else:
        # SHORT_DATE @ TIME
        date_str = dt_et.strftime("%a, %b %-d")
        time_str = dt_et.strftime("%-I:%M %p")
        formatted_time = f"{date_str} @ {time_str}"
    
    return f"{away_team} @ {home_team} {formatted_time}"

def is_on_espn_plus(game, scoreboard_data=None):
    # First, try to use ESPN API data if provided
    if scoreboard_data:
        home_abbr = game["homeTeam"]["abbrev"]
        away_abbr = game["awayTeam"]["abbrev"]
        
        events = scoreboard_data.get("events", [])
        for event in events:
            competitions = event.get("competitions", [])
            for comp in competitions:
                competitors = comp.get("competitors", [])
                teams = [c.get("team", {}).get("abbreviation") for c in competitors]
                if home_abbr in teams and away_abbr in teams:
                    broadcasts = comp.get("broadcasts", [])
                    for b in broadcasts:
                        if "ESPN+" in b.get("names", []):
                            return True
                    # If we found the game but ESPN+ is not listed
                    return False

    broadcasts = game.get("tvBroadcasts", [])
    if not broadcasts:
        return False

    # These networks are NOT on ESPN+
    excluded_networks = ["TNT", "NHLN", "truTV", "HBO MAX"]
    for b in broadcasts:
        if b.get("network") in excluded_networks:
            return False

    return True

async def get_espn_scoreboard(date_str: str):
    """
    Fetches the ESPN scoreboard for a given date or date range.
    date_str should be in YYYYMMDD or YYYYMMDD-YYYYMMDD format.
    """
    url = f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={date_str}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
    except Exception:
        pass
    return None

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

BASE_OLYMPIC_LEAGUES = {
    "men": "https://sports.core.api.espn.com/v2/sports/hockey/leagues/olympics-mens-ice-hockey",
    "women": "https://sports.core.api.espn.com/v2/sports/hockey/leagues/olympics-womens-ice-hockey",
}

IOC_TO_ALPHA2 = {
    "AFG": "AF", "ALB": "AL", "ALG": "DZ", "AND": "AD", "ANG": "AO", "ANT": "AG", "ARG": "AR", "ARM": "AM", "ARU": "AW", "ASA": "AS",
    "AUS": "AU", "AUT": "AT", "AZE": "AZ", "BAH": "BS", "BAN": "BD", "BAR": "BB", "BDI": "BI", "BEL": "BE", "BEN": "BJ", "BER": "BM",
    "BHU": "BT", "BIH": "BA", "BIZ": "BZ", "BLR": "BY", "BOL": "BO", "BOT": "BW", "BRA": "BR", "BRN": "BR", "BRU": "BN", "BUL": "BG",
    "BUR": "BF", "CAF": "CF", "CAM": "KH", "CAN": "CA", "CAY": "KY", "CGO": "CG", "CHA": "TD", "CHI": "CL", "CHN": "CN", "CIV": "CI",
    "CMR": "CM", "COD": "CD", "COK": "CK", "COL": "CO", "COM": "KM", "CPV": "CV", "CRC": "CR", "CRO": "HR", "CUB": "CU", "CYP": "CY",
    "CZE": "CZ", "DEN": "DK", "DJI": "DJ", "DMA": "DM", "DOM": "DO", "ECU": "EC", "EGY": "EG", "ERI": "ER", "ESA": "SV", "ESP": "ES",
    "EST": "EE", "ETH": "ET", "FIJ": "FJ", "FIN": "FI", "FRA": "FR", "FSM": "FM", "GAB": "GA", "GAM": "GM", "GBR": "GB", "GBS": "GW",
    "GEO": "GE", "GEQ": "GQ", "GER": "DE", "GHA": "GH", "GRE": "GR", "GRN": "GD", "GUA": "GT", "GUI": "GN", "GUM": "GU", "GUY": "GY",
    "HAI": "HT", "HKG": "HK", "HON": "HN", "HUN": "HU", "INA": "ID", "IND": "IN", "IRI": "IR", "IRL": "IE", "IRQ": "IQ", "ISL": "IS",
    "ISR": "IL", "ISV": "VI", "ITA": "IT", "IVB": "VG", "JAM": "JM", "JOR": "JO", "JPN": "JP", "KAZ": "KZ", "KEN": "KE", "KGZ": "KG",
    "KIR": "KI", "KOR": "KR", "KSA": "SA", "KUW": "KW", "LAO": "LA", "LAT": "LV", "LBA": "LY", "LBN": "LB", "LBR": "LR", "LCA": "LC",
    "LES": "LS", "LIE": "LI", "LTU": "LT", "LUX": "LU", "MAD": "MG", "MAR": "MA", "MAS": "MY", "MAW": "MW", "MEX": "MX", "MGL": "MN",
    "MHL": "MH", "MKD": "MK", "MLI": "ML", "MLT": "MT", "MNE": "ME", "MON": "MC", "MOZ": "MZ", "MRI": "MU", "MTN": "MR", "MYA": "MM",
    "NAM": "NA", "NCA": "NI", "NED": "NL", "NEP": "NP", "NGR": "NG", "NIG": "NE", "NOR": "NO", "NRU": "NR", "NZL": "NZ", "OMA": "OM",
    "PAK": "PK", "PAN": "PA", "PAR": "PY", "PER": "PE", "PHI": "PH", "PLE": "PS", "PLW": "PW", "PNG": "PG", "POL": "PL", "POR": "PT",
    "PRK": "KP", "PUR": "PR", "QAT": "QA", "ROU": "RO", "RSA": "ZA", "RUS": "RU", "RWA": "RW", "SAM": "WS", "SEN": "SN", "SEY": "SC",
    "SGP": "SG", "SKN": "KN", "SLE": "SL", "SLO": "SI", "SMR": "SM", "SOL": "SB", "SOM": "SO", "SRB": "RS", "SRI": "LK", "SSD": "SS",
    "STP": "ST", "SUD": "SD", "SUI": "CH", "SUR": "SR", "SVK": "SK", "SWE": "SE", "SWZ": "SZ", "SYR": "SY", "TAN": "TZ", "TGA": "TO",
    "THA": "TH", "TJK": "TJ", "TKM": "TM", "TLS": "TL", "TOG": "TG", "TPE": "TW", "TTO": "TT", "TUN": "TN", "TUR": "TR", "TUV": "TV",
    "UAE": "AE", "UGA": "UG", "UKR": "UA", "URU": "UY", "USA": "US", "UZB": "UZ", "VAN": "VU", "VEN": "VE", "VIE": "VN", "VIN": "VC",
    "YEM": "YE", "ZAM": "ZM", "ZIM": "ZW",
    "ROC": "RU", "OAR": "RU"
}

async def get_olympic_team_info(session, team_ref: str):
    try:
        async with session.get(team_ref, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            if resp.status != 200:
                return {"name": "TBD", "abbreviation": "TBD", "alpha2": None}
            team_data = await resp.json()
            name = team_data.get("displayName") or team_data.get("name")
            abbr = team_data.get("abbreviation") or team_data.get("shortDisplayName")
            
            alpha2 = None
            if abbr and abbr != "TBD":
                if abbr in IOC_TO_ALPHA2:
                    alpha2 = IOC_TO_ALPHA2[abbr]
                else:
                    try:
                        country = pycountry.countries.get(alpha_3=abbr)
                        if country:
                            alpha2 = country.alpha_2
                    except:
                        pass
            
            return {"name": name, "abbreviation": abbr, "alpha2": alpha2}
    except Exception:
        return {"name": "TBD", "abbreviation": "TBD", "alpha2": None}

async def get_olympic_schedule(date_obj):
    date_str = date_obj.strftime("%Y%m%d")
    headers = {"User-Agent": "Mozilla/5.0"}
    all_events = []
    
    async with aiohttp.ClientSession() as session:
        for league_type, base_url in BASE_OLYMPIC_LEAGUES.items():
            events_url = f"{base_url}/events?dates={date_str}&lang=en"
            async with session.get(events_url, headers=headers) as resp:
                if resp.status != 200:
                    continue
                events_data = await resp.json()
                
                items = events_data.get("items", [])
                for item in items:
                    async with session.get(item["$ref"], headers=headers) as e_resp:
                        if e_resp.status != 200:
                            continue
                        event_data = await e_resp.json()
                        event_date_utc = event_data.get("date")
                        
                        competitions_refs = event_data.get("competitions", [])
                        for comp_ref in competitions_refs:
                            async with session.get(comp_ref["$ref"], headers=headers) as c_resp:
                                if c_resp.status != 200:
                                    continue
                                comp_data = await c_resp.json()
                                round_desc = comp_data.get("description", "")
                                comp_date = comp_data.get("date", event_date_utc)
                                competitors = comp_data.get("competitors", [])
                                
                                if not competitors:
                                    continue
                                
                                # ESPN Core API usually lists home/away in competitors
                                home_comp = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                                away_comp = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1] if len(competitors) > 1 else competitors[0])
                                
                                home_team = await get_olympic_team_info(session, home_comp.get("team", {}).get("$ref")) if home_comp.get("team") else {"name": "TBD", "abbreviation": "TBD", "alpha2": None}
                                away_team = await get_olympic_team_info(session, away_comp.get("team", {}).get("$ref")) if away_comp.get("team") else {"name": "TBD", "abbreviation": "TBD", "alpha2": None}
                                
                                all_events.append({
                                    "league": league_type,
                                    "date": date_obj,
                                    "time_utc": comp_date,
                                    "home": home_team,
                                    "away": away_team,
                                    "round": round_desc
                                })
    return all_events
