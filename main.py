import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from nhl_api import fetch_next_game, search_player, get_player_details, get_standings
from image_generator import generate_player_card, generate_standings_image, generate_conference_image

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

@bot.command(name='nextgames', help='Shows the next game for the Sabres, Kraken, and Stars.')
async def next_games(ctx):
    response = "**Upcoming NHL Games:**\n"
    
    async with ctx.typing():
        for team_name, team_abbr in TEAMS.items():
            game_info = await fetch_next_game(team_abbr)
            response += f"• **{team_name}**: {game_info}\n"
    
    await ctx.send(response)

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
