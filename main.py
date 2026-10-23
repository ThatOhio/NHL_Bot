import os
import re
import discord
from datetime import datetime, timedelta, timezone, date, time
from zoneinfo import ZoneInfo
from discord.ext import commands, tasks
from dotenv import load_dotenv
from nhl_api import fetch_next_game, search_player, get_player_details, get_standings, get_next_game_info, format_game_info, is_on_espn_plus, get_espn_scoreboard, get_olympic_schedule, get_league_schedule
from image_generator import generate_player_card, generate_standings_image, generate_conference_image, generate_next_games_image, generate_olympic_schedule_image
from daily import build_daily_report
from state import load_state, save_state

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DAILY_CHANNEL_ID = os.getenv('DAILY_CHANNEL_ID')
EASTERN = ZoneInfo("America/New_York")
DAILY_POST_TIME = time(hour=9, minute=0, tzinfo=EASTERN)
# Post on startup if the bot was down at 9 AM, until this hour
DAILY_CATCH_UP_UNTIL_HOUR = 12

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
    if not daily_post_loop.is_running():
        daily_post_loop.start()
        await catch_up_daily_post()

def parse_window(text):
    match = re.fullmatch(r"(\d+)\s*([hd])", text.strip().lower())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    window = timedelta(hours=amount) if unit == "h" else timedelta(days=amount)
    if window <= timedelta(0):
        return None
    return min(window, timedelta(days=7))

def national_networks(game, scoreboard_data):
    networks = []
    for b in game.get("tvBroadcasts", []):
        if b.get("market") == "N" and b.get("countryCode") == "US" and b.get("network") not in networks:
            networks.append(b["network"])
    if is_on_espn_plus(game, scoreboard_data) and "ESPN+" not in networks:
        networks.append("ESPN+")
    return networks

async def send_league_schedule(ctx, window, window_label):
    now = datetime.now(timezone.utc)
    end = now + window
    today_et = now.astimezone(EASTERN).date()

    # The schedule endpoint returns 7 days; a 7d window can reach into an 8th
    days = await get_league_schedule(today_et.isoformat())
    if days and days[-1]["date"] < end.astimezone(EASTERN).date().isoformat():
        days += await get_league_schedule((today_et + timedelta(days=7)).isoformat())

    games = []
    for day in days:
        for g in day.get("games", []):
            start = datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00"))
            if now < start <= end:
                games.append((start, g))
    games.sort(key=lambda pair: pair[0])

    if not games:
        await ctx.send(f"No NHL games in the next {window_label}.")
        return

    dates = [s.astimezone(EASTERN).strftime("%Y%m%d") for s, _ in games]
    date_range = dates[0] if dates[0] == dates[-1] else f"{dates[0]}-{dates[-1]}"
    scoreboard_data = await get_espn_scoreboard(date_range)

    tracked = set(TEAMS.values())
    by_day = {}
    for start, g in games:
        start_et = start.astimezone(EASTERN)
        away, home = g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]
        matchup = f"{away} @ {home}"
        if tracked & {away, home}:
            matchup = f"**{matchup}** ⭐"
        line = f"`{start_et.strftime('%-I:%M %p'):>8}` {matchup}"
        networks = national_networks(g, scoreboard_data)
        if networks:
            line += f" · {', '.join(networks)}"
        by_day.setdefault(start_et.strftime("%A, %b %-d"), []).append(line)

    embed = discord.Embed(title=f"NHL Games — Next {window_label}", color=0x00B4FF)
    for day_label, lines in by_day.items():
        value = "\n".join(lines)
        if len(value) > 1024:
            value = value[:1020].rsplit("\n", 1)[0] + "\n…"
        embed.add_field(name=day_label, value=value, inline=False)
    embed.set_footer(text=f"{len(games)} games · times ET · ⭐ = our teams")
    await ctx.send(embed=embed)

@bot.command(name='nextgames', aliases=['next'], help='Shows the next game for the Sabres, Kraken, and Stars. Use "!next all [24h|48h|3d]" for every NHL game.')
async def next_games(ctx, scope: str = None, window: str = "24h"):
    if scope and scope.lower() == "all":
        parsed = parse_window(window)
        if not parsed:
            await ctx.send("Couldn't read that time window. Try something like `!next all 24h`, `48h`, or `3d` (max 7d).")
            return
        async with ctx.typing():
            await send_league_schedule(ctx, parsed, window.lower() if parsed < timedelta(days=7) else "7d")
        return

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

async def send_daily_report(channel, recap_date, persist):
    state = load_state()
    report = await build_daily_report(recap_date, TEAMS, state)

    if persist and report.should_skip:
        print(f"Daily post for {recap_date} skipped: no games, tracked-team news, or injury changes.")
        save_state({**report.new_state, "last_posted_date": datetime.now(EASTERN).date().isoformat()})
        return

    file = discord.File(fp=report.image, filename="daily_recap.png")
    embed = None
    if report.text:
        embed = discord.Embed(description=report.text, color=0x00B4FF)
        if report.news_ranked_by == "rules":
            embed.set_footer(text="News picked by keyword rules (Claude ranking unavailable)")
    await channel.send(file=file, embed=embed)

    if persist:
        save_state({**report.new_state, "last_posted_date": datetime.now(EASTERN).date().isoformat()})

async def get_daily_channel():
    if not DAILY_CHANNEL_ID:
        return None
    try:
        return bot.get_channel(int(DAILY_CHANNEL_ID)) or await bot.fetch_channel(int(DAILY_CHANNEL_ID))
    except (discord.NotFound, discord.Forbidden, ValueError) as e:
        print(f"Could not access daily channel {DAILY_CHANNEL_ID}: {e}")
        return None

async def run_scheduled_daily_post():
    today = datetime.now(EASTERN).date()
    if load_state().get("last_posted_date") == today.isoformat():
        return
    channel = await get_daily_channel()
    if not channel:
        print("DAILY_CHANNEL_ID is not set or not accessible; skipping the daily post.")
        return
    try:
        await send_daily_report(channel, today - timedelta(days=1), persist=True)
    except Exception as e:
        print(f"Daily post failed: {e}")

@tasks.loop(time=DAILY_POST_TIME)
async def daily_post_loop():
    await run_scheduled_daily_post()

async def catch_up_daily_post():
    now = datetime.now(EASTERN)
    if DAILY_POST_TIME.hour <= now.hour < DAILY_CATCH_UP_UNTIL_HOUR:
        await run_scheduled_daily_post()

@bot.command(name='daily', help='Previews the daily recap here. "!daily YYYY-MM-DD" replays a past date, "!daily post" sends it to the daily channel now.')
async def daily_command(ctx, arg: str = None):
    async with ctx.typing():
        yesterday = datetime.now(EASTERN).date() - timedelta(days=1)

        if arg and arg.lower() == "post":
            channel = await get_daily_channel()
            if not channel:
                await ctx.send("The daily channel isn't configured (DAILY_CHANNEL_ID) or I can't access it.")
                return
            try:
                await send_daily_report(channel, yesterday, persist=True)
                if channel.id != ctx.channel.id:
                    await ctx.send(f"Posted the daily recap to {channel.mention}.")
            except Exception as e:
                await ctx.send(f"Error posting daily recap: {str(e)}")
            return

        recap_date = yesterday
        if arg:
            try:
                recap_date = date.fromisoformat(arg)
            except ValueError:
                await ctx.send("Usage: `!daily`, `!daily YYYY-MM-DD`, or `!daily post`.")
                return

        try:
            # Don't save state, so the real post still includes these news and injury changes
            await send_daily_report(ctx.channel, recap_date, persist=False)
        except Exception as e:
            await ctx.send(f"Error generating daily recap: {str(e)}")

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN not found in environment. Please check your .env file.")
