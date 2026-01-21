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
    async def race(self, ctx):
        """Detailed River Race stats (Current or Last War)."""
        # 1. Resolve User's Clan Tag
        user_data = self.users.find_one({"_id": str(ctx.author.id)})
        if not user_data:
            await ctx.send("❌ Link your account first using `!link #TAG`.")
            return

        clean_player_tag = user_data["player_id"].replace("#", "")
        url = f"{self.api_base}/players/%23{clean_player_tag}"
        
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200:
                await ctx.send("❌ API Error (Player Lookup)")
                return
            p_data = await resp.json()
            if "clan" not in p_data:
                await ctx.send("❌ You are not in a clan!")
                return
            clan_tag = p_data["clan"]["tag"]

        # 2. Fetch War Data (Try Current First)
        clean_clan_tag = clan_tag.replace("#", "")
        current_url = f"{self.api_base}/clans/%23{clean_clan_tag}/currentriverrace"
        
        participants = []
        clan_name = "Unknown"
        header_text = "War Report"

        async with self.bot.http_session.get(current_url) as resp:
            if resp.status == 200:
                data = await resp.json()
                state = data.get("state")
                
                # If War is ACTIVE, use this data
                if state == "active":
                    clan_name = data.get("clan", {}).get("name", "Unknown")
                    participants = data.get("clan", {}).get("participants", [])
                else:
                    # War is NOT active (Training/Matchmaking) -> Fetch LOG
                    log_url = f"{self.api_base}/clans/%23{clean_clan_tag}/riverracelog?limit=1"
                    async with self.bot.http_session.get(log_url) as log_resp:
                        if log_resp.status == 200:
                            log_data = await log_resp.json()
                            if log_data.get("items"):
                                last_war = log_data["items"][0]
                                header_text = f"Last War Report (Season {last_war.get('seasonId')})"
                                
                                # Find our clan in the standings list
                                for standing in last_war.get("standings", []):
                                    c = standing.get("clan", {})
                                    if c.get("tag") == clan_tag:
                                        clan_name = c.get("name")
                                        participants = c.get("participants", [])
                                        break
                                
                                await ctx.send(f"⚠️ **No active war.** Showing results from last race.")

        if not participants:
            await ctx.send("❌ No war data found (Clan might be inactive).")
            return

        # 3. Sort Participants into Lists
        deck_lists = {0: [], 1: [], 2: [], 3: [], 4: []}
        
        for p in participants:
            d = p['decksUsed']
            d = 4 if d > 4 else d # Safety cap
            deck_lists[d].append(p['name'])
            
        # Sort Top Fame Earners
        sorted_p = sorted(participants, key=lambda x: x['fame'], reverse=True)[:5]

        # 4. Build the Message
        msg = f"📊 **{clan_name} {header_text}**\n\n"
        
        def format_list(label, names, emoji):
            if not names: return ""
            return f"{emoji} **{label} ({len(names)}):**\n`{', '.join(names)}`\n\n"

        msg += format_list("4/4 Decks (Perfect)", deck_lists[4], "✅")
        msg += format_list("3/4 Decks (Missed One)", deck_lists[3], "⚠️")
        msg += format_list("2/4 or 1/4 Decks", deck_lists[2] + deck_lists[1], "❌")
        msg += format_list("0/4 Decks (Sleeping)", deck_lists[0], "💤")

        msg += "**🏅 Top 5 Fame Leaders:**\n"
        for i, p in enumerate(sorted_p, 1):
            msg += f"`{i}.` **{p['name']}**: {p['fame']}\n"

        if len(msg) > 2000:
            msg = msg[:1900] + "\n...(message truncated)"
            
        await ctx.send(msg)

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
