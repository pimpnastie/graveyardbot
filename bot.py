import os, logging, discord, aiohttp, redis, threading
from flask import Flask, render_template_string
from discord.ext import commands
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clashbot")

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CR_TOKEN = os.getenv("CR_TOKEN") 
MONGO_URL = os.getenv("MONGO_URL")
REDIS_URL = os.getenv("REDIS_URL")

CR_API_BASE = "https://proxy.royaleapi.dev/v1"

# --- DATABASE SETUP ---
mongo = MongoClient(MONGO_URL)
db = mongo["ClashBotDB"]
users = db["users"]

redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

# --- FLASK WEB DASHBOARD ---
app = Flask(__name__)

# This HTML template makes the page look nice (Dark Mode!)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Graveyard Bot Dashboard</title>
    <style>
        body { font-family: sans-serif; background-color: #2c2f33; color: #ffffff; padding: 20px; }
        h1 { color: #7289da; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; background-color: #23272a; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #99aab5; }
        th { background-color: #7289da; color: white; }
        tr:hover { background-color: #2c2f33; }
        .container { max-width: 800px; margin: 0 auto; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏆 Graveyard Bot Dashboard</h1>
        <p>Bot Status: <span style="color: #43b581; font-weight: bold;">ONLINE</span></p>
        
        <h2>🔗 Linked Players</h2>
        <table>
            <tr>
                <th>Discord ID</th>
                <th>Clash Player ID</th>
            </tr>
            {% for user in users %}
            <tr>
                <td>{{ user['_id'] }}</td>
                <td>#{{ user['player_id'] }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    # Fetch all linked users from MongoDB
    all_users = list(users.find())
    return render_template_string(HTML_TEMPLATE, users=all_users)

def run_flask():
    port = int(os.getenv("PORT", 8080))
    # host='0.0.0.0' is required for Render to see the website
    app.run(host='0.0.0.0', port=port)

def start_keep_alive():
    # Run Flask in a separate thread so it doesn't block the bot
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class ClashBot(commands.AutoShardedBot):
    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(headers={
            "Authorization": f"Bearer {CR_TOKEN}",
            "Accept": "application/json"
        })
        for cog in ("link", "war", "admin", "reminders"):
            try:
                await self.load_extension(f"cogs.{cog}")
                log.info(f"Loaded extension: {cog}")
            except Exception as e:
                log.error(f"Failed to load extension {cog}: {e}")
        
        await self.tree.sync()

    async def close(self):
        if hasattr(self, 'http_session') and self.http_session:
            await self.http_session.close()
        if 'mongo' in globals() and mongo:
            mongo.close()
        await super().close()

bot = ClashBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} | shards={bot.shard_count}")

# --- HELPER TO FETCH API DATA ---
async def cr_get(endpoint: str):
    key = f"cr:{endpoint}"
    if redis_client:
        cached = redis_client.get(key)
        if cached:
            import json
            return json.loads(cached)

    url = f"{CR_API_BASE}{endpoint}"
    async with bot.http_session.get(url) as resp:
        if resp.status == 200:
            data = await resp.json()
            if redis_client:
                import json
                redis_client.setex(key, 300, json.dumps(data))
            return data
        else:
            log.error(f"API Error {resp.status} on {url}")
            return None

def get_player_id(discord_id: int):
    doc = users.find_one({"_id": str(discord_id)})
    return doc["player_id"] if doc else None

def normalize(tag):
    return tag.replace("#", "").upper()

if __name__ == "__main__":
    # Start the Flask Web Server
    start_keep_alive()
    # Start the Discord Bot
    bot.run(DISCORD_TOKEN)
