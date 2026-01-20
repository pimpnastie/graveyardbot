from discord.ext import commands, tasks
from bot import guilds

class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.loop.start()

    @tasks.loop(hours=12)
    async def loop(self):
        for g in guilds.find():
            channel = self.bot.get_channel(g["channel_id"])
            if channel:
                await channel.send("⚔️ Reminder: Use your war attacks!")

async def setup(bot):
    await bot.add_cog(Reminders(bot))
