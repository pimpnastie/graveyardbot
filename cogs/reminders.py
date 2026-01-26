import asyncio
import logging
import discord
from discord.ext import commands, tasks

class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.guilds = self.db["guilds"]
        self.log = logging.getLogger("clashbot")
        self.loop.start()

    def cog_unload(self):
        self.loop.cancel()

    async def _fetch_guilds_list(self):
        loop = asyncio.get_running_loop()
        def blocking():
            return list(self.guilds.find())
        return await loop.run_in_executor(None, blocking)

    @commands.hybrid_command(name="setreminders")
    @commands.has_permissions(manage_guild=True)
    async def setreminders(self, ctx, channel: discord.TextChannel):
        loop = asyncio.get_running_loop()
        def blocking_upsert():
            return self.guilds.update_one(
                {"_id": str(ctx.guild.id)},
                {"$set": {"channel_id": channel.id}},
                upsert=True
            )
        await loop.run_in_executor(None, blocking_upsert)
        await ctx.reply(f"✅ War reminders will now be sent to {channel.mention} every 12 hours.", mention_author=False)

    @commands.hybrid_command(name="stopreminders")
    @commands.has_permissions(manage_guild=True)
    async def stopreminders(self, ctx):
        loop = asyncio.get_running_loop()
        def blocking_delete():
            return self.guilds.delete_one({"_id": str(ctx.guild.id)})
        result = await loop.run_in_executor(None, blocking_delete)
        if getattr(result, "deleted_count", 0) > 0:
            await ctx.reply("🔕 War reminders stopped.", mention_author=False)
        else:
            await ctx.reply("❌ No reminders were set.", mention_author=False)

    @commands.hybrid_command(name="testreminders")
    async def testreminders(self, ctx):
        await ctx.reply("⚔️ **Reminder:** Use your war attacks! (Test successful)", mention_author=False)

    @tasks.loop(hours=12)
    async def loop(self):
        guild_rows = await self._fetch_guilds_list()
        for g in guild_rows:
            if "channel_id" in g:
                try:
                    channel_id = g["channel_id"]
                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        try:
                            channel = await self.bot.fetch_channel(channel_id)
                        except Exception:
                            continue
                    if channel:
                        try:
                            await channel.send("⚔️ **Reminder:** Use your war attacks! The river race is active.")
                        except Exception:
                            self.log.exception("Failed to send reminder to channel %s", channel_id)
                    await asyncio.sleep(1)  # small pause to avoid mass-sends
                except Exception:
                    self.log.exception("Failed to process guild reminder")

    @loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Reminders(bot))
