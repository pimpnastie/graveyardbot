import discord
import asyncio
from discord.ext import commands

ROLE_ID = 1464091054960803893  # Badge role ID

class Link(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_base = "https://proxy.royaleapi.dev/v1"
        self.users = bot.db_users

    async def _find_user(self, discord_id):
        loop = asyncio.get_running_loop()
        def blocking():
            return self.users.find_one({"_id": str(discord_id)})
        return await loop.run_in_executor(None, blocking)

    async def resolve_tag(self, ctx, tag):
        if tag:
            return tag.upper().replace("#", "")
        user_data = await self._find_user(ctx.author.id)
        return user_data["player_id"] if user_data else None

    @commands.hybrid_command(name="link")
    @commands.guild_only()
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def link(self, ctx, tag: str):
        clean_tag = tag.upper().replace("#", "")
        loop = asyncio.get_running_loop()
        def blocking_upsert():
            return self.users.update_one(
                {"_id": str(ctx.author.id)},
                {"$set": {"player_id": clean_tag}},
                upsert=True
            )
        await loop.run_in_executor(None, blocking_upsert)

        guild = ctx.guild
        member = ctx.author
        role = guild.get_role(ROLE_ID)

        if not role:
            return await ctx.reply(f"✅ Linked to **#{clean_tag}**, but role not found.", mention_author=False)

        if role in member.roles:
            return await ctx.reply(f"✅ Linked to **#{clean_tag}**. You already have **{role.name}**.", mention_author=False)

        if guild.me and role.position >= guild.me.top_role.position:
            return await ctx.reply("❌ I can't assign that role due to role hierarchy.", mention_author=False)

        try:
            await member.add_roles(role, reason="Account linked")
            await ctx.reply(f"✅ Linked to **#{clean_tag}** and gave you **{role.name}**!", mention_author=False)
        except discord.Forbidden:
            await ctx.reply("✅ Linked, but I lack permission to manage roles.", mention_author=False)

    @commands.hybrid_command(name="stats", aliases=["profile"])
    async def stats(self, ctx, tag: str = None):
        clean_tag = await self.resolve_tag(ctx, tag)
        if not clean_tag:
            return await ctx.reply("❌ Link your account or provide a tag.", mention_author=False)

        url = f"{self.api_base}/players/%23{clean_tag}"
        data = await self.bot.fetch_api(url, ttl=60)
        if not data:
            return await ctx.reply("❌ Could not fetch player stats.", mention_author=False)

        embed = discord.Embed(title=f"{data.get('name')} (Lvl {data.get('expLevel')})", color=0x3498db)
        embed.add_field(name="🏆 Trophies", value=data.get("trophies"), inline=True)
        embed.add_field(name="🛡️ Clan", value=data.get("clan", {}).get("name", "None"), inline=True)
        embed.add_field(name="⚔️ W/L", value=f"{data.get('wins')}/{data.get('losses')}", inline=True)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.hybrid_command(name="chests")
    async def chests(self, ctx, tag: str = None):
        clean_tag = await self.resolve_tag(ctx, tag)
        if not clean_tag:
            return await ctx.reply("❌ Link your account or provide a tag.", mention_author=False)

        url = f"{self.api_base}/players/%23{clean_tag}/upcomingchests"
        data = await self.bot.fetch_api(url, ttl=60)
        if not data:
            return await ctx.reply("❌ Could not fetch chests.", mention_author=False)

        msg = "**Upcoming Chests:**\n"
        for chest in data.get("items", [])[:3]:
            msg += f"`+{chest.get('index',0) + 1}` **{chest.get('name')}**\n"
        await ctx.reply(msg, mention_author=False)

    @commands.hybrid_command(name="log", aliases=["battles", "history"])
    async def log(self, ctx, tag: str = None):
        clean_tag = await self.resolve_tag(ctx, tag)
        if not clean_tag:
            return await ctx.reply("❌ Link your account or provide a tag.", mention_author=False)

        url = f"{self.api_base}/players/%23{clean_tag}/battlelog"
        data = await self.bot.fetch_api(url, ttl=30)
        if not data:
            return await ctx.reply("❌ Could not fetch battle log.", mention_author=False)

        msg = f"📜 **Last 5 Battles for #{clean_tag}**\n\n"
        for battle in data[:5]:
            team = battle.get('team', [{}])[0].get('crowns', 0)
            opp = battle.get('opponent', [{}])[0].get('crowns', 0)
            result = "✅ Win" if team > opp else "❌ Loss" if team < opp else "🤝 Draw"
            msg += f"{result}\n"
        await ctx.reply(msg, mention_author=False)

    @commands.hybrid_command(name="cleanup")
    @commands.is_owner()
    async def cleanup(self, ctx):
        loop = asyncio.get_running_loop()
        def blocking_cleanup():
            count = 0
            for user in self.users.find():
                if isinstance(user.get("_id"), int):
                    self.users.delete_one({"_id": user["_id"]})
                    count += 1
            return count
        cnt = await loop.run_in_executor(None, blocking_cleanup)
        await ctx.reply(f"🧹 Cleaned {cnt} entries.", mention_author=False)

async def setup(bot):
    await bot.add_cog(Link(bot))
