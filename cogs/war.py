import asyncio
import discord
from discord.ext import commands

class War(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.users = bot.db_users
        self.redis = bot.redis
        self.api_base = "https://proxy.royaleapi.dev/v1"

    async def _safe_defer(self, ctx):
        try:
            await ctx.defer()
            return
        except Exception:
            pass
        try:
            if getattr(ctx, "interaction", None):
                await ctx.interaction.response.defer()
        except Exception:
            pass

    @commands.hybrid_command(name="race")
    async def race(self, ctx, option: str = None):
        """Detailed River Race stats. Usage: !race or /race or !race last"""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            return await ctx.reply("❌ Link your account and join a clan first.", mention_author=False)

        await self._safe_defer(ctx)
        current_url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        fetch_last_war = False
        participants = []
        clan_name = "Unknown"
        header_text = "War Report"

        if option and option.lower() == "last":
            fetch_last_war = True
        else:
            data = await self.bot.fetch_api(current_url, ttl=30)
            if data:
                state = data.get("state")
                if state == "active":
                    clan_name = data.get("clan", {}).get("name", "Unknown")
                    participants = data.get("clan", {}).get("participants", [])
                else:
                    fetch_last_war = True

        if fetch_last_war:
            log_url = f"{self.api_base}/clans/%23{clan_tag}/riverracelog?limit=1"
            log_data = await self.bot.fetch_api(log_url, ttl=300)
            if log_data and log_data.get("items"):
                last_war = log_data["items"][0]
                header_text = f"Last War Report (Season {last_war.get('seasonId')})"
                for standing in last_war.get("standings", []):
                    c = standing.get("clan", {})
                    if c.get("tag") == "#" + clan_tag:
                        clan_name = c.get("name")
                        participants = c.get("participants", [])
                        break
                if option and option.lower() == "last":
                    await ctx.reply("📅 **Showing Previous War Results**", mention_author=False)
                else:
                    await ctx.reply("⚠️ **No active war.** Showing results from last race.", mention_author=False)

        if not participants:
            return await ctx.reply("❌ No war data found (Clan might be inactive).", mention_author=False)

        # Build deck lists using raw decksUsed, treating any >=4 as perfect (4)
        deck_lists = {0: [], 1: [], 2: [], 3: [], 4: []}
        for p in participants:
            d = int(p.get('decksUsed', 0) or 0)
            d_key = 4 if d >= 4 else d
            deck_lists.setdefault(d_key, []).append(p.get('name'))

        sorted_p = sorted(participants, key=lambda x: x.get('fame', 0), reverse=True)[:5]

        # Build Message
        msg = f"📊 **{clan_name} {header_text}**\n\n"
        def format_list(label, names, emoji):
            if not names: return ""
            return f"{emoji} **{label} ({len(names)}):**\n`{', '.join(names)}`\n\n"

        msg += format_list("4/4 Decks (Perfect)", deck_lists.get(4, []), "✅")
        msg += format_list("3/4 Decks (Missed One)", deck_lists.get(3, []), "⚠️")
        msg += format_list("0/4 Decks (Sleeping)", deck_lists.get(0, []), "💤")

        msg += "**🏅 Top 5 Fame Leaders:**\n"
        for i, p in enumerate(sorted_p, 1):
            msg += f"`{i}.` **{p.get('name')}**: {p.get('fame', 0)}\n"

        if len(msg) > 2000:
            msg = msg[:1900] + "\n...(truncated)"
        await ctx.reply(msg, mention_author=False)

    @commands.hybrid_command(name="war")
    async def war(self, ctx, tag: str = None):
        """Check River Race status. Usage: !war [tag] or /war [tag]"""
        await self._safe_defer(ctx)
        target_tag = tag
        if not target_tag:
            clean_tag = await self.get_clan_tag(ctx)
            if not clean_tag:
                return await ctx.reply("❌ Link your account first.", mention_author=False)
            target_tag = clean_tag

        clean_clan_tag = target_tag.replace("#", "")
        url = f"{self.api_base}/clans/%23{clean_clan_tag}/currentriverrace"
        data = await self.bot.fetch_api(url, ttl=30)
        if not data:
            return await ctx.reply(f"❌ API Error or no data", mention_author=False)

        state = data.get("state", "Unknown")
        clan_name = data.get("clan", {}).get("name", "Unknown")
        fame = data.get("clan", {}).get("fame", 0)
        participants = data.get("clan", {}).get("participants", [])
        active = sum(1 for p in participants if int(p.get('decksUsed', 0) or 0) > 0)

        msg = (
            f"⚔️ **{clan_name}**\n"
            f"**State:** {state}\n"
            f"**Fame:** {fame}\n"
            f"**Active:** {active}/{len(participants)}"
        )
        await ctx.reply(msg, mention_author=False)

    async def get_clan_tag(self, ctx):
        discord_id = str(ctx.author.id)
        if self.redis:
            cached_tag = self.redis.get(f"clan_tag:{discord_id}")
            if cached_tag:
                return cached_tag
        user_data = await asyncio.get_running_loop().run_in_executor(None, lambda: self.users.find_one({"_id": discord_id}))
        if not user_data:
            return None
        clean_tag = user_data["player_id"].replace("#", "")
        url = f"{self.api_base}/players/%23{clean_tag}"
        data = await self.bot.fetch_api(url, ttl=3600)
        if not data:
            return None
        clan_tag = data.get("clan", {}).get("tag", "").replace("#", "")
        if clan_tag and self.redis:
            self.redis.setex(f"clan_tag:{discord_id}", 3600, clan_tag)
        return clan_tag

async def setup(bot):
    await bot.add_cog(War(bot))
