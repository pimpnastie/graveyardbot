import discord
from discord.ext import commands
from discord import app_commands
from bot import cr_get, get_player_id


class War(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send(self, send, user_id: int):
        pid = get_player_id(user_id)
        if not pid:
            await send("❌ Link your account first using `!link #TAG`.")
            return

        player = await cr_get(f"/players/%23{pid}")
        if not player or "clan" not in player:
            await send("❌ Could not determine your clan.")
            return

        clan_tag = player["clan"]["tag"].replace("#", "")
        data = await cr_get(f"/clans/%23{clan_tag}/currentriverrace")

        if not data or "clan" not in data:
            await send("❌ Failed to fetch River Race data.")
            return

        clan = data["clan"]
        participants = clan.get("participants", [])
        active = sum(1 for p in participants if p.get("decksUsed", 0) > 0)

        embed = discord.Embed(
            title=f"⚔️ {clan.get('name', 'Unknown Clan')} – River Race",
            color=discord.Color.gold()
        )
        embed.add_field(name="State", value=data.get("state", "Unknown"), inline=False)
        embed.add_field(name="Rank", value=clan.get("rank", "?"), inline=True)
        embed.add_field(name="Fame", value=clan.get("fame", 0), inline=True)
        embed.add_field(
            name="Active Participants",
            value=f"{active}/{len(participants)}",
            inline=False
        )

        await send(embed=embed)

    # PREFIX COMMAND
    @commands.command()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def war(self, ctx: commands.Context):
        await self._send(ctx.send, ctx.author.id)

    # SLASH COMMAND
    @app_commands.command(name="war", description="Show River Race status")
    async def war_slash(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._send(interaction.followup.send, interaction.user.id)


async def setup(bot):
    await bot.add_cog(War(bot))
