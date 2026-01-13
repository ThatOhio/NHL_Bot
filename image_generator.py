import io
import aiohttp
from PIL import Image, ImageDraw, ImageFont

# Common linux font paths, updated for standard Docker/Debian paths
FONT_PATHS = [
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/Adwaita/AdwaitaSans-Bold.ttf",
]

LOGO_CACHE = {}

def get_font(size):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except:
            continue
    return ImageFont.load_default()

async def fetch_image(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                return await response.read()
    return None

async def get_team_logo(team_abbr):
    team_abbr = team_abbr.lower()
    
    # Some NHL abbreviations have different ESPN abbreviations
    espn_map = {
        "tbl": "tb",
        "sjs": "sj",
        "lak": "la"
    }
    espn_abbr = espn_map.get(team_abbr, team_abbr)
    
    if team_abbr in LOGO_CACHE:
        return LOGO_CACHE[team_abbr]
    
    url = f"https://a.espncdn.com/i/teamlogos/nhl/500/{espn_abbr}.png"
    data = await fetch_image(url)
    if data:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        LOGO_CACHE[team_abbr] = img
        return img
    return None

async def generate_player_card(data):
    width, height = 500, 700
    card = Image.new('RGB', (width, height), color=(20, 20, 20))
    draw = ImageDraw.Draw(card)
    
    headshot_url = data.get("headshot")
    team_abbr = data.get("currentTeamAbbrev")
    
    headshot_data = await fetch_image(headshot_url)
    logo = await get_team_logo(team_abbr)
    
    # Simple border
    draw.rectangle([10, 10, width-10, height-10], outline=(50, 50, 50), width=5)
    
    if headshot_data:
        headshot = Image.open(io.BytesIO(headshot_data)).convert("RGBA")
        # Resize headshot, typical size is ~260x260
        headshot = headshot.resize((350, 350))
        # Center headshot
        card.paste(headshot, (75, 120), headshot)
        
    # Add Logo (top right)
    if logo:
        logo_resized = logo.resize((100, 100), Image.LANCZOS)
        card.paste(logo_resized, (width - 120, 20), logo_resized)
        
    # Player Info
    name_font = get_font(40)
    info_font = get_font(25)
    
    first_name = data.get("firstName", {}).get("default", "")
    last_name = data.get("lastName", {}).get("default", "").upper()
    number = data.get("sweaterNumber", "")
    pos = data.get("position", "")
    team_name = data.get("fullTeamName", {}).get("default", "")
    
    draw.text((30, 30), first_name, font=get_font(25), fill=(200, 200, 200))
    draw.text((30, 60), last_name, font=name_font, fill=(255, 255, 255))
    draw.text((30, 110), f"#{number} | {pos} | {team_name}", font=info_font, fill=(150, 150, 150))

    # Stats Section
    stats_y = 500
    draw.line([30, stats_y - 10, width-30, stats_y - 10], fill=(100, 100, 100), width=2)
    
    featured_stats = data.get("featuredStats", {}).get("regularSeason", {}).get("subSeason", {})
    if not featured_stats:
        draw.text((width//2, stats_y + 50), "No stats available for current season", font=info_font, fill=(150, 150, 150), anchor="mm")
    else:
        is_goalie = pos == "G"
        if is_goalie:
            stats = [
                ("GP", featured_stats.get("gamesPlayed", 0)),
                ("W", featured_stats.get("wins", 0)),
                ("L", featured_stats.get("losses", 0)),
                ("OTL", featured_stats.get("otLosses", 0)),
                ("GAA", f"{featured_stats.get('goalsAgainstAvg', 0.0):.2f}"),
                ("SV%", f"{featured_stats.get('savePctg', 0.0):.3f}")
            ]
        else:
            stats = [
                ("GP", featured_stats.get("gamesPlayed", 0)),
                ("G", featured_stats.get("goals", 0)),
                ("A", featured_stats.get("assists", 0)),
                ("P", featured_stats.get("points", 0)),
                ("+/-", featured_stats.get("plusMinus", 0)),
                ("SOG", featured_stats.get("shots", 0))
            ]
            
        # Draw stats headers and values
        if is_goalie:
            # Weighted widths for goalies: 4 narrow, 2 wide (GAA, SV%)
            # 60*4 + 100*2 = 440
            stat_widths = [60, 60, 60, 60, 100, 100]
        else:
            stat_width = (width - 60) // len(stats)
            stat_widths = [stat_width] * len(stats)
            
        header_font = get_font(20)
        value_font = get_font(35)
        
        x_offset = 30
        for i, (label, value) in enumerate(stats):
            w = stat_widths[i]
            x = x_offset + w // 2
            draw.text((x, stats_y + 20), label, font=header_font, fill=(150, 150, 150), anchor="mm")
            draw.text((x, stats_y + 60), str(value), font=value_font, fill=(255, 255, 255), anchor="mm")
            x_offset += w

    # Footer
    footer_font = get_font(15)
    season = data.get("featuredStats", {}).get("season", "N/A")
    draw.text((width//2, height - 30), f"NHL Stats Season {season}", font=footer_font, fill=(100, 100, 100), anchor="mm")

    # Save to buffer
    buffer = io.BytesIO()
    card.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer

async def draw_team_row(draw, img, team, x, y, team_font, points_font):
    abbr = team["teamAbbrev"]["default"]
    logo = await get_team_logo(abbr)
    if logo:
        # Resize logo to fit row
        logo_small = logo.resize((32, 32), Image.LANCZOS)
        img.paste(logo_small, (x, y), logo_small)
    
    name = team["teamName"]["default"]
    points = team["points"]
    gp = team["gamesPlayed"]
    record = f"{team['wins']}-{team['losses']}-{team['otLosses']}"
    
    draw.text((x + 45, y + 16), name, font=team_font, fill=(255, 255, 255), anchor="lm")
    
    # Points and record
    stats_text = f"{gp} GP | {record} | {points} PTS"
    draw.text((x + 500, y + 16), stats_text, font=points_font, fill=(200, 200, 200), anchor="rm")

async def generate_standings_image(data):
    width, height = 1200, 650
    img = Image.new('RGB', (width, height), color=(20, 20, 20))
    draw = ImageDraw.Draw(img)
    
    # Draw Border
    draw.rectangle([10, 10, width-10, height-10], outline=(50, 50, 50), width=5)
    
    standings = data.get("standings", [])
    if not standings:
        return None

    # Title
    draw.text((width//2, 45), "NHL PLAYOFF PICTURE", font=get_font(40), fill=(255, 255, 255), anchor="mm")
    
    def get_conf_data(conf_abbr):
        conf_teams = [s for s in standings if s["conferenceAbbrev"] == conf_abbr]
        div_names = sorted(list(set(t["divisionName"] for t in conf_teams)))
        
        div_leaders = []
        for d_name in div_names:
            teams = sorted([t for t in conf_teams if t["divisionName"] == d_name and t["wildcardSequence"] == 0], 
                           key=lambda x: x["divisionSequence"])[:3]
            div_leaders.append((d_name, teams))
        
        wildcards = sorted([t for t in conf_teams if t["wildcardSequence"] in [1, 2]], 
                           key=lambda x: x["wildcardSequence"])
        return div_leaders, wildcards

    east_divs, east_wc = get_conf_data("E")
    west_divs, west_wc = get_conf_data("W")

    # Fonts
    conf_font = get_font(30)
    div_header_font = get_font(22)
    team_font = get_font(18)
    points_font = get_font(18)

    # Render Eastern Conference (Left)
    # Balanced margins: Left 66, Middle 68, Right 66
    ex = 66
    ey = 105
    draw.text((ex + 250, ey), "EASTERN CONFERENCE", font=conf_font, fill=(0, 150, 255), anchor="mm")
    ey += 50
    
    for div_name, teams in east_divs:
        draw.text((ex, ey), div_name.upper(), font=div_header_font, fill=(150, 150, 150))
        ey += 30
        for t in teams:
            await draw_team_row(draw, img, t, ex, ey, team_font, points_font)
            ey += 40
        ey += 15
    
    draw.text((ex, ey), "WILD CARD", font=div_header_font, fill=(150, 150, 150))
    ey += 30
    for t in east_wc:
        await draw_team_row(draw, img, t, ex, ey, team_font, points_font)
        ey += 40

    # Render Western Conference (Right)
    wx = 634
    wy = 105
    draw.text((wx + 250, wy), "WESTERN CONFERENCE", font=conf_font, fill=(255, 50, 50), anchor="mm")
    wy += 50
    
    for div_name, teams in west_divs:
        draw.text((wx, wy), div_name.upper(), font=div_header_font, fill=(150, 150, 150))
        wy += 30
        for t in teams:
            await draw_team_row(draw, img, t, wx, wy, team_font, points_font)
            wy += 40
        wy += 15
        
    draw.text((wx, wy), "WILD CARD", font=div_header_font, fill=(150, 150, 150))
    wy += 30
    for t in west_wc:
        await draw_team_row(draw, img, t, wx, wy, team_font, points_font)
        wy += 40

    # Save to buffer
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer

async def generate_conference_image(data):
    standings = data.get("standings", [])
    if not standings:
        return None
        
    # Full League, Side by Side
    east = sorted([s for s in standings if s["conferenceAbbrev"] == "E"], key=lambda x: x["conferenceSequence"])
    west = sorted([s for s in standings if s["conferenceAbbrev"] == "W"], key=lambda x: x["conferenceSequence"])
    title = "NHL STANDINGS"
    width = 1200
    height = 100 + max(len(east), len(west)) * 45 + 50
        
    img = Image.new('RGB', (width, height), color=(20, 20, 20))
    draw = ImageDraw.Draw(img)
    
    # Draw Border
    draw.rectangle([10, 10, width-10, height-10], outline=(50, 50, 50), width=5)
    
    draw.text((width//2, 45), title, font=get_font(35), fill=(255, 255, 255), anchor="mm")
    
    team_font = get_font(18)
    points_font = get_font(18)
    
    # Vertical Separator
    draw.line([width//2, 80, width//2, height - 30], fill=(50, 50, 50), width=2)

    # Balanced margins for two columns
    # Left: 33, Middle: 34, Right: 33
    # East Index: 73, East Row: 83
    # West Index: 657, West Row: 667
    
    # East
    curr_y = 105
    draw.text((333, curr_y - 30), "EASTERN", font=get_font(25), fill=(0, 150, 255), anchor="mm")
    for i, t in enumerate(east):
        draw.text((73, curr_y + 16), f"{i+1}.", font=team_font, fill=(150, 150, 150), anchor="rm")
        await draw_team_row(draw, img, t, 83, curr_y, team_font, points_font)
        curr_y += 45
    
    # West
    curr_y = 105
    draw.text((917, curr_y - 30), "WESTERN", font=get_font(25), fill=(255, 50, 50), anchor="mm")
    for i, t in enumerate(west):
        draw.text((657, curr_y + 16), f"{i+1}.", font=team_font, fill=(150, 150, 150), anchor="rm")
        await draw_team_row(draw, img, t, 667, curr_y, team_font, points_font)
        curr_y += 45
            
    # Save to buffer
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer

async def generate_next_games_image(games_data):
    # games_data: list of {team_name, team_abbr, opponent_abbr, is_home, time_str}
    width, height = 900, 400
    img = Image.new('RGB', (width, height), color=(20, 20, 20))
    draw = ImageDraw.Draw(img)
    
    # Border + Title
    draw.rectangle([10, 10, width-10, height-10], outline=(50, 50, 50), width=5)
    draw.text((width//2, 50), "UPCOMING GAMES", font=get_font(40), fill=(255, 255, 255), anchor="mm")
    
    # Fonts
    team_name_font = get_font(28)
    vs_font = get_font(24)
    time_font = get_font(22)
    
    # EAch team column width
    col_width = (width - 40) // 3
    
    for i, data in enumerate(games_data):
        x_center = 20 + (i * col_width) + (col_width // 2)
        y_offset = 130
        
        # Team Name
        draw.text((x_center, y_offset), data['team_name'], font=team_name_font, fill=(255, 255, 255), anchor="mm")
        y_offset += 80
        
        # Logos
        our_logo = await get_team_logo(data['team_abbr'])
        opp_logo = await get_team_logo(data['opponent_abbr'])
        
        logo_size = 100
        
        if our_logo:
            our_logo_res = our_logo.resize((logo_size, logo_size), Image.LANCZOS)
            img.paste(our_logo_res, (x_center - logo_size - 30, y_offset - logo_size // 2), our_logo_res)
            
        vs_text = "VS" if data['is_home'] else "@"
        draw.text((x_center, y_offset), vs_text, font=vs_font, fill=(150, 150, 150), anchor="mm")
        
        if opp_logo:
            opp_logo_res = opp_logo.resize((logo_size, logo_size), Image.LANCZOS)
            img.paste(opp_logo_res, (x_center + 30, y_offset - logo_size // 2), opp_logo_res)
            
        y_offset += 90
        
        # Time, split if it's too long
        time_str = data['time_str']
        if " @ " in time_str:
            day, time = time_str.split(" @ ", 1)
            draw.text((x_center, y_offset), day, font=time_font, fill=(200, 200, 200), anchor="mm")
            draw.text((x_center, y_offset + 30), time, font=time_font, fill=(200, 200, 200), anchor="mm")
        else:
            draw.text((x_center, y_offset), time_str, font=time_font, fill=(200, 200, 200), anchor="mm")

    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer
