import os
import logging
import discord
import aiohttp
import redis
import threading
import time
import traceback
import asyncio
import copy
from flask import Flask, render_template_string
from discord.ext import commands
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clashbot")

# --- CONFIG ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CR_TOKEN = os.getenv("CR_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
REDIS_URL = os.getenv("REDIS_URL")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

# --- DATABASE ---
mongo = MongoClient(MONGO_URL)
db = mongo["ClashBotDB"]
users_collection = db["users"]

# --- REDIS (OPTIONAL) ---
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        log.info("✅ Redis connected")
    except Exception as e:
        log.error(f"❌ Redis failed: {e}")

# --- FLASK DASHBOARD ---
# ⚠️ THIS MUST COME BEFORE THE @app.route LINES
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Graveyard Bot Dashboard</title>
    <style>
        body { font-family: sans-serif; background-color: #f0f2f5; padding: 20px; }
        h1 { color: #333; text-align: center; }
        table {
            border-collapse: collapse;
            width: 100%;
            max-width: 900px;
            margin: 0 auto;
            background: white;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
            border-radius: 8px;
            overflow: hidden;
        }
        th, td { padding: 12px 15px; text-align: left; }
        th { background-color: #4CAF50; color: white; font-weight: bold; }
        tr:nth-child(even) { background-color: #f9f9f9; }
        tr:hover { background-color: #f1f1f1; }
        .tag { font-family: monospace; color: #555; }
        .trophy { color: #d32f2f; font-weight: bold; }
    </style>
</head>
<body>

    <h1>🏆 Graveyard Bot Dashboard</h1>

    <table>
        <thead>
            <tr>
                <th>Discord User</th>
                <th>Player Tag</th>
                <th>Rank / Arena</th>
                <th>Trophies</th>
            </tr>
        </thead>
        <tbody>
            {% for user in users %}
            <tr>
                <td><b>{{ user.discord_name }}</b></td>
                <td class="tag">{{ user.player_tag }}</td>
                <td>{{ user.rank }}</td>
                <td class="trophy">🏆 {{ user.trophies }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

</body>
</html>
"""

@app.route("/")
def home():
    # Check if bot is ready to serve data
    if not bot or not bot.is_ready():
        return "<h1>Bot is starting...</h1><p>Please wait a moment for the data to load.</p>", 503

    try:
        # Fetch all linked users from Mongo
        db_users = list(users_collection.find())
        dashboard_data = []

        for user in db_users:
            try:
                discord_id = int(user["_id"])
                player_tag = user.get("player_id", "")
                clean_tag = player_tag.replace("#", "")

                # 1. Get Discord Name (from Bot Cache)
                discord_obj = bot.get_user(discord_id)
                discord_name = discord_obj.name if discord_obj else f"Unknown ({discord_id})"

                # 2. Get Clash Stats (Live API Fetch)
                trophies = "N/A"
                rank = "N/A"

                if clean_tag:
                    url = f"https://proxy.royaleapi.dev/v1/players/%23{clean_tag}"
                    
                    # We must run the async API call safely from this synchronous Flask thread
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            bot.fetch_api(url), bot.loop
                        )
                        # Wait up to 5 seconds for the result
                        clash_data = future.result(timeout=5)
                        
                        if clash_data:
                            trophies = clash_data.get("trophies", 0)
                            rank = clash_data.get("arena", {}).get("name", "Unknown")
                    except Exception as e:
                        log.error(f"Dashboard API fetch failed for {clean_tag}: {e}")

                dashboard_data.append({
                    "discord_name": discord_name,
                    "player_tag": player_tag,
                    "rank": rank,
                    "trophies": trophies
                })
            except Exception as e:
                log.error(f"Error processing user {user.get('_id')}: {e}")
                continue

        # Sort by Trophies (Highest first)
        dashboard_data.sort(key=lambda x: x["trophies"] if isinstance(x["trophies"], int) else -1, reverse=True)

        return render_template_string(HTML_TEMPLATE, users=dashboard_data)

    except Exception:
        log.exception("Dashboard: Critical error in home route")
        return "<h1>Internal Server Error</h1>", 500


def run_flask():
    # Render tends to use port 10000; default to 10000 when no PORT provided
    port = int(os.getenv("PORT", 10000))
    try:
        app.run(host="0.0.0.0", port=port)
    except OSError:
        log.warning(f"⚠️ Port {port} failed, trying 5001")
        app.run(host="0.0.0.0", port=5001)

threading.Thread(target=run_flask, daemon=True).start()

# --- DISCORD BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class ClashBot(commands.AutoShardedBot):
    async def setup_hook(self):
        headers = {"Accept": "application/json"}
        if CR_TOKEN:
            headers["Authorization"] = f"Bearer {CR_TOKEN}"
        self.http_session = aiohttp.ClientSession(headers=headers)

        # Shared resources
        self.mongo = mongo
        self.db = db
        self.db_users = users_collection
        self.redis = redis_client

        # API helpers: in-memory cache and concurrency limiter
        self.api_cache = {}  # url -> (expiry_ts, data)
        self.api_semaphore = asyncio.Semaphore(int(os.getenv("API_CONCURRENCY", "6")))

        # Ensure indexes and basic DB setup run at startup (non-blocking)
        await self._ensure_db_indexes()

        # --- 🛠️ LOAD ALL EXTENSIONS ---
        extensions = [
            "cogs.link",
            "cogs.admin",
            "cogs.war",
            "cogs.reminders"
        ]

        for ext in extensions:
            try:
                await self.load_extension(ext)
                log.info(f"✅ Loaded extension: {ext}")
            except Exception as e:
                log.error(f"❌ Failed to load extension {ext}: {e}")

        await self.tree.sync()

    async def _ensure_db_indexes(self):
        loop = asyncio.get_running_loop()
        def blocking_create_indexes():
            try:
                db.clan_history.create_index(
                    [("clan_tag", 1), ("timestamp", -1)],
                    name="clan_ts_idx",
                    background=True
                )
                db.player_history.create_index(
                    [("player_tag", 1), ("timestamp", -1)],
                    name="player_ts_idx",
                    background=True
                )
                db.player_history.create_index(
                    [("discord_id", 1), ("timestamp", -1)],
                    name="discord_ts_idx",
                    background=True,
                    sparse=True
                )
                ttl_days = os.getenv("CLAN_HISTORY_TTL_DAYS")
                if ttl_days:
                    try:
                        seconds = int(ttl_days) * 24 * 3600
                        db.clan_history.create_index("timestamp", expireAfterSeconds=seconds, name="clan_history_ttl", background=True)
                    except Exception:
                        log.exception("Failed to create TTL index for clan_history")

                log.info("✅ DB indexes ensured")
            except Exception:
                log.exception("Failed to ensure DB indexes")

        await loop.run_in_executor(None, blocking_create_indexes)

    async def fetch_api(self, url, ttl=300):
        """Simple in-memory TTL cache and concurrency-limited fetch helper.
        Returns parsed JSON or None on failure."""
        now = time.time()
        cached = self.api_cache.get(url)
        if cached and cached[0] > now:
            # return a deepcopy so callers don't mutate cache
            return copy.deepcopy(cached[1])

        async with self.api_semaphore:
            try:
                async with self.http_session.get(url) as resp:
                    if resp.status != 200:
                        log.debug("API %s returned status %s", url, resp.status)
                        return None
                    data = await resp.json()
                    # store a deepcopy to avoid accidental mutation later
                    self.api_cache[url] = (now + ttl, copy.deepcopy(data))
                    return copy.deepcopy(data)
            except Exception:
                log.exception("API fetch failed for %s", url)
                return None

    async def close(self):
        if hasattr(self, "http_session"):
            try:
                await self.http_session.close()
            except Exception:
                log.exception("Error closing http_session")

        # Skip closing the global MongoClient here to avoid interfering with the Flask dashboard.
        log.debug("Skipping mongo.close() to avoid closing client while dashboard is running")

        await super().close()

bot = ClashBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user} ({bot.user.id})")
    log.info(f"🌐 Connected to {len(bot.guilds)} guilds")

@bot.event
async def on_disconnect():
    log.warning("⚠️ Disconnected from Discord")

@bot.event
async def on_resumed():
    log.info("🔄 Discord session resumed")

@bot.event
async def on_command_error(ctx, error):
    # Friendly handling for common errors
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        try:
            await ctx.reply("Missing argument for command. See command help.", mention_author=False)
        except Exception:
            log.exception("Failed to send MissingRequiredArgument reply")
        return
    log.exception("Unhandled command error: %s", error)

# --- SINGLE ATTEMPT START ---
if __name__ == "__main__":
    print("🚀 Starting bot (single attempt mode)")

    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        traceback.print_exc()
        print("🛑 Entering safe idle mode to avoid rate limits")

        while True:
            time.sleep(3600)
