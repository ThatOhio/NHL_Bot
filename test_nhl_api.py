import asyncio
from nhl_api import fetch_next_game, search_player, get_player_details, is_on_espn_plus, get_espn_scoreboard

async def test_espn_plus_logic():
    print("\n--- Testing ESPN+ Logic ---")
    
    # Case 1: Regional US game (Heuristic fallback)
    game_reg = {"homeTeam": {"abbrev": "BUF"}, "awayTeam": {"abbrev": "MTL"}, "tvBroadcasts": [{"network": "MSG-B", "market": "H"}]}
    print(f"Regional US game on ESPN+ (heuristic): {is_on_espn_plus(game_reg)}") # True
    
    # Case 2: ESPN National (Heuristic fallback)
    game_espn = {"homeTeam": {"abbrev": "PIT"}, "awayTeam": {"abbrev": "PHI"}, "tvBroadcasts": [{"network": "ESPN", "market": "N"}]}
    print(f"ESPN National on ESPN+ (heuristic): {is_on_espn_plus(game_espn)}") # True
    
    # Case 3: TNT Exclusive (Heuristic fallback)
    game_tnt = {"homeTeam": {"abbrev": "BUF"}, "awayTeam": {"abbrev": "CAR"}, "tvBroadcasts": [{"network": "TNT", "market": "N"}]}
    print(f"TNT Exclusive on ESPN+ (heuristic): {is_on_espn_plus(game_tnt)}") # False
    
    # Case 4: ESPN API Match - ESPN+ listed
    scoreboard_data = {
        "events": [{
            "competitions": [{
                "competitors": [{"team": {"abbreviation": "BUF"}}, {"team": {"abbreviation": "MTL"}}],
                "broadcasts": [{"names": ["ESPN+", "MSGB"]}]
            }]
        }]
    }
    print(f"ESPN API Match (ESPN+ present): {is_on_espn_plus(game_reg, scoreboard_data)}") # True
    
    # Case 5: ESPN API Match - ESPN+ NOT listed (e.g. TNT game)
    scoreboard_tnt = {
        "events": [{
            "competitions": [{
                "competitors": [{"team": {"abbreviation": "BUF"}}, {"team": {"abbreviation": "CAR"}}],
                "broadcasts": [{"names": ["TNT", "HBO Max"]}]
            }]
        }]
    }
    print(f"ESPN API Match (ESPN+ absent): {is_on_espn_plus(game_tnt, scoreboard_tnt)}") # False

async def test_espn_api_fetch():
    print("\n--- Testing ESPN API Fetch ---")
    date_str = "20260115"
    data = await get_espn_scoreboard(date_str)
    if data:
        print(f"Successfully fetched ESPN scoreboard for {date_str}")
        events = data.get("events", [])
        print(f"Found {len(events)} events.")
    else:
        print("Failed to fetch ESPN scoreboard.")

async def test_api():
    await test_espn_plus_logic()
    await test_espn_api_fetch()
    
    teams = ["BUF", "SEA", "DAL"]
    print("--- Testing Next Games ---")
    for team in teams:
        result = await fetch_next_game(team)
        print(f"Result for {team}: {result}")
    
    print("\n--- Testing Player Search ---")
    player_name = "McDavid"
    matches = await search_player(player_name)
    if matches:
        p = matches[0]
        print(f"Found: {p['firstName']} {p['lastName']} ({p['teamAbbrev']})")
        details = await get_player_details(p['id'])
        if details:
            print(f"Successfully fetched details for {p['lastName']}")
    else:
        print(f"No matches for {player_name}")

if __name__ == "__main__":
    asyncio.run(test_api())
