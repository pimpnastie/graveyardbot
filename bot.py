
from keep_alive import keep_alive
keep_alive()
import discord
from discord.ext import commands

# This permissions setup lets the bot read messages
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')

@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')

# REPLACE THE TEXT BELOW WITH YOUR ACTUAL TOKEN
bot.run('MTQ2MjkwMzM2ODY1Njg4Mzk0OQ.GJ2syI.9iMjzLiMlTvGlbwmgk8KmeNcEJNd-YYVYooSRQ')