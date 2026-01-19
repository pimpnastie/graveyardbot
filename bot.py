import os
import discord
import clashroyale
from discord.ext import commands
from dotenv import load_dotenv
from keep_alive import keep_alive

load_dotenv()

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CR_TOKEN = os.getenv('CR_TOKEN')

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    # 1. We connect to Clash Royale HERE (inside on_ready)
    # We attach it to 'bot' so we can use it elsewhere
    bot.cr = clashroyale.official_api.Client(token=CR_TOKEN, is_async=True, url="https://proxy.royaleapi.dev/v1")
    print(f'Logged in as {bot.user}!')

# --- COMMANDS ---

@bot.command()
async def player(ctx, tag):
    """Get player stats by tag. Usage: !player #TAG"""
    tag = tag.strip('#').upper()
    
    try:
        # 2. Note the change here: we use 'bot.cr' instead of 'cr'
        profile = await bot.cr.get_player(tag)
        
        embed = discord.Embed(title=f"👑 {profile.name}", color=0xFFAA00)
        embed.add_field(name="Trophies", value=f"🏆 {profile.trophies}", inline=True)
        embed.add_field(name="Best Trophies", value=f"🏅 {profile.best_trophies}", inline=True)
        embed.add_field(name="Level", value=f"⭐ {profile.exp_level}", inline=True)
        embed.add_field(name="Arena", value=profile.arena.name, inline=False)
        
        await ctx.send(embed=embed)
        
    except clashroyale.NotFoundError:
        await ctx.send("❌ Player not found! Check the tag.")
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")

keep_alive()
bot.run(DISCORD_TOKEN)