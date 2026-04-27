import os
import discord
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from discord.ext import commands
from dotenv import load_dotenv
from nhl_api import fetch_next_game, search_player, get_player_details, get_standings, get_next_game_info, format_game_info, is_on_espn_plus, get_espn_scoreboard, get_olympic_schedule
from image_generator import generate_player_card, generate_standings_image, generate_conference_image, generate_next_games_image, generate_olympic_schedule_image

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

TEAMS = {
    "Buffalo Sabres": "BUF",
    "Seattle Kraken": "SEA",
    "Dallas Stars": "DAL"
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

@bot.command(name='nextgames', aliases=['next'], help='Shows the next game for the Sabres, Kraken, and Stars.')
async def next_games(ctx):
    async with ctx.typing():
        # First, fetch game info for all teams to identify dates
        team_games = {}
        all_dates = []
        for team_name, team_abbr in TEAMS.items():
            game = await get_next_game_info(team_abbr)
            if game:
                team_games[team_abbr] = (team_name, game)
                all_dates.append(game["gameDate"].replace("-", ""))
        
        if not team_games:
            await ctx.send("No upcoming games found for the tracked teams.")
            return

        # Fetch ESPN scoreboard for the relevant date range
        scoreboard_data = None
        if all_dates:
            min_date = min(all_dates)
            max_date = max(all_dates)
            date_range = min_date if min_date == max_date else f"{min_date}-{max_date}"
            scoreboard_data = await get_espn_scoreboard(date_range)

        games_data = []
        for team_abbr, (team_name, game) in team_games.items():
            if game.get("isTBD"):
                # Handle TBD games (usually between playoff rounds)
                status = game.get("seriesStatus", {})
                series_title = status.get("seriesTitle", "Playoffs")
                top_wins = status.get("topSeedWins", 0)
                bot_wins = status.get("bottomSeedWins", 0)
                
                top_abbr = game.get("topSeed", {}).get("abbrev")
                bot_abbr = game.get("bottomSeed", {}).get("abbrev")
                is_top = (team_abbr == top_abbr)
                opponent_abbr = bot_abbr if is_top else top_abbr
                if not opponent_abbr:
                    opponent_abbr = "TBD"
                
                score_str = f"{top_wins}-{bot_wins}" if is_top else f"{bot_wins}-{top_wins}"
                if top_wins == bot_wins:
                    series_summary = f"Series Tied {top_wins}-{bot_wins}"
                elif (is_top and top_wins > bot_wins) or (not is_top and bot_wins > top_wins):
                    series_summary = f"Leading {score_str}"
                else:
                    series_summary = f"Trailing {score_str}"

                games_data.append({
                    "team_name": team_name,
                    "team_abbr": team_abbr,
                    "opponent_abbr": opponent_abbr,
                    "is_home": False, # Doesn't matter for TBD
                    "time_str": "Next Game TBD",
                    "broadcasts": None,
                    "playoff_info": f"{series_title}\n{series_summary}"
                })
                continue

            home_abbr = game["homeTeam"]["abbrev"]
            away_abbr = game["awayTeam"]["abbrev"]
            is_home = (home_abbr == team_abbr)
            opponent_abbr = away_abbr if is_home else home_abbr
            
            full_info = format_game_info(game)
            # format_game_info returns "AWAY @ HOME Day @ Time [Playoff Info]"
            # We want just "Day @ Time"
            parts = full_info.split(" ")
            time_only = " ".join(parts[3:])
            
            # If there's playoff info in brackets at the end, extract it
            playoff_info = None
            if "[" in time_only and "]" in time_only:
                start = time_only.find("[")
                playoff_info = time_only[start+1:-1].replace(" - ", "\n")
                time_only = time_only[:start].strip()

            broadcasts = game.get("tvBroadcasts", [])
            relevant_networks = []
            for b in broadcasts:
                # Include National broadcasts or those matching our team's home/away status
                if b.get("market") == "N" or (is_home and b.get("market") == "H") or (not is_home and b.get("market") == "A"):
                    network = b.get("network")
                    if network and network not in relevant_networks:
                        relevant_networks.append(network)
            
            if is_on_espn_plus(game, scoreboard_data) and "ESPN+" not in relevant_networks:
                relevant_networks.append("ESPN+")
            
            broadcast_str = ", ".join(relevant_networks) if relevant_networks else None

            games_data.append({
                "team_name": team_name,
                "team_abbr": team_abbr,
                "opponent_abbr": opponent_abbr,
                "is_home": is_home,
                "time_str": time_only,
                "broadcasts": broadcast_str,
                "playoff_info": playoff_info
            })
        
        if not games_data:
            await ctx.send("No upcoming games found for the tracked teams.")
            return

        try:
            image_buffer = await generate_next_games_image(games_data)
            file = discord.File(fp=image_buffer, filename="next_games.png")
            await ctx.send(file=file)
        except Exception as e:
            await ctx.send(f"Error generating next games image: {str(e)}")

@bot.command(name='player', help='Shows a player card for a given player name.')
async def player_card(ctx, *, name: str):
    async with ctx.typing():
        matches = await search_player(name)
        
        if not matches:
            await ctx.send(f"No players found matching '{name}'.")
            return
        
        # Determine the best match
        player = None
        if len(matches) == 1:
            player = matches[0]
        else:
            # Check for exact match
            exact_match = next((p for p in matches if f"{p['firstName']} {p['lastName']}".lower() == name.lower()), None)
            if exact_match:
                player = exact_match
            elif len(matches) > 10:
                await ctx.send(f"Found {len(matches)} matches for '{name}'. Please be more specific.")
                return
            else:
                # Pick the first one and mention other possibilities
                player = matches[0]
                others = ", ".join([f"{p['firstName']} {p['lastName']}" for p in matches[1:4]])
                if len(matches) > 4:
                    others += "..."
                await ctx.send(f"Multiple matches found. Showing {player['firstName']} {player['lastName']}. (Others: {others})")

        details = await get_player_details(player['id'])
        if not details:
            await ctx.send(f"Could not fetch details for {player['firstName']} {player['lastName']}.")
            return
            
        try:
            card_buffer = await generate_player_card(details)
            file = discord.File(fp=card_buffer, filename=f"{player['lastName']}_card.png")
            await ctx.send(file=file)
        except Exception as e:
            await ctx.send(f"Error generating player card: {str(e)}")

@bot.command(name='standings', help='Shows the NHL playoff picture (division leaders and wildcards).')
async def standings_command(ctx):
    async with ctx.typing():
        data = await get_standings()
        if not data:
            await ctx.send("Could not fetch standings data.")
            return
            
        try:
            image_buffer = await generate_standings_image(data)
            file = discord.File(fp=image_buffer, filename="nhl_standings.png")
            await ctx.send(file=file)
        except Exception as e:
            await ctx.send(f"Error generating standings image: {str(e)}")

@bot.command(name='conference', help='Shows the current NHL standings for both conferences.')
async def conference_command(ctx):
    async with ctx.typing():
        data = await get_standings()
        if not data:
            await ctx.send("Could not fetch standings data.")
            return
            
        try:
            image_buffer = await generate_conference_image(data)
            file = discord.File(fp=image_buffer, filename="nhl_league_standings.png")
            await ctx.send(file=file)
        except Exception as e:
            await ctx.send(f"Error generating conference image: {str(e)}")

@bot.command(name='o-next', help='Shows the next Olympic hockey games.')
async def olympic_next(ctx):
    async with ctx.typing():
        # Determine "today" and "tomorrow" based on America/New_York timezone
        now_et = datetime.now(ZoneInfo("America/New_York"))
        today_et = now_et.date()
        tomorrow_et = today_et + timedelta(days=1)
        
        all_games = []
        for date in [today_et, tomorrow_et]:
            games = await get_olympic_schedule(date)
            if not games:
                all_games.append({"no_games": True, "date": date})
            else:
                all_games.extend(games)
        
        try:
            image_buffer = await generate_olympic_schedule_image(all_games, today_et)
            file = discord.File(fp=image_buffer, filename="olympic_schedule.png")
            await ctx.send(file=file)
        except Exception as e:
            await ctx.send(f"Error generating Olympic schedule image: {str(e)}")

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN not found in environment. Please check your .env file.")
