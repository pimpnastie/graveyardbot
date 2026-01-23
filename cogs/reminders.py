import discord
from discord.ext import commands, tasks

class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ✅ USE SHARED DB
        self.db = bot.db
        self.guilds = self.db["guilds"]
        
        # Start the loop
        self.loop.start()

    def cog_unload(self):
        self.loop.cancel()

    # --- ⚙️ CONFIGURATION COMMANDS ---

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def setreminders(self, ctx, channel: discord.TextChannel):
        """Sets the channel for automatic war reminders."""
        self.guilds.update_one(
            {"_id": str(ctx.guild.id)},
            {"$set": {"channel_id": channel.id}},
            upsert=True
        )
        await ctx.send(f"✅ War reminders will now be sent to {channel.mention} every 12 hours.")

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def stopreminders(self, ctx):
        """Stops war reminders for this server."""
        result = self.guilds.delete_one({"_id": str(ctx.guild.id)})
        if result.deleted_count > 0:
            await ctx.send("🔕 War reminders stopped.")
        else:
            await ctx.send("❌ No reminders were set.")

    @commands.command()
    async def testreminders(self, ctx):
        """Test the reminder message immediately."""
        await ctx.send("⚔️ **Reminder:** Use your war attacks! (Test successful)")

    # --- 🔄 BACKGROUND LOOP ---

    @tasks.loop(hours=12)
    async def loop(self):
        # Iterate over all guilds in the DB
        for g in self.guilds.find():
            if "channel_id" in g:
                try:
                    channel_id = g["channel_id"]
                    channel = self.bot.get_channel(channel_id)
                    
                    # If channel is not in cache, try to fetch it (rare case)
                    if not channel:
                        try:
                            channel = await self.bot.fetch_channel(channel_id)
                        except:
                            continue # Channel deleted or bot kicked

                    if channel:
                        await channel.send("⚔️ **Reminder:** Use your war attacks! The river race is active.")
                except Exception as e:
                    print(f"Failed to send reminder to guild {g['_id']}: {e}")

    @loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Reminders(bot))
