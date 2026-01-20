import os
import discord
from discord.ext import commands
from pymongo import MongoClient

# --- CONFIGURATION ---
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")

# --- DATABASE CONNECTION ---
if not MONGO_URL:
    print("⚠️ ERROR: MONGO_URL not found in environment variables!")
    cluster = None
    collection = None
else:
    # Connect to MongoDB Atlas
    cluster = MongoClient(MONGO_URL)
    db = cluster["ClashBotDB"]      # Your database name
    collection = db["users"]        # Your collection (table) name
    print("✅ Connected to MongoDB!")

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- DATABASE FUNCTIONS ---
def get_player_id(discord_id):
    if collection is None: return None
    # Look for the user in the database
    data = collection.find_one({"_id": str(discord_id)})
    if data:
        return data["player_id"]
    return None

def save_player_id(discord_id, player_id):
    if collection is None: return
    # Update if they exist, Insert if they are new (upsert=True)
    collection.update_one(
        {"_id": str(discord_id)}, 
        {"$set": {"player_id": player_id}}, 
        upsert=True
    )

# --- COMMANDS ---

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

@bot.command()
async def link(ctx, player_id: str):
    """
    Links your Discord account to a game Player ID permanently.
    Usage: !link <player_id>
    """
    # Clean the ID (uppercase, remove #)
    clean_id = player_id.upper().replace("#", "")
    
    # Save to database
    save_player_id(ctx.author.id, clean_id)
    
    await ctx.send(f"✅ **Saved!** Linked {ctx.author.name} to Player ID: `#{clean_id}`")

@bot.command()
async def myid(ctx):
    """Checks your linked ID."""
    player_id = get_player_id(ctx.author.id)
    
    if player_id:
        await ctx.send(f"Your linked Player ID is: `#{player_id}`")
    else:
        await ctx.send("You haven't linked an ID yet! Use `!link <id>`")

@bot.command()
async def whois(ctx, member: discord.Member):
    """See someone else's linked ID."""
    player_id = get_player_id(member.id)
    
    if player_id:
        await ctx.send(f"👤 **{member.name}** is linked to: `#{player_id}`")
    else:
        await ctx.send(f"❌ **{member.name}** hasn't linked an ID yet.")

# --- RUN BOT ---
bot.run(TOKEN)
