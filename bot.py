import os
from dotenv import load_dotenv
from keep_alive import keep_alive

# Load the secret .env file
load_dotenv()

# Start the web server
keep_alive()

import discord
from discord.ext import commands

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')

# SECURE LOGIN (Reads from the .env file)
token = os.getenv('DISCORD_TOKEN')
bot.run(token)