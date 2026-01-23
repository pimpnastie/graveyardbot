import discord
from discord.ext import commands

class War(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ✅ USE SHARED RESOURCES
        self.db = bot.db
        self.users = bot.db_users
        self.redis = bot.redis
        self.api_base = "https://proxy.royaleapi.dev/v1"

    async def get_clan_tag(self, ctx):
        """Helper to get the clan tag with Redis Caching."""
        discord_id = str(ctx.author.id)
        
        # 1. Check Redis Cache First
        if self.redis:
            cached_tag = self.redis.get(f"clan_tag:{discord_id}")
            if cached_tag:
                return cached_tag

        # 2. Check MongoDB
        user_data = self.users.find_one({"_id": discord_id})
        if not user_data:
            return None
        
        clean_tag = user_data["player_id"].replace("#", "")
        url = f"{self.api_base}/players/%23{clean_tag}"
        
        # 3. Fetch from API
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200: return None
            data = await resp.json()
            clan_tag = data.get("clan", {}).get("tag", "").replace("#", "")
            
            # 4. Save to Redis (Cache for 1 hour)
            if clan_tag and self.redis:
                self.redis.setex(f"clan_tag:{discord_id}", 3600, clan_tag)
                
            return clan_tag

    @commands.command()
    async def race(self, ctx, option: str = None):
        """Detailed River Race stats. Usage: !race or !race last"""
        # 1. Get Clan Tag (Cached)
        clean_clan_tag = await self.get_clan_tag(ctx)
        if not clean_clan_tag:
            return await ctx.send("❌ Link your account and join a clan first.")

        # 2. Fetch War Data
        current_url = f"{self.api_base}/clans/%23{clean_clan_tag}/currentriverrace"
        
        participants = []
        clan_name = "Unknown"
        header_text = "War Report"
        fetch_last_war = False
        
        if option and option.lower() == "last":
            fetch_last_war = True
        else:
            async with self.bot.http_session.get(current_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    state = data.get("state")
                    if state == "active":
                        clan_name = data.get("clan", {}).get("name", "Unknown")
                        participants = data.get("clan", {}).get("participants", [])
                    else:
                        fetch_last_war = True 

        if fetch_last_war:
            log_url = f"{self.api_base}/clans/%23{clean_clan_tag}/riverracelog?limit=1"
            async with self.bot.http_session.get(log_url) as log_resp:
                if log_resp.status == 200:
                    log_data = await log_resp.json()
                    if log_data.get("items"):
                        last_war = log_data["items"][0]
                        header_text = f"Last War Report (Season {last_war.get('seasonId')})"
                        
                        for standing in last_war.get("standings", []):
                            c = standing.get("clan", {})
                            if c.get("tag") == "#" + clean_clan_tag: # Add # back for comparison
                                clan_name = c.get("name")
                                participants = c.get("participants", [])
                                break
                        
                        if option and option.lower() == "last":
                            await ctx.send(f"📅 **Showing Previous War Results**")
                        else:
                            await ctx.send(f"⚠️ **No active war.** Showing results from last race.")

        if not participants:
            return await ctx.send("❌ No war data found (Clan might be inactive).")

        # 3. Sort Participants
        deck_lists = {0: [], 1: [], 2: [], 3: [], 4: []}
        for p in participants:
            d = p['decksUsed']
            d = 4 if d > 4 else d
            deck_lists[d].append(p['name'])
            
        sorted_p = sorted(participants, key=lambda x: x['fame'], reverse=True)[:5]

        # 4. Build Message
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

        if len(msg) > 2000: msg = msg[:1900] + "\n...(truncated)"
        await ctx.send(msg)

    @commands.command()
    async def war(self, ctx, tag: str = None):
        """Check River Race status."""
        target_tag = tag

        # 1. Resolve Tag if not provided
        if not target_tag:
            clean_tag = await self.get_clan_tag(ctx)
            if not clean_tag:
                return await ctx.send("❌ Link your account first.")
            target_tag = clean_tag

        # 2. Fetch War Data
        clean_clan_tag = target_tag.replace("#", "")
        url = f"{self.api_base}/clans/%23{clean_clan_tag}/currentriverrace"
        
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200:
                return await ctx.send(f"❌ API Error: {resp.status}")
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
