import os
from discord.ext import commands
from pymongo import MongoClient

class War(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Connect to DB
        self.mongo = MongoClient(os.getenv("MONGO_URL"))
        self.db = self.mongo["ClashBotDB"]
        self.users = self.db["users"]
        self.api_base = "https://proxy.royaleapi.dev/v1"

    @commands.command()
    async def war(self, ctx, tag: str = None):
        """Check River Race status."""
        target_tag = tag

        # 1. Resolve the Tag (DB Lookup)
        if not target_tag:
            user_data = self.users.find_one({"_id": str(ctx.author.id)})
            
            if not user_data:
                await ctx.send("❌ Link your account first using `!link #TAG`.")
                return
            
            # FIX: Force the %23 prefix for the API
            # We strip any existing '#' just in case, then add '%23'
            clean_player_tag = user_data["player_id"].replace("#", "")
            url = f"{self.api_base}/players/%23{clean_player_tag}"
            
            async with self.bot.http_session.get(url) as resp:
                if resp.status != 200:
                    await ctx.send(f"❌ API Error: {resp.status} (Player Lookup)")
                    return
                p_data = await resp.json()
            
            if "clan" not in p_data:
                await ctx.send("❌ You are not in a clan!")
                return
            target_tag = p_data["clan"]["tag"]

        # 2. Fetch War Data
        # FIX: Same force prefix here for the clan tag
        clean_clan_tag = target_tag.replace("#", "")
        url = f"{self.api_base}/clans/%23{clean_clan_tag}/currentriverrace"
        
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200:
                await ctx.send(f"❌ API Error: {resp.status} (War Data)")
                return
            data = await resp.json()

        # 3. Parse & Send
        state = data.get("state", "Unknown")
        clan_name = data.get("clan", {}).get("name", "Unknown")
        fame = data.get("clan", {}).get("fame", 0)
        
        participants = data.get("clan", {}).get("participants", [])
        active = sum(1 for p in participants if p['decksUsed'] > 0)
        
        msg = (
            f"⚔️ **{clan_name}**\n"
            f"**State:** {state}\n"
            f"**Fame:** {fame}\n"
            f"**Active:** {active}/{len(participants)}"
        )
        await ctx.send(msg)

async def setup(bot):
    await bot.add_cog(War(bot))
