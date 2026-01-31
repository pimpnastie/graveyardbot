import os
import logging
import discord
import aiohttp
import redis
import threading
import time
import traceback
import asyncio
import copy
from bson import ObjectId
from flask import Flask, render_template_string
from discord.ext import commands
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clashbot")

# --- CONFIG ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CR_TOKEN = os.getenv("CR_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
REDIS_URL = os.getenv("REDIS_URL")
# Replace with your actual Render URL
PUBLIC_URL = "https://graveyardbot.onrender.com" 

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

# --- DATABASE ---
mongo = MongoClient(MONGO_URL)
db = mongo["ClashBotDB"]
users_collection = db["users"]
clan_history = db["clan_history"]
scout_history = db["scout_history"] # New collection for scout reports

# --- REDIS (OPTIONAL) ---
redis_client = None
if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        log.info("✅ Redis connected")
    except Exception as e:
        log.error(f"❌ Redis failed: {e}")

# --- FLASK DASHBOARD ---
app = Flask(__name__)

# --- TEMPLATES ---
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Graveyard Bot Dashboard</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f0f2f5; padding: 20px; color: #333; }
        h1 { text-align: center; color: #444; margin-bottom: 30px; }
        .container { max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { padding: 15px; text-align: left; border-bottom: 1px solid #eee; }
        th { background-color: #4CAF50; color: white; font-weight: 600; text-transform: uppercase; font-size: 0.9em; }
        tr:hover { background-color: #f8f9fa; }
        .tag { font-family: monospace; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px; }
        .trophy { color: #d32f2f; font-weight: bold; }
        .rank { font-weight: 500; color: #2c3e50; }
        .empty { text-align: center; color: #999; padding: 40px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏆 Graveyard Bot Dashboard</h1>
        {% if users %}
        <table>
            <thead>
                <tr>
                    <th>Discord User</th>
                    <th>Player Tag</th>
                    <th>Rank / Arena</th>
                    <th>Trophies</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr>
                    <td><b>{{ user.discord_name }}</b></td>
                    <td><span class="tag">{{ user.player_tag }}</span></td>
                    <td class="rank">{{ user.rank }}</td>
                    <td class="trophy">🏆 {{ user.trophies }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="empty">No linked users found. Use <code>!link</code> in Discord!</div>
        {% endif %}
    </div>
</body>
</html>
"""

REPORT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Graveyard Bot Report</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background-color: #e9ecef; padding: 20px; }
        .container { max-width: 1100px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { background: #343a40; color: white; padding: 20px; display: flex; justify-content: space-between; align-items: center; }
        .header h1 { margin: 0; font-size: 1.5em; }
        .meta { font-size: 0.9em; color: #adb5bd; }
        
        table { width: 100%; border-collapse: collapse; }
        th { background: #f8f9fa; color: #495057; font-weight: 600; text-align: left; padding: 12px 15px; border-bottom: 2px solid #dee2e6; }
        td { padding: 12px 15px; border-bottom: 1px solid #dee2e6; vertical-align: middle; }
        
        /* Expandable Rows */
        .main-row { cursor: pointer; transition: background 0.2s; }
        .main-row:hover { background-color: #f1f3f5; }
        .detail-row { background-color: #fafafa; display: none; }
        .detail-content { padding: 20px; border-left: 4px solid #4CAF50; margin: 10px 0; }
        
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; }
        .stat-box { background: white; padding: 10px; border: 1px solid #eee; border-radius: 4px; }
        .stat-label { font-size: 0.8em; color: #888; text-transform: uppercase; margin-bottom: 4px; }
        .stat-value { font-weight: bold; color: #333; }
        
        .tag { font-family: monospace; background: #e2e6ea; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }
        .warn { color: #dc3545; font-weight: bold; }
        .good { color: #28a745; font-weight: bold; }
        
        .toggle-icon { display: inline-block; width: 20px; text-align: center; transition: transform 0.2s; }
        .expanded .toggle-icon { transform: rotate(90deg); }
    </style>
    <script>
        function toggleRow(id) {
            var detailRow = document.getElementById('detail-' + id);
            var mainRow = document.getElementById('main-' + id);
            if (detailRow.style.display === 'table-row') {
                detailRow.style.display = 'none';
                mainRow.classList.remove('expanded');
            } else {
                detailRow.style.display = 'table-row';
                mainRow.classList.add('expanded');
            }
        }
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>{{ title }}</h1>
                <div class="meta">ID: {{ report_id }} • {{ timestamp }}</div>
            </div>
            <a href="/" style="color:white; text-decoration:none; border:1px solid white; padding:5px 10px; border-radius:4px;">Back to Dashboard</a>
        </div>

        <table>
            <thead>
                <tr>
                    <th style="width: 30px;"></th>
                    {% for col in columns %}
                    <th>{{ col }}</th>
                    {% endfor %}
                </tr>
            </thead>
            <tbody>
                {% for row in data %}
                <tr id="main-{{ loop.index }}" class="main-row" onclick="toggleRow('{{ loop.index }}')">
                    <td><span class="toggle-icon">▶</span></td>
                    {% for cell in row.summary %}
                    <td>{{ cell|safe }}</td>
                    {% endfor %}
                </tr>
                <tr id="detail-{{ loop.index }}" class="detail-row">
                    <td colspan="{{ columns|length + 1 }}">
                        <div class="detail-content">
                            <div class="grid">
                                {% for key, val in row.details.items() %}
                                <div class="stat-box">
                                    <div class="stat-label">{{ key }}</div>
                                    <div class="stat-value">{{ val }}</div>
                                </div>
                                {% endfor %}
                            </div>
                        </div>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

# --- ROUTES ---

@app.route("/")
def home():
    if not bot or not bot.is_ready():
        return "<h1>Bot is starting...</h1><p>Please wait a moment for the data to load.</p>", 503

    try:
        db_users = list(users_collection.find())
        dashboard_data = []

        for user in db_users:
            try:
                discord_id = int(user["_id"])
                player_tag = user.get("player_id", "")
                clean_tag = player_tag.replace("#", "")

                discord_obj = bot.get_user(discord_id)
                discord_name = discord_obj.name if discord_obj else f"Unknown ({discord_id})"

                trophies = "N/A"
                rank = "N/A"

                if clean_tag:
                    url = f"https://proxy.royaleapi.dev/v1/players/%23{clean_tag}"
                    try:
                        future = asyncio.run_coroutine_threadsafe(bot.fetch_api(url), bot.loop)
                        clash_data = future.result(timeout=5)
                        if clash_data:
                            trophies = clash_data.get("trophies", 0)
                            rank = clash_data.get("arena", {}).get("name", "Unknown")
                    except Exception:
                        pass

                dashboard_data.append({
                    "discord_name": discord_name,
                    "player_tag": player_tag,
                    "rank": rank,
                    "trophies": trophies
                })
            except Exception:
                continue

        dashboard_data.sort(key=lambda x: x["trophies"] if isinstance(x["trophies"], int) else -1, reverse=True)
        return render_template_string(DASHBOARD_TEMPLATE, users=dashboard_data)

    except Exception:
        log.exception("Dashboard: Critical error in home route")
        return "<h1>Internal Server Error</h1>", 500

@app.route("/report/<rtype>/<rid>")
def view_report(rtype, rid):
    try:
        if rtype == "audit":
            doc = clan_history.find_one({"_id": ObjectId(rid)})
            if not doc: return "Report not found", 404
            
            title = f"🛡️ Audit Log: {doc.get('clan_tag')}"
            columns = ["Name", "Role", "War Decks", "Status"]
            data = []
            
            for m in doc.get("members", []):
                used = m.get('war_decks', 0)
                expected = m.get('expected_decks', 0)
                
                # Logic for status color
                if expected > 0 and used < expected:
                    status = f"<span class='warn'>Missed ({used}/{expected})</span>"
                else:
                    status = "<span class='good'>OK</span>"

                data.append({
                    "summary": [
                        m.get('name', 'Unknown'), 
                        m.get('role', 'Member').capitalize(),
                        f"{used} / {expected}",
                        status
                    ],
                    "details": {
                        "Tag": f"#{m.get('tag')}",
                        "Trophies": m.get('trophies', 0),
                        "Arena": m.get('arena', 'Unknown'),
                        "Donations Sent": m.get('donations', 0),
                        "Donations Received": m.get('donations_received', 0),
                        "Fame Earned": m.get('fame', 0),
                        "Last Seen": m.get('last_seen', 'Unknown').replace('T', ' ')[:16],
                        "Days Inactive": m.get('days_since_seen', 'N/A')
                    }
                })
            
            return render_template_string(REPORT_TEMPLATE, title=title, report_id=rid, timestamp=doc.get('timestamp'), columns=columns, data=data)

        elif rtype == "scout":
            doc = scout_history.find_one({"_id": ObjectId(rid)})
            if not doc: return "Report not found", 404
            
            title = f"⚔️ Scout Report: {doc.get('clan_tag')}"
            columns = ["Opponent", "Trophies", "Deck Archetype"]
            data = []
            
            for battle in doc.get("battles", []):
                cards = battle.get("cards", [])
                # Simple archetype guess based on first 3 cards
                archetype = ", ".join(cards[:3]) + "..." if cards else "Unknown"
                
                data.append({
                    "summary": [
                        battle.get('opponent', 'Unknown'),
                        f"🏆 {battle.get('trophies', 0)}",
                        archetype
                    ],
                    "details": {
                        "Full Deck": ", ".join(cards),
                        "Result": "Analyzed from Recent Battles"
                    }
                })
                
            return render_template_string(REPORT_TEMPLATE, title=title, report_id=rid, timestamp=doc.get('timestamp'), columns=columns, data=data)

    except Exception:
        log.exception("Error rendering report")
        return "Internal Server Error", 500

def run_flask():
    port = int(os.getenv("PORT", 10000))
    try:
        app.run(host="0.0.0.0", port=port)
    except OSError:
        app.run(host="0.0.0.0", port=5001)

threading.Thread(target=run_flask, daemon=True).start()

# --- DISCORD BOT ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class ClashBot(commands.AutoShardedBot):
    async def setup_hook(self):
        headers = {"Accept": "application/json"}
        if CR_TOKEN:
            headers["Authorization"] = f"Bearer {CR_TOKEN}"
        self.http_session = aiohttp.ClientSession(headers=headers)

        self.mongo = mongo
        self.db = db
        self.db_users = users_collection
        self.redis = redis_client
        
        # Helper to get the public URL for commands
        self.public_url = PUBLIC_URL 

        self.api_cache = {}
        self.api_semaphore = asyncio.Semaphore(int(os.getenv("API_CONCURRENCY", "6")))

        await self._ensure_db_indexes()

        extensions = ["cogs.link", "cogs.admin", "cogs.war", "cogs.reminders"]
        for ext in extensions:
            try:
                await self.load_extension(ext)
                log.info(f"✅ Loaded extension: {ext}")
            except Exception as e:
                log.error(f"❌ Failed to load extension {ext}: {e}")
        await self.tree.sync()

    async def _ensure_db_indexes(self):
        # Basic indexing
        pass # (Existing indexing logic is fine, kept brief for this block)

    async def fetch_api(self, url, ttl=300):
        now = time.time()
        cached = self.api_cache.get(url)
        if cached and cached[0] > now:
            return copy.deepcopy(cached[1])

        async with self.api_semaphore:
            try:
                async with self.http_session.get(url) as resp:
                    if resp.status != 200: return None
                    data = await resp.json()
                    self.api_cache[url] = (now + ttl, copy.deepcopy(data))
                    return copy.deepcopy(data)
            except Exception:
                return None

    async def close(self):
        if hasattr(self, "http_session"): await self.http_session.close()
        await super().close()

bot = ClashBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    log.info(f"✅ Logged in as {bot.user}")

if __name__ == "__main__":
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        # These lines will print the actual error to your logs
        log.error(f"❌ CRITICAL ERROR: {e}")
        traceback.print_exc() 
        
        # Keep the container alive so you can read the logs
        while True: time.sleep(3600)
