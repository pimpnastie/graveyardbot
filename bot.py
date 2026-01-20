import os, logging, discord, aiohttp, redis
from discord.ext import commands
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clashbot")

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# Fixed: Matches the 'CR_TOKEN' key in your Render Screenshot
CR_TOKEN = os.getenv("CR_TOKEN") 
MONGO_URL = os.getenv("MONGO_URL")
REDIS_URL = os.getenv("REDIS_URL")

CR_API_BASE = "https://api.clashroyale.com/v1"

# --- DATABASE SETUP ---
mongo = MongoClient(MONGO_URL)
db = mongo["ClashBotDB"]
users = db["users"]
guilds = db["guilds"]

# DELETED: users.create_index("_id", unique=True) <-- Caused the crash. MongoDB handles this automatically!

# Redis is optional
redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

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
        # Load your cogs
        for cog in ("link", "war", "admin", "reminders"):
            try:
                await self.load_extension(f"cogs.{cog}")
                log.info(f"Loaded extension: {cog}")
            except Exception as e:
                log.error(f"Failed to load extension {cog}: {e}")
        
        await self.tree.sync()

    async def close(self):
        await self.http_session.close()
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
    bot.run(DISCORD_TOKEN)
