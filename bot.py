import os, logging, discord, aiohttp, redis
from discord.ext import commands
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clashbot")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CR_TOKEN = os.getenv("CR_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
REDIS_URL = os.getenv("REDIS_URL")

CR_API_BASE = "https://proxy.royaleapi.dev/v1"

mongo = MongoClient(MONGO_URL)
db = mongo["ClashBotDB"]
users = db["users"]
guilds = db["guilds"]

users.create_index("_id", unique=True)

redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class ClashBot(commands.AutoShardedBot):
    async def setup_hook(self):
        self.http = aiohttp.ClientSession(headers={
            "Authorization": f"Bearer {CR_TOKEN}",
            "Accept": "application/json"
        })
        for cog in ("link", "war", "admin", "reminders"):
            await self.load_extension(f"cogs.{cog}")
        await self.tree.sync()

    async def close(self):
        await self.http.close()
        mongo.close()
        await super().close()

bot = ClashBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} | shards={bot.shard_count}")

async def cr_get(endpoint: str):
    key = f"cr:{endpoint}"
    if redis_client:
        cached = redis_client.get(key)
        if cached:
            import json
            return json.loads(cached)

    async with bot.http.get(f"{CR_API_BASE}{endpoint}") as resp:
        if resp.status == 200:
            data = await resp.json()
            if redis_client:
                import json
                redis_client.setex(key, 300, json.dumps(data))
            return data
        return None

def get_player_id(discord_id: int):
    doc = users.find_one({"_id": discord_id})
    return doc["player_id"] if doc else None

def normalize(tag):
    return tag.replace("#", "").upper()

bot.run(DISCORD_TOKEN)\n