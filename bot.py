import os
import logging
import discord
import aiohttp
import redis
import threading
import time
import traceback
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
users_collection = db["users"] # Renamed local variable for clarity

# --- REDIS (OPTIONAL) ---
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        log.info("✅ Redis connected")
    except Exception as e:
        log.error(f"❌ Redis failed: {e}")

# --- FLASK DASHBOARD ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Graveyard Bot Dashboard</title>
</head>
<body>
<h1>🏆 Graveyard Bot Dashboard</h1>
<table border="1">
<tr><th>Discord ID</th><th>Player Tag</th></tr>
{% for user in users %}
<tr>
    <td>{{ user['_id'] }}</td>
    <td>#{{ user.get('player_id', '???') }}</td>
</tr>
{% endfor %}
</table>
</body>
</html>
"""

@app.route("/")
def home():
    # Pass the actual collection data to the template
    return render_template_string(HTML_TEMPLATE, users=list(users_collection.find()))

def run_flask():
    # Windows Socket Error Fix: Use port 5000 if 8080/10000 fails
    port = int(os.getenv("PORT", 5000))
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
        self.http_session = aiohttp.ClientSession(headers={
            "Authorization": f"Bearer {CR_TOKEN}",
            "Accept": "application/json"
        })

        # Share DB + Redis with cogs
        self.mongo = mongo
        self.db = db
        # ✅ FIX: Renamed from self.users to self.db_users
        self.db_users = users_collection 
        self.redis = redis_client

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

    async def close(self):
        if hasattr(self, "http_session"):
            await self.http_session.close()
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
