import os
import io
import csv
import asyncio
import logging
import gridfs
import math
import copy
from collections import Counter
from datetime import datetime, timezone
import discord
from discord.ext import commands

MAX_CARD_LEVEL = int(os.getenv("MAX_CARD_LEVEL", "16"))

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.users = bot.db_users
        self.history = self.db["clan_history"]
        self.player_history = self.db["player_history"]
        self.fs = gridfs.GridFS(self.db)
        self.redis = bot.redis
        self.api_base = "https://proxy.royaleapi.dev/v1"
        self.log = logging.getLogger("clashbot")

    # --------------------
    # Helpers
    # --------------------
    def _parse_iso(self, s):
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

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

    def _compute_expected_decks(self, war_data):
        try:
            if not war_data:
                return 4

            if war_data.get("periodType") == "training":
                return 0

            # 1) Prefer explicit per-day data if present
            days_block = war_data.get("days") or war_data.get("dayHistory") or war_data.get("daysStats")
            if isinstance(days_block, list) and len(days_block) > 0:
                active_days = 0
                for d in days_block:
                    total_for_day = d.get("decksUsed") or d.get("totalDecks") or d.get("decks", 0)
                    try:
                        if int(total_for_day or 0) > 0:
                            active_days += 1
                    except Exception:
                        pass
                return min(16, active_days * 4)

            # 2) Fallback heuristic using participants' cumulative decks
            participants = []
            clan_part = war_data.get("clan") or {}
            participants = clan_part.get("participants", []) if isinstance(clan_part, dict) else []

            total_clan_decks = sum(int(p.get("decksUsed", 0) or 0) for p in participants)
            if total_clan_decks == 0:
                return 0

            max_decks_used = 0
            for p in participants:
                try:
                    d = int(p.get("decksUsed", 0) or 0)
                except Exception:
                    d = 0
                if d > max_decks_used:
                    max_decks_used = d

            active_days_by_usage = math.ceil(max_decks_used / 4) if max_decks_used > 0 else 0

            # elapsed days from start time / dayIndex
            start_keys = ["startTime", "start_time", "startDate", "startAt", "start"]
            start_str = None
            for k in start_keys:
                if war_data.get(k):
                    start_str = war_data.get(k)
                    break

            now = datetime.utcnow().replace(tzinfo=timezone.utc)
            elapsed_days = None
            if start_str:
                start_dt = self._parse_iso(start_str)
                if start_dt:
                    elapsed_seconds = (now - start_dt).total_seconds()
                    if elapsed_seconds < 0:
                        elapsed_days = 0
                    else:
                        elapsed_days = int(elapsed_seconds // 86400) + 1

            if elapsed_days is None:
                if war_data.get("dayIndex") is not None:
                    try:
                        elapsed_days = int(war_data.get("dayIndex", 1))
                    except Exception:
                        elapsed_days = None
                elif war_data.get("day") is not None:
                    try:
                        elapsed_days = int(war_data.get("day", 1))
                    except Exception:
                        elapsed_days = None

            if elapsed_days is None:
                active_days = active_days_by_usage
            else:
                active_days = min(elapsed_days, active_days_by_usage)

            expected = active_days * 4
            return min(16, expected)
        except Exception:
            self.log.exception("Error computing expected decks")
            return 4

    async def _find_all_users(self):
        loop = asyncio.get_running_loop()
        def blocking():
            return list(self.users.find())
        return await loop.run_in_executor(None, blocking)

    async def _find_user_by_discord(self, discord_id):
        loop = asyncio.get_running_loop()
        def blocking():
            return self.users.find_one({"_id": str(discord_id)})
        return await loop.run_in_executor(None, blocking)

    # --- COMMANDS ---
    @commands.hybrid_command(name="whohas")
    async def whohas(self, ctx, *, card_name: str):
        """Find clan members who have a specific card (checks top 15)."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            await ctx.reply("❌ Link your account and join a clan first.", mention_author=False)
            return

        await self._safe_defer(ctx)
        await ctx.reply(f"🔍 Searching clan for **{card_name}**... (Checking Top 15)", mention_author=False)

        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        clan_data = await self.bot.fetch_api(c_url, ttl=30)
        if not clan_data:
            await ctx.reply("❌ Failed to fetch clan.", mention_author=False)
            return

        members = clan_data.get("memberList", [])[:15]
        hits = []

        for member in members:
            tag = member.get("tag", "").lstrip("#")
            p_url = f"{self.api_base}/players/%23{tag}"
            p_data = await self.bot.fetch_api(p_url, ttl=60)
            if p_data:
                for card in p_data.get("cards", []):
                    if card.get("name", "").lower() == card_name.lower():
                        card_level = card.get("level", 1)
                        card_max = card.get("maxLevel", MAX_CARD_LEVEL)
                        normalized_level = card_level + (MAX_CARD_LEVEL - card_max)
                        hits.append(f"**{member.get('name')}**: Lvl {normalized_level} (raw {card_level}/{card_max})")
                        break
            await asyncio.sleep(0.25)

        if hits:
            msg = f"🃏 **Found {card_name} Owners:**\n" + "\n".join(hits)
            await ctx.reply(msg, mention_author=False)
        else:
            await ctx.reply(f"❌ Not found in Top 15 members.", mention_author=False)

    @commands.hybrid_command(name="forecast")
    async def forecast(self, ctx):
        """Predicts race finish."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            return await ctx.reply("❌ Link your account first.", mention_author=False)

        await self._safe_defer(ctx)
        url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        data = await self.bot.fetch_api(url, ttl=30)
        if not data:
            return await ctx.reply("❌ Failed to fetch race data.", mention_author=False)

        clan = data.get("clan", {})
        fame = clan.get("fame", 0)
        if data.get("periodType") == "training":
            return await ctx.reply("😴 **Training Day:** No forecast available.", mention_author=False)

        GOAL = 10000
        if fame >= GOAL:
            return await ctx.reply("🎉 **Race Finished!**", mention_author=False)

        remaining = GOAL - fame
        decks_used = sum(p.get('decksUsed', 0) for p in clan.get("participants", []))
        avg_fame = fame / decks_used if decks_used > 0 else 0

        if avg_fame > 0:
            needed = int(remaining / avg_fame)
            await ctx.reply(f"🔮 **Forecast:**\n🏁 Fame: `{fame}/{GOAL}`\n🚀 Left: `{remaining}`\n🃏 Est. Decks: `{needed}`", mention_author=False)
        else:
            await ctx.reply("📉 Not enough data.", mention_author=False)

    @commands.hybrid_command(name="scout")
    async def scout(self, ctx, *, arg: str = None):
        """Generates a meta report of opponent cards from the current river race."""
        clan_flag = bool(arg and arg.lower().strip() == "clan")
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            return await ctx.reply("❌ Link your account and join a clan first.", mention_author=False)

        await self._safe_defer(ctx)
        url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"
        data = await self.bot.fetch_api(url, ttl=30)
        if not data:
            return await ctx.reply("❌ Failed to fetch race data.", mention_author=False)

        participants = data.get("clan", {}).get("participants", [])
        if not participants:
            return await ctx.reply("❌ No participants data available.", mention_author=False)

        if not clan_flag:
            linked = await self._find_user_by_discord(ctx.author.id)
            if linked and linked.get("player_id"):
                player_tag = "#" + linked.get("player_id").lstrip("#")
                target = next((p for p in participants if p.get("tag") == player_tag), None)
                if target:
                    top_players = [target]
                else:
                    top_players = sorted(participants, key=lambda x: x.get('decksUsed', 0), reverse=True)[:1]
            else:
                return await ctx.reply("❌ I couldn't resolve your linked player tag. Use `!link <tag>`", mention_author=False)
        else:
            top_players = sorted(participants, key=lambda x: x.get('decksUsed', 0), reverse=True)[:5]

        opponent_cards = []
        for p in top_players:
            tag = p.get('tag', '').lstrip("#")
            b_url = f"{self.api_base}/players/%23{tag}/battlelog"
            logs = await self.bot.fetch_api(b_url, ttl=30)
            if logs:
                for battle in logs[:10]:
                    opp = battle.get("opponent", [{}])[0]
                    for card in opp.get("cards", []):
                        opponent_cards.append(card.get('name'))
            await asyncio.sleep(0.25)

        most_common = Counter(opponent_cards).most_common(5)
        if most_common:
            msg = "⚠️ **Meta Report:**\n" + "\n".join([f"🔥 **{c}** ({n})" for c, n in most_common])
            await ctx.reply(msg, mention_author=False)
        else:
            await ctx.reply("❌ Could not analyze battles.", mention_author=False)

    @commands.hybrid_command(name="rolesync")
    @commands.has_permissions(manage_roles=True)
    async def rolesync(self, ctx):
        """Syncs Discord Roles with Clan Roles."""
        if not await self.is_leader(ctx.author.id):
            return await ctx.reply("❌ Leaders only.", mention_author=False)

        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            return await ctx.reply("❌ Link your account first.", mention_author=False)

        await self._safe_defer(ctx)
        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        clan_data = await self.bot.fetch_api(c_url, ttl=30)
        if not clan_data:
            return await ctx.reply("❌ Failed to fetch clan.", mention_author=False)

        role_map = {
            "member": discord.utils.get(ctx.guild.roles, name="Member"),
            "elder": discord.utils.get(ctx.guild.roles, name="Elder"),
            "coLeader": discord.utils.get(ctx.guild.roles, name="Co-Leader"),
            "leader": discord.utils.get(ctx.guild.roles, name="Leader")
        }

        if not all(role_map.values()):
            return await ctx.reply("⚠️ Missing roles: Member, Elder, Co-Leader, or Leader.", mention_author=False)

        changes = 0
        linked_users = await self._find_all_users()
        for user_doc in linked_users:
            try:
                discord_id = int(user_doc.get("_id"))
            except Exception:
                continue
            member = ctx.guild.get_member(discord_id)
            if not member:
                continue
            cr_member = next((m for m in clan_data.get("memberList", []) if m.get("tag") == "#" + user_doc.get("player_id", "")), None)
            if cr_member:
                target_role = role_map.get(cr_member.get("role"))
                if target_role and target_role not in member.roles:
                    try:
                        await member.remove_roles(*[r for r in role_map.values() if r in member.roles])
                        await member.add_roles(target_role)
                        changes += 1
                    except discord.Forbidden:
                        self.log.warning("Missing perms to update roles for %s", member)
                    except Exception:
                        self.log.exception("Failed to update roles for %s", member)
                    await asyncio.sleep(0.5)
        await ctx.reply(f"✅ **Sync Complete:** Updated {changes} users.", mention_author=False)

    @commands.hybrid_command(name="audit")
    async def audit(self, ctx, option: str = None):
        """Audit report. Usage: `!audit` or `!audit csv` — saves a snapshot to DB or prints CSV."""
        if not await self.is_leader(ctx.author.id):
            return await ctx.reply("❌ Access Denied.", mention_author=False)

        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            return await ctx.reply("❌ Link your account first.", mention_author=False)

        await self._safe_defer(ctx)
        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        w_url = f"{self.api_base}/clans/%23{clan_tag}/currentriverrace"

        clan = await self.bot.fetch_api(c_url, ttl=30)
        if not clan:
            return await ctx.reply("❌ Failed to fetch clan data.", mention_author=False)
        war = await self.bot.fetch_api(w_url, ttl=30) or {}

        expected_decks = self._compute_expected_decks(war)
        war_part = {p.get('tag'): p.get('decksUsed', 0) for p in war.get("clan", {}).get("participants", [])}

        members_summary = []
        clean_tags = []
        for m in clan.get("memberList", []):
            tag = m.get('tag', '')
            clean_tag = tag.lstrip("#")
            clean_tags.append(clean_tag)
            last_seen = m.get('lastSeen')
            last_seen_ts = self._parse_iso(last_seen)
            days_since_seen = None
            if last_seen_ts:
                days_since_seen = (datetime.utcnow().replace(tzinfo=timezone.utc) - last_seen_ts).days
            war_decks = war_part.get(tag, 0)
            deck_completion_pct = None
            if expected_decks and expected_decks > 0:
                try:
                    deck_completion_pct = round(min(1.0, war_decks / expected_decks), 4)
                except Exception:
                    deck_completion_pct = None

            members_summary.append({
                "tag": clean_tag,
                "tag_with_hash": tag,
                "name": m.get('name'),
                "role": m.get('role'),
                "donations": m.get('donations', 0),
                "war_decks": war_decks,
                "expected_decks": expected_decks,
                "deck_completion_pct": deck_completion_pct,
                "last_seen": last_seen,
                "last_seen_ts": last_seen_ts,
                "days_since_seen": days_since_seen,
                "fame": None,
                "trophies": None,
                "exp_level": None
            })

        csv_bytes = None
        if option == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Tag", "Name", "Role", "Donations", "War Decks", "Expected Decks", "Completion%", "Last Seen"])
            for m in members_summary:
                writer.writerow([
                    f"#{m.get('tag','')}",
                    m.get("name", ""),
                    m.get("role", ""),
                    m.get("donations", 0),
                    m.get("war_decks", 0),
                    m.get("expected_decks", 0),
                    f"{m.get('deck_completion_pct') or 0:.2f}",
                    m.get("last_seen") or ""
                ])
            output.seek(0)
            csv_bytes = output.getvalue().encode("utf-8")
            try:
                await ctx.reply("📊 Report:", file=discord.File(io.BytesIO(csv_bytes), filename=f"Audit_{clan_tag}_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.csv"), mention_author=False)
            except Exception:
                # If file sending fails, continue and store CSV in GridFS
                self.log.exception("Failed to send CSV file to Discord; proceeding to store it in DB")

        snapshot = {
            "clan_tag": clan_tag,
            "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc),
            "periodType": war.get("periodType"),
            "season": war.get("seasonId"),
            "fame": war.get("clan", {}).get("fame"),
            "member_count": clan.get("members", 0),
            "members": members_summary,
            "issues": [f"**{m.get('name')}**: {m.get('war_decks', 0)}/{m.get('expected_decks', 0)} War Decks" for m in members_summary if (m.get('war_decks', 0) < (m.get('expected_decks', 0) or 0))]
        }

        loop = asyncio.get_running_loop()
        try:
            csv_gridfs_id = None
            if csv_bytes:
                def blocking_put_csv(data, filename):
                    return self.fs.put(data, filename=filename)
                filename = f"audit_{clan_tag}_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.csv"
                try:
                    csv_gridfs_id = await loop.run_in_executor(None, blocking_put_csv, csv_bytes, filename)
                    snapshot["csv_gridfs_id"] = csv_gridfs_id
                except Exception:
                    self.log.exception("GridFS store failed; proceeding without CSV reference")

            def blocking_insert_snapshot(doc):
                return self.history.insert_one(doc)
            res = await loop.run_in_executor(None, blocking_insert_snapshot, snapshot)
            snapshot_id = res.inserted_id

            def blocking_fetch_linked(tags):
                return list(self.users.find({"player_id": {"$in": tags}}, {"player_id": 1, "_id": 1}))
            linked_docs = await loop.run_in_executor(None, blocking_fetch_linked, clean_tags)
            linked_map = {d.get("player_id"): d.get("_id") for d in linked_docs if d.get("player_id")}

            player_docs = []
            for m in members_summary:
                last_seen_ts = m.get("last_seen_ts")
                last_seen_iso = last_seen_ts.isoformat() if last_seen_ts else None
                days_since_seen = m.get("days_since_seen")
                doc = {
                    "player_tag": m.get("tag"),
                    "player_tag_with_hash": m.get("tag_with_hash"),
                    "clan_tag": clan_tag,
                    "timestamp": snapshot["timestamp"],
                    "war_decks": m.get("war_decks"),
                    "expected_decks": m.get("expected_decks"),
                    "deck_completion_pct": m.get("deck_completion_pct"),
                    "fame": m.get("fame"),
                    "trophies": m.get("trophies"),
                    "exp_level": m.get("exp_level"),
                    "last_seen": m.get("last_seen"),
                    "last_seen_ts": last_seen_iso,
                    "days_since_seen": days_since_seen,
                    "discord_id": linked_map.get(m.get("tag")),
                    "snapshot_id": snapshot_id
                }
                player_docs.append(doc)

            if player_docs:
                def blocking_insert_players(docs):
                    return self.player_history.insert_many(docs)
                await loop.run_in_executor(None, blocking_insert_players, player_docs)

            self.log.info("Saved audit snapshot %s (players: %d)", snapshot_id, len(player_docs))
        except Exception:
            self.log.exception("Failed to persist audit history")

    @commands.hybrid_command(name="primetime")
    async def primetime(self, ctx):
        """Shows the hour (UTC) when the clan is most active."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            return await ctx.reply("❌ Link your account first.", mention_author=False)

        await self._safe_defer(ctx)
        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        data = await self.bot.fetch_api(c_url, ttl=30)
        if not data:
            return await ctx.reply("❌ Could not fetch clan data.", mention_author=False)

        hours = []
        for member in data.get("memberList", []):
            if "lastSeen" in member:
                try:
                    ls = member['lastSeen']
                    hour_str = ls.split('T')[1][:2]
                    hours.append(int(hour_str))
                except Exception:
                    pass

        if not hours:
            return await ctx.reply("❌ No activity data available.", mention_author=False)

        peak_hour, count = Counter(hours).most_common(1)[0]
        note = "Morning" if 5 <= peak_hour < 12 else "Afternoon" if 12 <= peak_hour < 17 else "Evening" if 17 <= peak_hour < 22 else "Night"
        await ctx.reply(f"🕒 **Prime Time:** The clan is most active around **{peak_hour}:00 UTC** ({note}).\n📊 Based on {len(hours)} active members.", mention_author=False)

    @commands.hybrid_command(name="clan")
    async def clan(self, ctx):
        """Shows general clan stats."""
        clan_tag = await self.get_clan_tag(ctx)
        if not clan_tag:
            return await ctx.reply("❌ Link your account first.", mention_author=False)

        await self._safe_defer(ctx)
        c_url = f"{self.api_base}/clans/%23{clan_tag}"
        data = await self.bot.fetch_api(c_url, ttl=30)
        if not data:
            return await ctx.reply("❌ Could not fetch clan data.", mention_author=False)

        embed = discord.Embed(title=f"{data.get('name')} (#{data.get('tag').replace('#','')})", color=0xF1C40F)
        embed.description = data.get("description", "No description.")
        embed.add_field(name="🏆 Clan Score", value=data.get("clanScore", 0), inline=True)
        embed.add_field(name="⚔️ War Trophies", value=data.get("clanWarTrophies", 0), inline=True)
        embed.add_field(name="👥 Members", value=f"{data.get('members', 0)}/50", inline=True)
        loc = data.get("location", {}).get("name", "Unknown")
        embed.add_field(name="🌍 Location", value=loc, inline=True)
        req = data.get("requiredTrophies", 0)
        embed.add_field(name="🚪 Required", value=f"{req}+ Trophies", inline=True)
        await ctx.reply(embed=embed, mention_author=False)

    async def get_clan_tag(self, ctx):
        discord_id = str(ctx.author.id)
        if self.redis:
            cached_tag = self.redis.get(f"clan_tag:{discord_id}")
            if cached_tag:
                return cached_tag
        user_data = await self._find_user_by_discord(ctx.author.id)
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

    async def is_leader(self, discord_id):
        user_data = await self._find_user_by_discord(discord_id)
        if not user_data:
            return False
        clean_tag = user_data["player_id"].replace("#", "")
        url = f"{self.api_base}/players/%23{clean_tag}"
        data = await self.bot.fetch_api(url, ttl=60)
        if data:
            return data.get("role") in ("leader", "coLeader")
        return False

async def setup(bot):
    await bot.add_cog(Admin(bot))
