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
4.  **Run the Bot**:
    ```bash
    python main.py
    ```

## Docker Deployment

You can also deploy this bot using Docker:

1.  **Configure Environment**: Ensure you have a `.env` file with your `DISCORD_TOKEN`.
2.  **Build and Start**:
    ```bash
    docker-compose up -d --build
    ```
3.  **Logs**:
    ```bash
    docker-compose logs -f
    ```

## Commands

- `!nextgames`: Shows the next scheduled game for the Buffalo Sabres, Seattle Kraken, and Dallas Stars.
- `!player <name>`: Shows a "player card" image for the specified player, including their headshot, team logo, and current season stats.
- `!standings`: Shows a playoff overview image with division leaders and wildcard teams for both conferences.
- `!conference`: Shows a full standings image with both Eastern and Western conferences side by side.
