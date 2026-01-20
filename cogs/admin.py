import os, requests
from discord.ext import commands
from pymongo import MongoClient

class Admin(commands.Cog):
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

    async def is_leader(self, discord_id):
        # 1. Get linked tag from DB (ensure ID is string)
        user_data = self.users.find_one({"_id": str(discord_id)})
        if not user_data:
            return False
        
        # 2. Fetch player profile to check role
        player_tag = user_data["player_id"].replace("#", "%23")
        url = f"{self.api_base}/players/{player_tag}"
        resp = requests.get(url, headers=self.get_headers())
        
        if resp.status_code == 200:
            data = resp.json()
            # Check if role is leader or coLeader
            return data.get("role") in ("leader", "coLeader")
        return False

    @commands.command()
    async def nudge(self, ctx):
        """List players who haven't used all 4 decks."""
        # 1. Permission Check
        if not await self.is_leader(ctx.author.id):
            await ctx.send("❌ **Access Denied:** You must be a Leader or Co-Leader to use this.")
            return

        # 2. Find the clan tag (using the leader's linked account)
        user_data = self.users.find_one({"_id": str(ctx.author.id)})
        if not user_data:
            await ctx.send("❌ You need to !link your account first.")
            return

        player_tag = user_data["player_id"].replace("#", "%23")
        
        # Fetch profile to get clan tag
        p_url = f"{self.api_base}/players/{player_tag}"
        p_resp = requests.get(p_url, headers=self.get_headers())
        if p_resp.status_code != 200 or "clan" not in p_resp.json():
            await ctx.send("❌ Could not find your clan.")
            return
            
        clan_tag = p_resp.json()["clan"]["tag"].replace("#", "%23")

        # 3. Fetch War Data
        w_url = f"{self.api_base}/clans/{clan_tag}/currentriverrace"
        w_resp = requests.get(w_url, headers=self.get_headers())
        
        if w_resp.status_code != 200:
            await ctx.send("❌ Failed to fetch war data.")
            return

        # 4. Find Slackers
        data = w_resp.json()
        participants = data.get("clan", {}).get("participants", [])
        slacking = []

        for p in participants:
            decks = p['decksUsed']
            if decks < 4:
                slacking.append(f"**{p['name']}**: {decks}/4")

        # 5. Send Report
        if slacking:
            msg = "⚠️ **Attacks Remaining Today:**\n" + "\n".join(slacking)
            # Split message if it exceeds Discord's 2000 char limit
            if len(msg) > 1900:
                msg = msg[:1900] + "\n...(list truncated)"
            await ctx.send(msg)
        else:
            await ctx.send("🎉 **Perfect!** Everyone has used all 4 decks!")

async def setup(bot):
    await bot.add_cog(Admin(bot))
