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

redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

# --- FLASK DASHBOARD ---
app = Flask(__name__)

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head><title>Graveyard Bot Dashboard</title></head>
<body>
<h1>🏆 Graveyard Bot Dashboard</h1>
<table border="1">
<tr><th>Discord ID</th><th>Player Tag</th></tr>
{% for user in users %}
<tr><td>{{ user['_id'] }}</td><td>#{{ user['player_id'] }}</td></tr>
{% endfor %}
</table>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML_TEMPLATE, users=list(users.find()))

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

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

        # Share DB with cogs
        self.mongo = mongo
        self.db = db
        self.users = users

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

# 🚨 IMPORTANT: NO while True, NO restart loop
bot.run(DISCORD_TOKEN)
