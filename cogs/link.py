from discord.ext import commands
from bot import users, normalize

class Link(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def link(self, ctx, tag: str):
        users.update_one(
            {"_id": ctx.author.id},
            {"$set": {"player_id": normalize(tag)}},
            upsert=True
        )
        await ctx.send(f"✅ Linked to #{normalize(tag)}")

async def setup(bot):
    await bot.add_cog(Link(bot))\n