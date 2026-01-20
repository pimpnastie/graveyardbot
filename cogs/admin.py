from discord.ext import commands
from bot import cr_get, get_player_id

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def is_leader(self, discord_id):
        pid = get_player_id(discord_id)
        if not pid:
            return False
        player = await cr_get(f"/players/%23{pid}")
        return player.get("role") in ("leader", "coLeader")

    @commands.command()
    async def nudge(self, ctx):
        if not await self.is_leader(ctx.author.id):
            await ctx.send("❌ Leader / Co-Leader only.")
            return
        await ctx.send("⚠️ War nudge sent (logic ready).")

async def setup(bot):
    await bot.add_cog(Admin(bot))\n