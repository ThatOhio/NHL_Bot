import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from nhl_api import fetch_next_game, search_player, get_player_details, get_standings, get_next_game_info, format_game_info
from image_generator import generate_player_card, generate_standings_image, generate_conference_image, generate_next_games_image

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
        games_data = []
        for team_name, team_abbr in TEAMS.items():
            game = await get_next_game_info(team_abbr)
            if game:
                home_abbr = game["homeTeam"]["abbrev"]
                away_abbr = game["awayTeam"]["abbrev"]
                is_home = (home_abbr == team_abbr)
                opponent_abbr = away_abbr if is_home else home_abbr
                
                full_info = format_game_info(game)
                # format_game_info returns "AWAY @ HOME Day @ Time"
                # We want just "Day @ Time"
                parts = full_info.split(" ")
                time_only = " ".join(parts[3:])
                
                broadcasts = game.get("tvBroadcasts", [])
                relevant_networks = []
                for b in broadcasts:
                    # Include National broadcasts or those matching our team's home/away status
                    if b.get("market") == "N" or (is_home and b.get("market") == "H") or (not is_home and b.get("market") == "A"):
                        network = b.get("network")
                        if network and network not in relevant_networks:
                            relevant_networks.append(network)
                
                broadcast_str = ", ".join(relevant_networks) if relevant_networks else None

                games_data.append({
                    "team_name": team_name,
                    "team_abbr": team_abbr,
                    "opponent_abbr": opponent_abbr,
                    "is_home": is_home,
                    "time_str": time_only,
                    "broadcasts": broadcast_str
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

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN not found in environment. Please check your .env file.")
