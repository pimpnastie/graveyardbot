import os, json, csv, io, asyncio
import discord
from datetime import datetime, timedelta
from collections import Counter
from discord.ext import commands
from pymongo import MongoClient

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Connect to DB
        self.mongo = MongoClient(os.getenv("MONGO_URL"))
        self.db = self.mongo["ClashBotDB"]
        self.users = self.db["users"]
        self.history = self.db["clan_history"]

        self.api_base = "https://proxy.royaleapi.dev/v1"

    async def get_clan_tag(self, ctx):
        """Helper to get the clan tag of the command sender."""
        user_data = self.users.find_one({"_id": str(ctx.author.id)})
        if not user_data:
            return None
        
        clean_tag = user_data["player_id"].replace("#", "")
        url = f"{self.api_base}/players/%23{clean_tag}"
        
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200: return None
            data = await resp.json()
            return data.get("clan", {}).get("tag", "").replace("#", "")

    async def is_leader(self, discord_id):
        """Checks if the user is a Leader/Co-Leader via live API request."""
        user_data = self.users.find_one({"_id": str(discord_id)})
        if not user_data: return False

        clean_tag = user_data["player_id"].replace("#", "")
        url = f"{self.api_base}/players/%23{clean_tag}"
        
        async with self.bot.http_session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("role") in ("leader", "coLeader")
        return False

    # --- NEW COMMANDS ---

    @commands.command()
    async def whohas(self, ctx, *, card_name: str):
        """Find clan members who have a specific card (for trading)."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            await ctx.send("❌ Link your account and join a clan first.")
            return

        await ctx.send(f"🔍 Searching clan for **{card_name}**... (This takes a moment)")

        # 1. Get all members
        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        async with self.bot.http_session.get(c_url) as resp:
            clan_data = await resp.json()
        
        members = clan_data.get("memberList", [])
        hits = []

        # 2. Scan top 15 members to avoid hitting rate limits too hard
        # (Scanning all 50 takes too long and might timeout)
        scan_count = 0
        for member in members[:15]: 
            tag = member['tag'].replace("#", "")
            p_url = f"{self.api_base}/players/%23{tag}"
            
            async with self.bot.http_session.get(p_url) as p_resp:
                if p_resp.status == 200:
                    p_data = await p_resp.json()
                    for card in p_data.get("cards", []):
                        if card['name'].lower() == card_name.lower():
                            # Calculate max level (default is usually 14 or 15 now)
                            # RoyaleAPI returns 'level' as 1-based index from card rarity start
                            # Simplified: We just show the raw level or "Max"
                            hits.append(f"**{member['name']}**: Lvl {card.get('level', '?') + (13 - card.get('maxLevel', 13)) + 1}")
                            break
            scan_count += 1
            await asyncio.sleep(0.1) # Be nice to the API

        if hits:
            msg = f"🃏 **Found {card_name} Owners (Top 15 checked):**\n" + "\n".join(hits)
            await ctx.send(msg)
        else:
            await ctx.send(f"❌ Could not find high-level **{card_name}** in the top 15 members.")

    @commands.command()
    async def forecast(self, ctx):
        """Predicts if the clan will finish the race today."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag: return

        url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        async with self.bot.http_session.get(url) as resp:
            data = await resp.json()

        clan = data.get("clan", {})
        fame = clan.get("fame", 0)
        period_type = data.get("periodType") # 'training' or 'warDay'

        if period_type == "training":
            await ctx.send("😴 **Training Day:** No fame to forecast. Relax!")
            return

        # Simple Linear Projection
        # Logic: Assuming roughly 10,000 fame goal for a finish
        GOAL = 10000 
        if fame >= GOAL:
            await ctx.send("🎉 **Race Finished!** We already crossed the finish line!")
            return

        remaining = GOAL - fame
        # Naive estimate: Active players usually get ~1000 fame per 4 decks
        decks_used = sum(p['decksUsed'] for p in clan.get("participants", []))
        avg_fame_per_deck = fame / decks_used if decks_used > 0 else 0

        if avg_fame_per_deck > 0:
            decks_needed = int(remaining / avg_fame_per_deck)
            await ctx.send(f"🔮 **War Forecast:**\n🏁 Current Fame: `{fame}/{GOAL}`\n🚀 Remaining: `{remaining}`\n🃏 Est. Decks Needed: `{decks_needed}`\n\n*Get those attacks in!*")
        else:
            await ctx.send("📉 Not enough data to forecast yet.")

    @commands.command()
    async def scout(self, ctx):
        """Analyzes recent battles to show the current Meta."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag: return

        await ctx.send("🛡️ **Scouting Opponents...** (Analyzing last 50 battles)")

        # Get participants
        url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        async with self.bot.http_session.get(url) as resp:
            data = await resp.json()

        # Pick top 5 active players to analyze their logs
        top_players = sorted(data.get("clan", {}).get("participants", []), key=lambda x: x['decksUsed'], reverse=True)[:5]
        
        opponent_cards = []

        for p in top_players:
            tag = p['tag'].replace("#", "")
            b_url = f"{self.api_base}/players/%23{tag}/battlelog"
            async with self.bot.http_session.get(b_url) as b_resp:
                if b_resp.status == 200:
                    logs = await b_resp.json()
                    for battle in logs[:10]: # Check last 10 battles per player
                        opp = battle.get("opponent", [{}])[0]
                        for card in opp.get("cards", []):
                            opponent_cards.append(card['name'])
            await asyncio.sleep(0.1)

        # Find most common
        most_common = Counter(opponent_cards).most_common(5)
        
        if most_common:
            msg = "⚠️ **Meta Report (Most Common Opponent Cards):**\n"
            for card, count in most_common:
                msg += f"🔥 **{card}** (seen {count} times)\n"
            msg += "\n*Suggestion: Build decks to counter these!*"
            await ctx.send(msg)
        else:
            await ctx.send("❌ Could not analyze battles.")

    @commands.command()
    async def primetime(self, ctx):
        """Shows the hour (UTC) when the clan is most active."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag: return

        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        async with self.bot.http_session.get(c_url) as resp:
            data = await resp.json()

        hours = []
        for member in data.get("memberList", []):
            if "lastSeen" in member:
                # Format: 20231025T103000.000Z
                try:
                    ls = member['lastSeen']
                    dt = datetime.strptime(ls, "%Y%m%dT%H%M%S.%fZ")
                    hours.append(dt.hour)
                except: pass
        
        if not hours:
            await ctx.send("❌ No activity data available.")
            return

        peak_hour, count = Counter(hours).most_common(1)[0]
        await ctx.send(f"🕒 **Prime Time:** Your clan is most active around **{peak_hour}:00 UTC** ({count} members last seen then).")

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def rolesync(self, ctx):
        """Syncs Discord Roles with Clash Royale Clan Roles (Member/Elder/Co-Leader)."""
        if not await self.is_leader(ctx.author.id):
            await ctx.send("❌ Leaders only.")
            return

        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag: return

        await ctx.send("🔄 **Syncing Roles...**")

        # Fetch clan members
        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        async with self.bot.http_session.get(c_url) as resp:
            clan_data = await resp.json()
        
        # Map CR roles to typical Discord Role names
        role_map = {
            "member": discord.utils.get(ctx.guild.roles, name="Member"),
            "elder": discord.utils.get(ctx.guild.roles, name="Elder"),
            "coLeader": discord.utils.get(ctx.guild.roles, name="Co-Leader"),
            "leader": discord.utils.get(ctx.guild.roles, name="Leader")
        }

        # Check if roles exist in server
        if not all(role_map.values()):
            await ctx.send("⚠️ **Setup Error:** I could not find roles named `Member`, `Elder`, `Co-Leader`, or `Leader` in this server. Please create them exactly like that first.")
            return

        changes = 0
        
        # Iterate over all linked users in DB
        for user_doc in self.users.find():
            discord_id = int(user_doc["_id"])
            player_tag = user_doc["player_id"]
            
            # Find this user in the Discord Server
            member = ctx.guild.get_member(discord_id)
            if not member: continue 

            # Find this user in the Clan Member List
            cr_member = next((m for m in clan_data.get("memberList", []) if m["tag"] == "#" + player_tag.replace("#","")), None)
            
            if cr_member:
                cr_role_name = cr_member["role"] # member, elder, coLeader, leader
                target_role = role_map.get(cr_role_name)
                
                # Assign logic: Remove other rank roles, add new one
                if target_role and target_role not in member.roles:
                    # Remove all other rank roles first
                    await member.remove_roles(*[r for r in role_map.values() if r in member.roles])
                    # Add new role
                    await member.add_roles(target_role)
                    changes += 1
            
        await ctx.send(f"✅ **Sync Complete:** Updated roles for **{changes}** users.")

    # --- EXISTING COMMANDS (UNCHANGED) ---

    @commands.command()
    async def audit(self, ctx, option: str = None):
        """Identify inactive players (Chat Report or CSV)."""
        if not await self.is_leader(ctx.author.id):
            await ctx.send("❌ Access Denied.")
            return

        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            await ctx.send("❌ Link your account first.")
            return

        # Parallel Fetch
        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        w_url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        
        async with self.bot.http_session.get(c_url) as c_resp, \
                   self.bot.http_session.get(w_url) as w_resp:
            
            if c_resp.status != 200 or w_resp.status != 200:
                await ctx.send("❌ API Error.")
                return 
            clan_data = await c_resp.json()
            war_data = await w_resp.json()

        war_participants = {p['tag']: p['decksUsed'] for p in war_data.get("clan", {}).get("participants", [])}

        if option and option.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Name", "Tag", "Role", "Donations", "War Decks", "Days Offline", "Last Seen"])
            
            for m in clan_data.get("memberList", []):
                days_off = 0
                if "lastSeen" in m:
                    try:
                        dt = datetime.strptime(m['lastSeen'], "%Y%m%dT%H%M%S.%fZ")
                        days_off = (datetime.utcnow() - dt).days
                    except: pass
                
                writer.writerow([
                    m['name'], m['tag'], m['role'], m['donations'],
                    war_participants.get(m['tag'], 0), days_off, m.get('lastSeen', '')
                ])
            
            output.seek(0)
            fname = f"Audit_{datetime.utcnow().strftime('%Y-%m-%d')}.csv"
            await ctx.send("📊 **Report Ready:**", file=discord.File(fp=output, filename=fname))
            return

        # Chat Report
        candidates = []
        for m in clan_data.get("memberList", []):
            issues = []
            if m['donations'] == 0: issues.append("📦 No Donations")
            if war_participants.get(m['tag'], 0) < 4: issues.append(f"⚔️ War {war_participants.get(m['tag'], 0)}/4")
            
            days_off = 0
            if "lastSeen" in m:
                try:
                    dt = datetime.strptime(m['lastSeen'], "%Y%m%dT%H%M%S.%fZ")
                    days_off = (datetime.utcnow() - dt).days
                except: pass
            
            if days_off >= 3: issues.append(f"💤 Offline {days_off}d")
            
            if len(issues) >= 2 or days_off > 7:
                candidates.append(f"🔴 **{m['name']}** ({m['role']}): {', '.join(issues)}")

        msg = f"📋 **Audit Report** ({len(candidates)} flagged)\n\n" + "\n".join(candidates)
        if len(msg) > 1900: msg = msg[:1900] + "\n...(truncated)"
        await ctx.send(msg if candidates else "✅ No major issues found.")

    @commands.command()
    async def nudge(self, ctx):
        """List players who missed war attacks."""
        if not await self.is_leader(ctx.author.id):
            await ctx.send("❌ Access Denied.")
            return

        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag: return

        url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        async with self.bot.http_session.get(url) as resp:
            data = await resp.json()

        slacking = []
        for p in data.get("clan", {}).get("participants", []):
            if p['decksUsed'] < 4:
                slacking.append(f"**{p['name']}**: {p['decksUsed']}/4")

        msg = "⚠️ **Missed Attacks:**\n" + "\n".join(slacking)
        await ctx.send(msg[:1900] if slacking else "🎉 **Perfect!** All decks used.")

    @commands.command()
    async def announce(self, ctx, *, message):
        if not await self.is_leader(ctx.author.id): return
        try: await ctx.message.delete()
        except: pass
        embed = discord.Embed(description=message, color=0xe74c3c)
        embed.set_author(name=f"📢 {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command()
    @commands.is_owner()
    async def set_activity(self, ctx, *, text):
        await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=text))
        await ctx.send(f"✅ Set status: {text}")

    @commands.command()
    async def import_history(self, ctx):
        if not await self.is_leader(ctx.author.id): return
        if not ctx.message.attachments: return
        att = ctx.message.attachments[0]
        try:
            data = await att.read()
            records = []
            if att.filename.endswith(".json"):
                j = json.loads(data)
                records = j if isinstance(j, list) else j.get("items", [j])
            elif att.filename.endswith(".csv"):
                records = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
            
            if records:
                for r in records: r["imported_at"] = datetime.utcnow()
                self.history.insert_many(records)
                await ctx.send(f"✅ Imported {len(records)} records.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

async def setup(bot):
    await bot.add_cog(Admin(bot))
