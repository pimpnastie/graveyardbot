import os, logging, discord, aiohttp, redis, threading, json, sys, time, traceback
from flask import Flask, render_template_string
from discord.ext import commands
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# --- LOGGING SETUP ---
# We configure logging to print to the console so Render captures it
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("clashbot")

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CR_TOKEN = os.getenv("CR_TOKEN") 
MONGO_URL = os.getenv("MONGO_URL")
REDIS_URL = os.getenv("REDIS_URL")

CR_API_BASE = "https://proxy.royaleapi.dev/v1"

# --- DATABASE SETUP ---
# Created ONCE globally. Stays open forever.
print("Step 1: Connecting to Database...")
try:
    mongo = MongoClient(MONGO_URL)
    db = mongo["ClashBotDB"]
    users = db["users"]
    print("✅ Database connection established.")
except Exception as e:
    print(f"❌ CRITICAL DATABASE ERROR: {e}")
    # We don't exit because we want the web server to stay alive even if DB fails

redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

# --- FLASK WEB DASHBOARD ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Graveyard Bot Dashboard</title>
    <style>
        body { font-family: sans-serif; background-color: #2c2f33; color: #ffffff; padding: 20px; }
        h1 { color: #7289da; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; background-color: #23272a; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #99aab5; }
        th { background-color: #7289da; color: white; }
        tr:hover { background-color: #2c2f33; }
        .container { max-width: 800px; margin: 0 auto; }
        .status { padding: 10px; border-radius: 5px; background-color: #43b581; display: inline-block;}
    </style>
</head>
<body>
    <div class="container">
        <h1>🏆 Graveyard Bot Dashboard</h1>
        <div class="status">✅ System Online</div>
        <p>The internal web server is running. Check Render logs for Bot Status.</p>
        
        <h2>🔗 Linked Players</h2>
        <table>
            <tr>
                <th>Discord ID</th>
                <th>Clash Player ID</th>
            </tr>
            {% for user in users %}
            <tr>
                <td>{{ user['_id'] }}</td>
                <td>#{{ user['player_id'] }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    try:
        all_users = list(users.find())
        return render_template_string(HTML_TEMPLATE, users=all_users)
    except Exception as e:
        print(f"⚠️ Dashboard Error (Page Load): {e}")
        return f"Database Error: {e}", 500

def run_flask():
    port = int(os.getenv("PORT", 8080))
    # host='0.0.0.0' is required for Render
    app.run(host='0.0.0.0', port=port)

def start_keep_alive():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class ClashBot(commands.AutoShardedBot):
    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(headers={
            "Authorization": f"Bearer {CR_TOKEN}",
            "Accept": "application/json"
        })
        for cog in ("link",): 
            try:
                await self.load_extension(f"cogs.{cog}")
                print(f"🧩 Extension Loaded: {cog}")
            except Exception as e:
                print(f"⚠️ Failed to load extension {cog}: {e}")
        
        await self.tree.sync()

    async def close(self):
        if hasattr(self, 'http_session') and self.http_session:
            await self.http_session.close()
        # NOTE: We do NOT close mongo here.
        await super().close()

# --- MAIN EXECUTION BLOCK ---
if __name__ == "__main__":
    
    # 1. Start the web server immediately
    print("🌍 Starting web dashboard thread...")
    start_keep_alive()
    
    # Rate Limit Protection Variables
    initial_wait = 10
    wait_time = initial_wait
    
    # 2. Infinite Loop to keep the bot alive
    while True:
        print("\n" + "="*40)
        print(f"🚀 Launching Bot Instance... (Current Backoff: {wait_time}s)")
        print("="*40)
        
        # Create a FRESH bot instance every time
        bot = ClashBot(command_prefix="!", intents=intents)
        
        @bot.event
        async def on_ready():
            print(f"✅ SUCCESS: Logged in as {bot.user} (ID: {bot.user.id})")
            print(f"🌐 Connected to {len(bot.guilds)} guilds")

        # Track start time to know if we had a "stable" run
        start_time = time.time()

        try:
            bot.run(DISCORD_TOKEN)
            
        except discord.errors.HTTPException as e:
            # --- RATE LIMIT PROTECTION ---
            if e.status == 429:
                print("\n🛑 CRITICAL: DISCORD RATE LIMIT DETECTED (429) 🛑")
                print("The bot is restarting too fast. Entering DEEP SLEEP mode.")
                print("Sleeping for 10 minutes to let the ban expire...")
                time.sleep(600) 
                wait_time = initial_wait # Reset backoff after a long sleep
            else:
                print(f"\n❌ HTTP Error detected: {e}")
                print(f"Sleeping for {wait_time} seconds before retrying...")
                time.sleep(wait_time)
                # Exponential Backoff: Double the wait time, capped at 5 mins
                wait_time = min(wait_time * 2, 300)
                
        except Exception as e:
            # --- CRASH PROTECTION ---
            print(f"\n❌ CRITICAL CRASH: {e}")
            traceback.print_exc() # Prints the full error details to logs
            
            # Smart Reset: If bot ran fine for >5 mins, reset the timer
            if time.time() - start_time > 300:
                print("Bot was stable for over 5 mins. Resetting error timer.")
                wait_time = initial_wait
            
            print(f"Sleeping for {wait_time} seconds before restarting...")
            time.sleep(wait_time)
            # Exponential Backoff
            wait_time = min(wait_time * 2, 300)

        except KeyboardInterrupt:
            print("👋 Manual shutdown requested. Exiting.")
            break
