import os, json, csv, io, asyncio
import discord
from datetime import datetime, timedelta
from collections import Counter
from discord.ext import commands

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ✅ USE SHARED DB (Fixes Issue #1)
        self.db = bot.db 
        self.users = bot.db_users
        self.history = self.db["clan_history"]
        self.redis = bot.redis # ✅ USE SHARED REDIS (Fixes Issue #2)

        self.api_base = "https://proxy.royaleapi.dev/v1"

    async def get_clan_tag(self, ctx):
        """Helper to get the clan tag (with Redis Caching)."""
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

    async def is_leader(self, discord_id):
        """Checks if the user is a Leader/Co-Leader."""
        # Optimization: We could cache this too, but for safety (permissions), 
        # we often prefer live data. Kept live for security.
        user_data = self.users.find_one({"_id": str(discord_id)})
        if not user_data: return False

        clean_tag = user_data["player_id"].replace("#", "")
        url = f"{self.api_base}/players/%23{clean_tag}"
        
        async with self.bot.http_session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("role") in ("leader", "coLeader")
        return False

    # --- COMMANDS ---

    @commands.command()
    async def whohas(self, ctx, *, card_name: str):
        """Find clan members who have a specific card."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            await ctx.send("❌ Link your account and join a clan first.")
            return

        await ctx.send(f"🔍 Searching clan for **{card_name}**... (Checking Top 15)")

        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        async with self.bot.http_session.get(c_url) as resp:
            if resp.status != 200: return await ctx.send("❌ Failed to fetch clan.")
            clan_data = await resp.json()
        
        members = clan_data.get("memberList", [])
        hits = []

        # Scan Top 15
        for member in members[:15]: 
            tag = member['tag'].replace("#", "")
            p_url = f"{self.api_base}/players/%23{tag}"
            
            async with self.bot.http_session.get(p_url) as p_resp:
                if p_resp.status == 200:
                    p_data = await p_resp.json()
                    for card in p_data.get("cards", []):
                        if card['name'].lower() == card_name.lower():
                            level = card.get('level', 1) + (13 - card.get('maxLevel', 13)) + 1
                            hits.append(f"**{member['name']}**: Lvl {level}")
                            break
            await asyncio.sleep(0.2) # Increased sleep to be safer

        if hits:
            msg = f"🃏 **Found {card_name} Owners:**\n" + "\n".join(hits)
            await ctx.send(msg)
        else:
            await ctx.send(f"❌ Not found in Top 15 members.")

    @commands.command()
    async def forecast(self, ctx):
        """Predicts race finish."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag: return

        url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        async with self.bot.http_session.get(url) as resp:
            data = await resp.json()

        clan = data.get("clan", {})
        fame = clan.get("fame", 0)
        
        if data.get("periodType") == "training":
            return await ctx.send("😴 **Training Day:** No forecast available.")

        GOAL = 10000 
        if fame >= GOAL:
            return await ctx.send("🎉 **Race Finished!**")

        remaining = GOAL - fame
        decks_used = sum(p['decksUsed'] for p in clan.get("participants", []))
        avg_fame = fame / decks_used if decks_used > 0 else 0

        if avg_fame > 0:
            needed = int(remaining / avg_fame)
            await ctx.send(f"🔮 **Forecast:**\n🏁 Fame: `{fame}/{GOAL}`\n🚀 Left: `{remaining}`\n🃏 Est. Decks: `{needed}`")
        else:
            await ctx.send("📉 Not enough data.")

    @commands.command()
    async def scout(self, ctx):
        """Analyzes Top 5 active players' recent battles."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag: return

        await ctx.send("🛡️ **Scouting Opponents...**")

        url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        async with self.bot.http_session.get(url) as resp:
            data = await resp.json()

        top_players = sorted(data.get("clan", {}).get("participants", []), key=lambda x: x['decksUsed'], reverse=True)[:5]
        opponent_cards = []

        for p in top_players:
            tag = p['tag'].replace("#", "")
            b_url = f"{self.api_base}/players/%23{tag}/battlelog"
            async with self.bot.http_session.get(b_url) as b_resp:
                if b_resp.status == 200:
                    logs = await b_resp.json()
                    for battle in logs[:10]:
                        opp = battle.get("opponent", [{}])[0]
                        for card in opp.get("cards", []):
                            opponent_cards.append(card['name'])
            await asyncio.sleep(0.2)

        most_common = Counter(opponent_cards).most_common(5)
        if most_common:
            msg = "⚠️ **Meta Report:**\n" + "\n".join([f"🔥 **{c}** ({n})" for c, n in most_common])
            await ctx.send(msg)
        else:
            await ctx.send("❌ Could not analyze battles.")

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def rolesync(self, ctx):
        """Syncs Discord Roles with Clan Roles."""
        if not await self.is_leader(ctx.author.id):
            return await ctx.send("❌ Leaders only.")

        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag: return

        await ctx.send("🔄 **Syncing Roles...**")

        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        async with self.bot.http_session.get(c_url) as resp:
            clan_data = await resp.json()
        
        role_map = {
            "member": discord.utils.get(ctx.guild.roles, name="Member"),
            "elder": discord.utils.get(ctx.guild.roles, name="Elder"),
            "coLeader": discord.utils.get(ctx.guild.roles, name="Co-Leader"),
            "leader": discord.utils.get(ctx.guild.roles, name="Leader")
        }

        if not all(role_map.values()):
            return await ctx.send("⚠️ Missing roles: Member, Elder, Co-Leader, or Leader.")

        changes = 0
        # Iterate linked users
        for user_doc in self.users.find():
            discord_id = int(user_doc["_id"])
            
            member = ctx.guild.get_member(discord_id)
            if not member: continue 

            cr_member = next((m for m in clan_data.get("memberList", []) if m["tag"] == "#" + user_doc["player_id"]), None)
            
            if cr_member:
                target_role = role_map.get(cr_member["role"])
                if target_role and target_role not in member.roles:
                    await member.remove_roles(*[r for r in role_map.values() if r in member.roles])
                    await member.add_roles(target_role)
                    changes += 1
            
        await ctx.send(f"✅ **Sync Complete:** Updated {changes} users.")

    @commands.command()
    async def audit(self, ctx, option: str = None):
        """Audit report."""
        if not await self.is_leader(ctx.author.id): return await ctx.send("❌ Access Denied.")
        clan_tag = await self.get_clan_tag(ctx)
        
        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        w_url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        
        async with self.bot.http_session.get(c_url) as c_r, self.bot.http_session.get(w_url) as w_r:
            clan = await c_r.json()
            war = await w_r.json()

        war_part = {p['tag']: p['decksUsed'] for p in war.get("clan", {}).get("participants", [])}

        if option == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Name", "Role", "Donations", "War Decks", "Last Seen"])
            for m in clan.get("memberList", []):
                writer.writerow([m['name'], m['role'], m['donations'], war_part.get(m['tag'], 0), m.get('lastSeen')])
            output.seek(0)
            return await ctx.send("📊 Report:", file=discord.File(fp=output, filename="Audit.csv"))

        # Chat Report
        issues = []
        for m in clan.get("memberList", []):
            if war_part.get(m['tag'], 0) < 4:
                issues.append(f"**{m['name']}**: {war_part.get(m['tag'], 0)}/4 War Decks")

        msg = "⚠️ **Audit (Low War):**\n" + "\n".join(issues[:20]) # Limit to 20 lines
        await ctx.send(msg if issues else "✅ Clan looks good!")

async def setup(bot):
    await bot.add_cog(Admin(bot))
