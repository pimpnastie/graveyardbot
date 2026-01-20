import os
from discord.ext import commands, tasks
from pymongo import MongoClient

class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Connect to DB directly
        self.mongo = MongoClient(os.getenv("MONGO_URL"))
        self.db = self.mongo["ClashBotDB"]
        self.guilds = self.db["guilds"]
        
        # Start the loop
        self.loop.start()

    def cog_unload(self):
        self.loop.cancel()

    @tasks.loop(hours=12)
    async def loop(self):
        # Iterate over all guilds in the DB
        for g in self.guilds.find():
            # Ensure we have a channel_id
            if "channel_id" in g:
                channel = self.bot.get_channel(g["channel_id"])
                if channel:
                    try:
                        await channel.send("⚔️ **Reminder:** Use your war attacks!")
                    except Exception as e:
                        print(f"Failed to send reminder to channel {g['channel_id']}: {e}")

    @loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Reminders(bot))
