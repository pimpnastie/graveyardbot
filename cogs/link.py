import discord
import json
import logging
from discord.ext import commands

# --- 🔧 CONFIGURATION ---
ROLE_ID = 1464091054960803893  # Your specific verified role ID

log = logging.getLogger("cogs.link")

class Link(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.users = bot.users  # MongoDB Collection
        self.redis = bot.redis  # Redis Client

    # --- 🧠 SMART CACHING HELPER (New Optimization) ---
    async def get_player_data(self, user_id):
        """
        Retrieves user data with a caching strategy:
        Redis (RAM) -> MongoDB (Disk) -> Cache it -> Return
        """
        redis_key = f"user:{user_id}"

        # 1. TRY REDIS (Fastest)
        if self.redis:
            cached = self.redis.get(redis_key)
            if cached:
                return json.loads(cached)

        # 2. TRY MONGODB (Slower)
        data = self.users.find_one({"_id": str(user_id)})

        # 3. SAVE TO REDIS (If found)
        if data and self.redis:
            # Cache for 1 hour (3600s)
            self.redis.setex(redis_key, 3600, json.dumps(data))

        return data

    def invalidate_cache(self, user_id):
        """Forces the next read to fetch fresh data from DB"""
        if self.redis:
            self.redis.delete(f"user:{user_id}")

    # --- 🔗 COMMANDS ---

    @commands.command()
    @commands.guild_only()
    async def link(self, ctx, tag: str = None):
        """Links your Discord ID to a Clash Royale Player Tag"""
        if not tag:
            return await ctx.send("❌ Usage: `!link #TAG`")

        clean_tag = tag.upper().replace("#", "").replace("O", "0")

        # 1. Update MongoDB (Upsert = Update if exists, Insert if new)
        self.users.update_one(
            {"_id": str(ctx.author.id)},
            {"$set": {"player_id": clean_tag}},
            upsert=True
        )

        # 2. Clear cache so the bot knows you changed tags immediately
        self.invalidate_cache(ctx.author.id)

        # 3. ROLE ASSIGNMENT LOGIC (Restored from your old code)
        guild = ctx.guild
        member = guild.get_member(ctx.author.id)

        # Safety check: ensure member object exists
        if not member:
            await ctx.send(f"✅ Linked to **#{clean_tag}**, but I couldn't find your member object to assign the role.")
            return

        role = guild.get_role(ROLE_ID)
        
        # Check if role exists
        if not role:
            await ctx.send(f"✅ Linked to **#{clean_tag}**, but the Verified Role (ID: {ROLE_ID}) was not found.")
            return

        # Check: Does bot have 'Manage Roles' permission?
        if not guild.me.guild_permissions.manage_roles:
            await ctx.send(f"✅ Linked to **#{clean_tag}**, but I don't have permission to manage roles.")
            return

        # Check: Is the role higher than the bot's top role?
        if role >= guild.me.top_role:
            await ctx.send(f"✅ Linked to **#{clean_tag}**, but I can't give the **{role.name}** role
