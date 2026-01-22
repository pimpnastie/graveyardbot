import os, json, csv, io
import discord
from datetime import datetime
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

    async def is_leader(self, discord_id):
        """Checks if the user is a Leader/Co-Leader via live API request."""
        user_data = self.users.find_one({"_id": str(discord_id)})
        if not user_data:
            return False

        # FIX: Force the %23 prefix so the API accepts the tag
        clean_tag = user_data["player_id"].replace("#", "")
        url = f"{self.api_base}/players/%23{clean_tag}"
        
        async with self.bot.http_session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("role") in ("leader", "coLeader")
        
        return False

    @commands.command()
    async def audit(self, ctx, option: str = None):
        """
        Identify inactive players. 
        Usage: !audit (Chat Report) or !audit csv (Download Spreadsheet)
        """
        # 1. Permission & Clan Lookup
        if not await self.is_leader(ctx.author.id):
            await ctx.send("❌ **Access Denied:** Leaders/Co-Leaders only.")
            return

        user_data = self.users.find_one({"_id": str(ctx.author.id)})
        if not user_data:
            await ctx.send("❌ Link your account first.")
            return
        
        # FIX: Use the same correct tag logic here
        player_tag = user_data["player_id"].replace("#", "")
        url = f"{self.api_base}/players/%23{player_tag}"
        
        async with self.bot.http_session.get(url) as resp:
            p_data = await resp.json()
            if "clan" not in p_data:
                await ctx.send("❌ You are not in a clan.")
                return
            # Fix clan tag as well just in case
            clan_tag = p_data["clan"]["tag"].replace("#", "")
        
        # 2. Parallel Fetch: Clan Roster + Current War
        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        w_url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        
        async with self.bot.http_session.get(c_url) as c_resp, \
                   self.bot.http_session.get(w_url) as w_resp:
            
            if c_resp.status != 200 or w_resp.status != 200:
                await ctx.send("❌ API Error fetching clan data.")
                return
                
            clan_data = await c_resp.json()
            war_data = await w_resp.json()

        # 3. Process Data
        war_participants = {p['tag']: p['decksUsed'] for p in war_data.get("clan", {}).get("participants", [])}
        
        # If user wants CSV, generate full report for ALL members
        if option and option.lower() == "csv":
            # Setup CSV Buffer
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Header Row
            writer.writerow(["Name", "Tag", "Role", "Donations", "War Decks (Max 4)", "Days Offline", "Last Seen"])
            
            for member in clan_data.get("memberList", []):
                # Calculate Days Offline
                days_offline = 0
                last_seen_str = member.get('lastSeen', '')
                if last_seen_str:
                    try:
                        last_seen_dt = datetime.strptime(last_seen_str, "%Y%m%dT%H%M%S.%fZ")
                        days_offline = (datetime.utcnow() - last_seen_dt).days
                    except: pass
                
                # Write Row
                writer.writerow([
                    member['name'],
                    member['tag'],
                    member['role'],
                    member['donations'],
                    war_participants.get(member['tag'], 0),
                    days_offline,
                    last_seen_str
                ])
            
            output.seek(0)
            filename = f"ClanAudit_{datetime.utcnow().strftime('%Y-%m-%d')}.csv"
            await ctx.send(f"📊 **Here is the full clan export:**", file=discord.File(fp=output, filename=filename))
            return

        # 4. Standard Text Report (Only show flagged users)
        candidates = []
        for member in clan_data.get("memberList", []):
            issues = []
            
            # Check Donations
            if member['donations'] == 0:
                issues.append(f"📦 **Donations:** 0")

            # Check War
            w_decks = war_participants.get(member['tag'], 0)
            if w_decks < 4:
                issues.append(f"⚔️ **War:** {w_decks}/4")

            # Check Inactivity
            days_offline = 0
            try:
                last_seen_str = member.get('lastSeen', '')
                if last_seen_str:
                    last_seen_dt = datetime.strptime(last_seen_str, "%Y%m%dT%H%M%S.%fZ")
                    days_offline = (datetime.utcnow() - last_seen_dt).days
                    if days_offline >= 3:
                        issues.append(f"💤 **Offline:** {days_offline}d")
            except: pass

            # Flag if 2+ issues OR offline > 7 days
            if len(issues) >= 2 or days_offline > 7:
                candidates.append(
                    f"🔴 **{member['name']}** ({member['role']})\n" + 
                    "   " + " | ".join(issues)
                )

        if candidates:
            header = f"📋 **Audit Report** ({len(candidates)} flagged)\n*Use `!audit csv` for a full spreadsheet.*\n\n"
            msg = header + "\n".join(candidates)
            if len(msg) > 1900: msg = msg[:1900] + "\n...(truncated)"
            await ctx.send(msg)
        else:
            await ctx.send("✅ **Clean Sheet:** No obvious candidates found! (Use `!audit csv` for full data)")

    @commands.command()
    async def nudge(self, ctx):
        """List players who haven't used all 4 decks."""
        if not await self.is_leader(ctx.author.id):
            await ctx.send("❌ Access Denied.")
            return

        user_data = self.users.find_one({"_id": str(ctx.author.id)})
        
        # FIX: Use the same correct tag logic here
        player_tag = user_data["player_id"].replace("#", "")
        url = f"{self.api_base}/players/%23{player_tag}"
        
        async with self.bot.http_session.get(url) as resp:
            p_data = await resp.json()
            if "clan" not in p_data:
                await ctx.send("❌ You are not in a clan.")
                return
            clan_tag = p_data["clan"]["tag"].replace("#", "")

        # Use correct clan URL with %23
        w_url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        async with self.bot.http_session.get(w_url) as resp:
            data = await resp.json()

        slacking = []
        participants = data.get("clan", {}).get("participants", [])
        for p in participants:
            if p['decksUsed'] < 4:
                slacking.append(f"**{p['name']}**: {p['decksUsed']}/4")

        if slacking:
            msg = "⚠️ **Attacks Remaining Today:**\n" + "\n".join(slacking)
            if len(msg) > 1900: msg = msg[:1900] + "\n..."
            await ctx.send(msg)
        else:
            await ctx.send("🎉 **Perfect!** Everyone has used all 4 decks!")

    @commands.command()
    async def announce(self, ctx, *, message):
        """Send an official message as the bot."""
        if not await self.is_leader(ctx.author.id):
            await ctx.send("❌ Access Denied.")
            return

        try: await ctx.message.delete()
        except: pass
        
        embed = discord.Embed(description=message, color=0xe74c3c)
        embed.set_author(name=f"📢 Announcement from {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command()
    @commands.is_owner()
    async def set_activity(self, ctx, *, text):
        """Sets the bot's status."""
        await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=text))
        await ctx.send(f"✅ Status updated: **Watching {text}**")

    @commands.command()
    async def import_history(self, ctx):
        """Import RoyaleAPI history (JSON/CSV)."""
        if not await self.is_leader(ctx.author.id):
            await ctx.send("❌ Access Denied.")
            return
        
        if not ctx.message.attachments:
            await ctx.send("❌ Attach a JSON or CSV file.")
            return

        attachment = ctx.message.attachments[0]
        try:
            file_bytes = await attachment.read()
            records = []
            if attachment.filename.endswith(".json"):
                data = json.loads(file_bytes)
                records = data if isinstance(data, list) else data.get("items", [data])
            elif attachment.filename.endswith(".csv"):
                records = list(csv.DictReader(io.StringIO(file_bytes.decode("utf-8"))))
            
            if records:
                for r in records: r["imported_at"] = datetime.utcnow()
                self.history.insert_many(records)
                await ctx.send(f"✅ Imported **{len(records)}** records.")
            else:
                await ctx.send("⚠️ File was empty.")
        except Exception as e:
            await ctx.send(f"❌ Error: `{e}`")

async def setup(bot):
    await bot.add_cog(Admin(bot))
