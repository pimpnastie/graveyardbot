import discord
from discord.ext import commands
from discord import app_commands
from bot import cr_get, get_player_id

class War(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send(self, send, user_id):
        pid = get_player_id(user_id)
        if not pid:
            await send("❌ Link your account first.")
            return

        player = await cr_get(f"/players/%23{pid}")
        clan_tag = player["clan"]["tag"].replace("#", "")
        data = await cr_get(f"/clans/%23{clan_tag}/currentriverrace")

        clan = data["clan"]
        embed = discord.Embed(
            title=f"⚔️ {clan['name']} – River Race",
            color=discord.Color.gold()
        )
        embed.add_field(name="Fame", value=clan["fame"])
        embed.add_field(name="Rank", value=clan["rank"])
        await send(embed=embed)

    @commands.command()
    async def war(self, ctx):
        await self._send(ctx.send, ctx.author.id)

    @app_commands.command(name="war", description="Show River Race status")
    async def war_slash(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._send(interaction.followup.send, interaction.user.id)

async def setup(bot):
    await bot.add_cog(War(bot))\n