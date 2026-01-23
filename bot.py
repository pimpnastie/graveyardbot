import os, logging, discord, aiohttp, redis, threading, time, traceback
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

# --- DATABASE ---
mongo = MongoClient(MONGO_URL)
db = mongo["ClashBotDB"]
users = db["users"]

# Initialize Redis (SAFE MODE: handles if Redis URL is missing)
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        log.info("✅ Redis Connected")
    except Exception as e:
        log.error(f"❌ Redis Connection Failed: {e}")

# --- FLASK DASHBOARD ---
app = Flask(__name__)

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head><title>Graveyard Bot Dashboard</title></head>
<body>
<h1>🏆 Graveyard Bot Dashboard</h1>
<table border="1">
<tr><th>Discord ID</th><th>Player Tag</th><th>Roles</th></tr>
{% for user in users %}
<tr>
    <td>{{ user['_id'] }}</td>
    <td>#{{ user.get('player_id', '???') }}</td>
    <td>{{ user.get('roles', []) }}</td>
</tr>
{% endfor %}
</table>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML_TEMPLATE, users=list(users.find()))

def run_flask():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# --- DISCORD BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # REQUIRED for role syncing

class ClashBot(commands.AutoShardedBot):
    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(headers={
            "Authorization": f"Bearer {CR_TOKEN}",
            "Accept": "application/json"
        })

        # --- SHARE RESOURCES WITH COGS ---
        self.mongo = mongo
        self.db = db
        self.users = users
        self.redis = redis_client # <--- NEW: Cog access to Redis

        await self.load_extension("cogs.link")
        await self.tree.sync()

    async def close(self):
        if hasattr(self, "http_session"):
            await self.http_session.close()
        await super().close()

bot = ClashBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    print(f"🌐 Guilds: {len(bot.guilds)}")

# 🚨 ONE-TRY STARTUP LOGIC
if __name__ == "__main__":
    import sys
    import time
    
    print("🚀 Attempting to start bot (Single Attempt)...")
    
    try:
        # This will block here as long as the bot is running.
        # It only returns or errors if the connection dies completely.
        bot.run(DISCORD_TOKEN)
        
    except Exception as e:
        # If we get here, the connection failed.
        print(f"\n❌ CRITICAL ERROR: {e}")
        print("🛑 STOPPING: The bot failed to connect.")
        print("💤 Entering 'Coma Mode' to prevent Render restart loop.")
        print("👉 You must manually REDEPLOY to try again.")

        # Infinite loop that does NOTHING. 
        # The process stays "alive", so Render doesn't restart it.
        # But it makes 0 calls to Discord.
        while True:
            time.sleep(3600)
