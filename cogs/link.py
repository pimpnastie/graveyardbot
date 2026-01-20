import os
from discord.ext import commands
from pymongo import MongoClient

class Link(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Connect to DB directly to avoid circular import crashes
        self.mongo = MongoClient(os.getenv("MONGO_URL"))
        self.db = self.mongo["ClashBotDB"]
        self.users = self.db["users"]

    @commands.command()
    async def link(self, ctx, tag: str):
        """Link your Discord to a Player ID."""
        # Clean the tag (remove # and uppercase)
        clean_tag = tag.upper().replace("#", "")
        
        # FIX: Save ID as a STRING so other commands can find it!
        self.users.update_one(
            {"_id": str(ctx.author.id)}, 
            {"$set": {"player_id": clean_tag}}, 
            upsert=True
        )
        await ctx.send(f"✅ Linked to #{clean_tag}")

async def setup(bot):
    await bot.add_cog(Link(bot))
