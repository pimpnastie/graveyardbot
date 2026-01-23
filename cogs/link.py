import discord
from discord.ext import commands

ROLE_ID = 1464091054960803893

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

        if not member:
            await ctx.send(f"✅ Linked to **#{clean_tag}**, but I couldn't find your member object.")
            return

        role = guild.get_role(ROLE_ID)
        if not role:
            await ctx.send(f"✅ Linked to **#{clean_tag}**, but role not found.")
            return

        if not guild.me.guild_permissions.manage_roles:
            await ctx.send("❌ I don't have permission to manage roles.")
            return

        if role >= guild.me.top_role:
            await ctx.send("❌ That role is higher than my top role.")
            return

        if role in member.roles:
            await ctx.send(f"✅ Linked to **#{clean_tag}** (role already assigned).")
            return

        await member.add_roles(role, reason="Account linked")
        await ctx.send(f"✅ Linked to **#{clean_tag}** and gave you **{role.name}**!")

    # ---- other commands unchanged ----

async def setup(bot):
    await bot.add_cog(Link(bot))
