import json
import os
import anthropic

NEWS_MODEL = "claude-haiku-4-5"
MAX_STORIES = 5

# Game results are already in the recap image
SKIPPED_TYPES = {"Preview", "Recap", "Media"}

SYSTEM_PROMPT = """You pick NHL news stories for a daily post in a small friend group's Discord server.
The group follows these teams closely: {tracked}.

Pick up to {max_stories} stories from the numbered list, best first:
1. Any meaningful story about a followed team (injuries, trades, signings, call-ups, suspensions, coaching changes).
2. Then league news that a hockey fan would genuinely want to know: notable trades, significant injuries to star players, suspensions, major signings, milestones.

Skip fantasy advice, power rankings, betting content, game previews/recaps, and light human-interest pieces unless nothing better exists.
Never pick two stories about the same event. Picking fewer than {max_stories} is fine if the rest are not worth posting."""

PICKS_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Numbers of the chosen stories, best first",
        }
    },
    "required": ["picks"],
    "additionalProperties": False,
}

def article_teams(article):
    return {c.get("description") for c in article.get("categories", []) if c.get("type") == "team"}

def is_tracked(article, tracked_names):
    # Power rankings etc. tag every team
    teams = article_teams(article)
    return bool(teams & tracked_names) and len(teams) <= 4

def candidate_articles(articles, since, seen_urls):
    candidates = []
    for a in articles:
        url = a.get("links", {}).get("web", {}).get("href")
        if not url or url in seen_urls:
            continue
        if a.get("type") in SKIPPED_TYPES:
            continue
        if a.get("published", "") < since:
            continue
        candidates.append(a)
    return candidates

def rank_by_rules(candidates, tracked_names):
    keep = [a for a in candidates if is_tracked(a, tracked_names) or a.get("type") == "HeadlineNews"]
    return sorted(keep, key=lambda a: not is_tracked(a, tracked_names))[:MAX_STORIES]

async def rank_with_claude(candidates, tracked_names):
    client = anthropic.AsyncAnthropic()
    lines = []
    for i, a in enumerate(candidates, start=1):
        teams = ", ".join(sorted(article_teams(a))) or "none"
        if len(article_teams(a)) > 4:
            teams = "many teams"
        desc = (a.get("description") or "").replace("\n", " ")[:200]
        lines.append(f"[{i}] ({a.get('type')}; teams: {teams}) {a.get('headline')} — {desc}")

    response = await client.messages.create(
        model=NEWS_MODEL,
        max_tokens=256,
        system=SYSTEM_PROMPT.format(tracked=", ".join(sorted(tracked_names)), max_stories=MAX_STORIES),
        messages=[{"role": "user", "content": "\n".join(lines)}],
        output_config={"format": {"type": "json_schema", "schema": PICKS_SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    picks = json.loads(text)["picks"]

    chosen = []
    for n in picks:
        if 1 <= n <= len(candidates) and candidates[n - 1] not in chosen:
            chosen.append(candidates[n - 1])
    return chosen[:MAX_STORIES]

async def pick_stories(candidates, tracked_names):
    if not candidates:
        return [], "rules"
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return await rank_with_claude(candidates, tracked_names), "claude"
        except Exception as e:
            print(f"News ranking with Claude failed, falling back to rules: {e}")
    return rank_by_rules(candidates, tracked_names), "rules"
