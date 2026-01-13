import asyncio
from nhl_api import fetch_next_game, search_player, get_player_details

async def test_api():
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
