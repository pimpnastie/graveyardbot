import os
import discord
from discord.ext import commands
from pymongo import MongoClient

class Link(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_base = "https://proxy.royaleapi.dev/v1"
        
        # Connect to DB
        self.mongo = MongoClient(os.getenv("MONGO_URL"))
        self.db = self.mongo["ClashBotDB"]
        self.users = self.db["users"]

    # --- HELPER: Resolve Tag ---
    async def resolve_tag(self, ctx, tag):
        """Helper to get a clean tag from args or database."""
        if tag:
            return tag.upper().replace("#", "")
        
        user_data = self.users.find_one({"_id": str(ctx.author.id)})
        if user_data:
            return user_data["player_id"].replace("#", "")
        
        return None

    # --- COMMANDS ---

    @commands.command()
    async def link(self, ctx, tag: str):
        """Link your Discord to a Player ID."""
        clean_tag = tag.upper().replace("#", "")
        
        # Save as String
        self.users.update_one(
            {"_id": str(ctx.author.id)}, 
            {"$set": {"player_id": clean_tag}}, 
            upsert=True
        )
        await ctx.send(f"✅ Linked to **#{clean_tag}**")

    @commands.command(aliases=["profile"])
    async def stats(self, ctx, tag: str = None):
        """View comprehensive player stats."""
        clean_tag = await self.resolve_tag(ctx, tag)
        if not clean_tag:
            await ctx.send("❌ Link your account or provide a tag: `!stats #TAG`")
            return

        url = f"{self.api_base}/players/%23{clean_tag}"
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200:
                await ctx.send("❌ Could not fetch player stats.")
                return
            data = await resp.json()

        # Parse Data
        name = data.get("name")
        lvl = data.get("expLevel")
        trophies = data.get("trophies")
        best_trophies = data.get("bestTrophies")
        wins = data.get("wins")
        losses = data.get("losses")
        clan = data.get("clan", {}).get("name", "No Clan")
        arena = data.get("arena", {}).get("name", "Unknown Arena")

        embed = discord.Embed(title=f"{name} (Lvl {lvl})", color=0x3498db)
        embed.add_field(name="🏆 Trophies", value=f"{trophies} (Best: {best_trophies})", inline=True)
        embed.add_field(name="🛡️ Clan", value=clan, inline=True)
        embed.add_field(name="⚔️ W/L Ratio", value=f"{wins}/{losses}", inline=True)
        embed.add_field(name="🏟️ Arena", value=arena, inline=False)
        
        await ctx.send(embed=embed)

    @commands.command()
    async def chests(self, ctx, tag: str = None):
        """Check upcoming chest cycle."""
        clean_tag = await self.resolve_tag(ctx, tag)
        if not clean_tag:
            await ctx.send("❌ Link your account or provide a tag.")
            return

        url = f"{self.api_base}/players/%23{clean_tag}/upcomingchests"
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200:
                await ctx.send("❌ Could not fetch chests.")
                return
            data = await resp.json()

        items = data.get("items", [])
        
        msg = "**Upcoming Chests:**\n"
        # Next 3 chests
        for chest in items[:3]:
            msg += f"`+{chest['index'] + 1}` **{chest['name']}**\n"
            
        msg += "\n**Rare Chests:**\n"
        rares = ["Magical Chest", "Giant Chest", "Royal Wild Chest", "Mega Lightning Chest", "Legendary Chest"]
        found_rares = []
        
        for chest in items:
            if chest['name'] in rares:
                found_rares.append(f"{chest['name']} `+{chest['index'] + 1}`")
        
        msg += "\n".join(found_rares) if found_rares else "No rare chests nearby."
        await ctx.send(msg)

    @commands.command(aliases=["battles", "history"])
    async def log(self, ctx, tag: str = None):
        """View last 5 battle results."""
        clean_tag = await self.resolve_tag(ctx, tag)
        if not clean_tag:
            await ctx.send("❌ Link your account or provide a tag.")
            return

        url = f"{self.api_base}/players/%23{clean_tag}/battlelog"
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200:
                await ctx.send("❌ Could not fetch battle log.")
                return
            data = await resp.json()

        msg = f"📜 **Last 5 Battles for #{clean_tag}**\n\n"
        
        for battle in data[:5]:
            # Determine Win/Loss
            # Team crowns vs Opponent crowns is usually the easiest check
            team_crowns = battle['team'][0]['crowns']
            opp_crowns = battle['opponent'][0]['crowns']
            
            if team_crowns > opp_crowns:
                result = "✅ Win"
            elif team_crowns < opp_crowns:
                result = "❌ Loss"
            else:
                result = "🤝 Draw"
                
            opponent_name = battle['opponent'][0]['name']
            msg += f"{result} vs **{opponent_name}** ({team_crowns}-{opp_crowns})\n"
            
        await ctx.send(msg)

    @commands.command()
    async def clan(self, ctx, tag: str = None):
        """View detailed clan info."""
        # 1. If tag provided, use it. If not, get user's clan.
        clean_tag = None
        
        if tag:
             clean_tag = tag.upper().replace("#", "")
        else:
             # Look up user to get their clan tag
             user_tag = await self.resolve_tag(ctx, None)
             if not user_tag:
                 await ctx.send("❌ Link your account first.")
                 return
                 
             # Fetch player profile to find clan
             p_url = f"{self.api_base}/players/%23{user_tag}"
             async with self.bot.http_session.get(p_url) as resp:
                 if resp.status == 200:
                     p_data = await resp.json()
                     if "clan" in p_data:
                         clean_tag = p_data["clan"]["tag"].replace("#", "")
                     else:
                         await ctx.send("❌ You are not in a clan.")
                         return
                 else:
                     await ctx.send("❌ API Error fetching profile.")
                     return

        # 2. Fetch Clan Data
        c_url = f"{self.api_base}/clans/%23{clean_tag}"
        async with self.bot.http_session.get(c_url) as resp:
            if resp.status != 200:
                await ctx.send("❌ Could not fetch clan data.")
                return
            data = await resp.json()

        embed = discord.Embed(title=f"{data.get('name')} (#{data.get('tag').replace('#','')})", color=0xf1c40f)
        embed.description = data.get("description", "No description.")
        embed.add_field(name="🏆 Clan Score", value=data.get("clanScore"), inline=True)
        embed.add_field(name="👥 Members", value=f"{data.get('members')}/50", inline=True)
        embed.add_field(name="🌍 Location", value=data.get("location", {}).get("name", "Unknown"), inline=True)
        embed.add_field(name="🃏 Donations/Wk", value=data.get("donationsPerWeek"), inline=True)
        
        await ctx.send(embed=embed)

    @commands.command()
    @commands.is_owner()
    async def cleanup(self, ctx):
        """Deletes entries where the ID is stored as a Number."""
        count = 0
        for user in self.users.find():
            user_id = user["_id"]
            if isinstance(user_id, int):
                self.users.delete_one({"_id": user_id})
                count += 1
        await ctx.send(f"🧹 Cleaned up **{count}** duplicate integer entries.")

async def setup(bot):
    await bot.add_cog(Link(bot))
