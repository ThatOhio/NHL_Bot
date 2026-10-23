# NHL Discord Bot

A simple Discord bot that provides upcoming game information for the Buffalo Sabres, Seattle Kraken, and Dallas Stars.

## Setup

1.  **Clone the repository** (if you haven't already).
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configure Environment**:
    - Copy and Rename `.env.example` to `.env`.
    - Add the Discord bot token to the `.env` file:
      ```
      DISCORD_TOKEN=bot_token_here
      ```
    - `DAILY_CHANNEL_ID`: channel or thread for the daily recap.
    - `ANTHROPIC_API_KEY` (optional): used to pick news stories with Claude Haiku. Falls back to keyword rules if unset.
4.  **Run the Bot**:
    ```bash
    python main.py
    ```

## Docker Deployment

You can also deploy this bot using Docker:

1.  **Configure Environment**: Ensure you have a `.env` file with your `DISCORD_TOKEN`.
2.  **State Volume**: `./data` is mounted into the container to store daily recap state (posted news links, last injury report).
3.  **Build and Start**:
    ```bash
    docker-compose up -d --build
    ```
4.  **Logs**:
    ```bash
    docker-compose logs -f
    ```

## Commands

- `!nextgames`: Shows the next scheduled game for the Buffalo Sabres, Seattle Kraken, and Dallas Stars.
- `!next all [window]`: Lists every NHL game in the given window (default `24h`, e.g. `48h`, `3d`, max `7d`).
- `!daily`: Previews the daily recap in the current channel without saving state. `!daily YYYY-MM-DD` shows a past date, `!daily post` posts to the daily channel now.
- `!player <name>`: Shows a "player card" image for the specified player, including headshot, team logo, position, physical profile (height/weight), and current season stats.
- `!standings`: Shows a playoff overview image with division leaders and wildcard teams for both conferences.
- `!conference`: Shows a full standings image with both Eastern and Western conferences side by side.

## Daily Recap

Posted daily at 9:00 AM ET to `DAILY_CHANNEL_ID`:

- **Image**: tracked team cards (game result, scorers, three stars, or standings and next game if they didn't play) and all other final scores.
- **News**: up to 5 ESPN stories from the last 24 hours, tracked teams first.
- **Injury Updates**: changes to the tracked teams' injury lists since the last post.

Skipped if there were no games, tracked-team news, or injury changes. If the bot is offline at 9 AM it posts on startup, until noon ET.
