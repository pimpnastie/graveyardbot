import discord
from discord.ext import commands

class Link(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_base = "https://proxy.royaleapi.dev/v1"
        self.users = bot.users

    async def resolve_tag(self, ctx, tag):
        if tag:
            return tag.upper().replace("#", "")
        user_data = self.users.find_one({"_id": str(ctx.author.id)})
        return user_data["player_id"] if user_data else None

    @commands.command()
    @commands.guild_only()
    async def link(self, ctx, tag: str):
        clean_tag = tag.upper().replace("#", "")

        self.users.update_one(
            {"_id": str(ctx.author.id)},
            {"$set": {"player_id": clean_tag}},
            upsert=True
        )

        guild = ctx.guild
        member = guild.get_member(ctx.author.id)

        role_id = 1464091054960803893
        role = guild.get_role(role_id)

        if not role:
            await ctx.send(f"✅ Linked to **#{clean_tag}**, but role not found.")
            return

        if role.position >= guild.me.top_role.position:
            await ctx.send("❌ I can't assign that role due to role hierarchy.")
            return

        try:
            await member.add_roles(role, reason="Account linked")
            await ctx.send(f"✅ Linked to **#{clean_tag}** and gave you **{role.name}**!")
        except discord.Forbidden:
            await ctx.send("✅ Linked, but I lack permission to manage roles.")

    @commands.command(aliases=["profile"])
    async def stats(self, ctx, tag: str = None):
        clean_tag = await self.resolve_tag(ctx, tag)
        if not clean_tag:
            await ctx.send("❌ Link your account or provide a tag.")
            return

        url = f"{self.api_base}/players/%23{clean_tag}"
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200:
                await ctx.send("❌ Could not fetch player stats.")
                return
            data = await resp.json()

        embed = discord.Embed(
            title=f"{data.get('name')} (Lvl {data.get('expLevel')})",
            color=0x3498db
        )
        embed.add_field(name="🏆 Trophies", value=data.get("trophies"), inline=True)
        embed.add_field(name="🛡️ Clan", value=data.get("clan", {}).get("name", "None"), inline=True)
        embed.add_field(name="⚔️ W/L", value=f"{data.get('wins')}/{data.get('losses')}", inline=True)
        await ctx.send(embed=embed)

    @commands.command()
    async def chests(self, ctx, tag: str = None):
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
        for chest in items[:3]:
            msg += f"`+{chest['index'] + 1}` **{chest['name']}**\n"
        await ctx.send(msg)

    @commands.command(aliases=["battles", "history"])
    async def log(self, ctx, tag: str = None):
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
            team = battle['team'][0]['crowns']
            opp = battle['opponent'][0]['crowns']
            result = "✅ Win" if team > opp else "❌ Loss" if team < opp else "🤝 Draw"
            msg += f"{result}\n"
        await ctx.send(msg)

    @commands.command()
    async def clan(self, ctx, tag: str = None):
        clean_tag = await self.resolve_tag(ctx, tag)
        if not clean_tag:
            await ctx.send("❌ Link your account first.")
            return

        url = f"{self.api_base}/clans/%23{clean_tag}"
        async with self.bot.http_session.get(url) as resp:
            if resp.status != 200:
                await ctx.send("❌ Could not fetch clan.")
                return
            data = await resp.json()

        embed = discord.Embed(title=data.get("name"), color=0xf1c40f)
        embed.description = data.get("description", "No description.")
        await ctx.send(embed=embed)

    @commands.command()
    @commands.is_owner()
    async def cleanup(self, ctx):
        count = 0
        for user in self.users.find():
            if isinstance(user["_id"], int):
                self.users.delete_one({"_id": user["_id"]})
                count += 1
        await ctx.send(f"🧹 Cleaned {count} entries.")

async def setup(bot):
    await bot.add_cog(Link(bot))
