import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from nhl_api import get_scores, get_game_landing, get_standings_on, get_league_schedule, get_espn_news, get_espn_injuries
from news import candidate_articles, pick_stories, is_tracked
from image_generator import generate_daily_recap_image

EASTERN = ZoneInfo("America/New_York")
SEEN_NEWS_LIMIT = 300
FINAL_STATES = {"OFF", "FINAL"}

def team_abbr(value):
    # The NHL API returns teamAbbrev either as a plain string or as {"default": ...}
    return value.get("default") if isinstance(value, dict) else value

def period_suffix(game):
    return {"OT": "OT", "SO": "SO"}.get(game.get("gameOutcome", {}).get("lastPeriodType"), "")

class DailyReport:
    def __init__(self, recap_date):
        self.recap_date = recap_date
        self.image = None
        self.text = ""
        self.games_played = 0
        self.has_tracked_news = False
        self.has_injury_changes = False
        self.news_ranked_by = None
        self.new_state = None

    @property
    def should_skip(self):
        return self.games_played == 0 and not self.has_tracked_news and not self.has_injury_changes

def build_standing(s):
    return {
        "record": f"{s['wins']}-{s['losses']}-{s['otLosses']}",
        "div_rank": s.get("divisionSequence"),
        "div_name": s.get("divisionName"),
        "conf_name": s.get("conferenceName"),
        "wildcard": s.get("wildcardSequence") or 0,
        "points": s.get("points"),
        "gp": s.get("gamesPlayed"),
        "form": f"L10 {s['l10Wins']}-{s['l10Losses']}-{s['l10OtLosses']} · Streak {s.get('streakCode', '')}{s.get('streakCount', '')}",
    }

async def build_game_detail(game, abbr):
    home, away = game["homeTeam"], game["awayTeam"]
    us, them = (home, away) if home["abbrev"] == abbr else (away, home)
    detail = {
        "away_abbr": away["abbrev"], "away_score": away.get("score"),
        "home_abbr": home["abbrev"], "home_score": home.get("score"),
        "won": (us.get("score") or 0) > (them.get("score") or 0),
        "suffix": period_suffix(game),
        "final": game.get("gameState") in FINAL_STATES,
        "scorers": "",
        "stars": [],
        "playoff": None,
    }

    series = game.get("seriesStatus")
    if game.get("gameType") == 3 and series:
        title = series.get("seriesTitle", "Playoffs")
        g_num = series.get("gameNumberOfSeries")
        detail["playoff"] = f"{title} · Game {g_num}" if g_num else title

    landing = await get_game_landing(game["id"])
    summary = (landing or {}).get("summary", {})

    goal_counts = {}
    for period in summary.get("scoring", []):
        for goal in period.get("goals", []):
            if team_abbr(goal.get("teamAbbrev")) == abbr:
                name = goal.get("name", {}).get("default", "?")
                goal_counts[name] = goal_counts.get(name, 0) + 1
    detail["scorers"] = ", ".join(f"{n} ({c})" if c > 1 else n for n, c in goal_counts.items())

    for star in summary.get("threeStars", []):
        if star.get("goals") is not None:
            stat = f"{star.get('goals', 0)}G {star.get('assists', 0)}A"
        elif star.get("savePctg") is not None:
            stat = f"{star['savePctg']:.3f} SV%"
        else:
            stat = ""
        detail["stars"].append({
            "rank": star.get("star"),
            "name": star.get("name", {}).get("default", "?"),
            "team": team_abbr(star.get("teamAbbrev")),
            "stat": stat,
        })
    return detail

def format_next_game(abbr, schedule_days):
    now = datetime.now(timezone.utc)
    for day in schedule_days:
        for g in day.get("games", []):
            start = datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00"))
            home, away = g["homeTeam"]["abbrev"], g["awayTeam"]["abbrev"]
            if abbr in (home, away) and start > now:
                vs = f"vs {away}" if home == abbr else f"@ {home}"
                return f"{vs} · {start.astimezone(EASTERN).strftime('%a %-I:%M %p')}"
    return None

def diff_injuries(espn_injuries, tracked, previous):
    # With no previous snapshot (first run), every current injury is reported as new
    by_name = {t.get("displayName"): t.get("injuries", []) for t in espn_injuries}
    changes, snapshot = {}, {}
    today = datetime.now(EASTERN).date()

    for team_name, abbr in tracked.items():
        current = {}
        for inj in by_name.get(team_name, []):
            athlete = inj.get("athlete", {})
            pid = str(athlete.get("id") or athlete.get("displayName"))
            details = inj.get("details", {})
            current[pid] = {
                "name": athlete.get("displayName", "?"),
                "status": inj.get("status", "?"),
                "type": details.get("type"),
                "return": details.get("returnDate"),
            }
        snapshot[abbr] = current
        before = previous.get(abbr, {})

        lines = []
        for pid, cur in current.items():
            what = f" ({cur['type']})" if cur["type"] and cur["type"] != "Undisclosed" else ""
            est = ""
            # ESPN often uses tomorrow as a placeholder return date
            if cur["return"]:
                try:
                    ret = datetime.fromisoformat(cur["return"]).date()
                    if (ret - today).days > 3:
                        est = f", est. return {ret.strftime('%b %-d')}"
                except ValueError:
                    pass
            if pid not in before:
                lines.append(f"🆕 {cur['name']}{what} — {cur['status']}{est}")
            elif before[pid]["status"] != cur["status"]:
                lines.append(f"🔄 {cur['name']}{what} — {before[pid]['status']} → {cur['status']}{est}")
        for pid, old in before.items():
            if pid not in current:
                lines.append(f"✅ {old['name']} — off the injury report")
        if lines:
            changes[abbr] = lines
    return changes, snapshot

async def build_daily_report(recap_date, tracked, state):
    report = DailyReport(recap_date)
    date_str = recap_date.isoformat()
    tracked_abbrs = list(tracked.values())
    tracked_names = set(tracked.keys())

    games, standings_data, schedule_days, articles, injuries = await asyncio.gather(
        get_scores(date_str),
        get_standings_on(date_str),
        get_league_schedule((recap_date + timedelta(days=1)).isoformat()),
        get_espn_news(),
        get_espn_injuries(),
    )
    games = [g for g in games if g.get("gameState") in FINAL_STATES or g.get("gameScheduleState") == "PPD"]
    report.games_played = sum(1 for g in games if g.get("gameState") in FINAL_STATES)
    standings = {team_abbr(t["teamAbbrev"]): t for t in (standings_data or {}).get("standings", [])}

    cards, other_games = [], []
    tracked_games = {}
    for g in games:
        teams_in_game = [a for a in tracked_abbrs if a in (g["homeTeam"]["abbrev"], g["awayTeam"]["abbrev"])]
        for a in teams_in_game:
            tracked_games[a] = g
        if not teams_in_game:
            other_games.append({
                "away_abbr": g["awayTeam"]["abbrev"], "away_score": g["awayTeam"].get("score"),
                "home_abbr": g["homeTeam"]["abbrev"], "home_score": g["homeTeam"].get("score"),
                "suffix": period_suffix(g) if g.get("gameState") in FINAL_STATES else "PPD",
            })

    for team_name, abbr in tracked.items():
        card = {"abbr": abbr, "name": team_name, "standing": None, "game": None, "next_game": None}
        if abbr in standings:
            card["standing"] = build_standing(standings[abbr])
        g = tracked_games.get(abbr)
        if g and g.get("gameState") in FINAL_STATES:
            card["game"] = await build_game_detail(g, abbr)
        else:
            card["next_game"] = format_next_game(abbr, schedule_days)
        cards.append(card)

    date_label = datetime.combine(recap_date, datetime.min.time()).strftime("%A, %B %-d")
    report.image = await generate_daily_recap_image(date_label, cards, other_games)

    # 24 hours before the 9 AM post time
    post_time = datetime.combine(recap_date + timedelta(days=1), datetime.min.time(), EASTERN).replace(hour=9)
    since = (post_time - timedelta(hours=24)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    seen_urls = state.get("posted_news_urls", [])
    candidates = candidate_articles(articles, since, set(seen_urls))
    stories, report.news_ranked_by = await pick_stories(candidates, tracked_names)
    report.has_tracked_news = any(is_tracked(a, tracked_names) for a in stories)

    sections = []
    if stories:
        lines = ["**📰 News**"]
        for a in stories:
            lines.append(f"• [{a['headline']}]({a['links']['web']['href']})")
        sections.append("\n".join(lines))

    new_injury_state = state.get("injuries", {})
    if injuries is not None:
        changes, new_injury_state = diff_injuries(injuries, tracked, state.get("injuries", {}))
        report.has_injury_changes = bool(changes)
        if changes:
            lines = ["**🩹 Injury Updates**"]
            for abbr in tracked_abbrs:
                if abbr in changes:
                    lines.append(f"**{abbr}**")
                    lines.extend(changes[abbr])
            sections.append("\n".join(lines))

    text = "\n\n".join(sections)
    if len(text) > 4000:
        text = text[:3990].rsplit("\n", 1)[0] + "\n…"
    report.text = text

    new_urls = [a["links"]["web"]["href"] for a in stories]
    report.new_state = {
        **state,
        "posted_news_urls": (seen_urls + new_urls)[-SEEN_NEWS_LIMIT:],
        "injuries": new_injury_state,
    }
    return report
