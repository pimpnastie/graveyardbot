import os, requests
from discord.ext import commands
from pymongo import MongoClient

class War(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Connect to DB directly
        self.mongo = MongoClient(os.getenv("MONGO_URL"))
        self.db = self.mongo["ClashBotDB"]
        self.users = self.db["users"]
        self.api_token = os.getenv("CR_TOKEN")
        self.api_base = "https://api.clashroyale.com/v1"

    def get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json"
        }

    @commands.command()
    async def war(self, ctx, tag: str = None):
        """Check River Race status."""
        target_tag = tag

        # If no tag provided, look up the linked user
        if not target_tag:
            # FIX: Look for STRING ID to match link.py
            user_data = self.users.find_one({"_id": str(ctx.author.id)})
            
            if not user_data:
                await ctx.send("❌ Link your account first using `!link #TAG`.")
                return
            
            # Fetch player profile to find their clan
            player_tag = user_data["player_id"].replace("#", "%23")
            url = f"{self.api_base}/players/{player_tag}"
            
            resp = requests.get(url, headers=self.get_headers())
            if resp.status_code != 200:
                await ctx.send("❌ Could not fetch your profile. API Error.")
                return
                
            p_data = resp.json()
            if "clan" not in p_data:
                await ctx.send("❌ You are not in a clan!")
                return
            target_tag = p_data["clan"]["tag"]

        # Fetch War Data
        safe_tag = target_tag.replace("#", "%23")
        url = f"{self.api_base}/clans/{safe_tag}/currentriverrace"
        response = requests.get(url, headers=self.get_headers())
        
        if response.status_code == 200:
            data = response.json()
            state = data.get("state", "Unknown")
            clan_name = data.get("clan", {}).get("name", "Unknown")
            fame = data.get("clan", {}).get("fame", 0)
            
            # Calculate active players
            participants = data.get("clan", {}).get("participants", [])
            active = sum(1 for p in participants if p['decksUsed'] > 0)
            
            msg = (
                f"⚔️ **{clan_name}**\n"
                f"**State:** {state}\n"
                f"**Fame:** {fame}\n"
                f"**Active:** {active}/{len(participants)}"
            )
            await ctx.send(msg)
        else:
            await ctx.send("❌ Could not fetch war data.")

async def setup(bot):
    await bot.add_cog(War(bot))
