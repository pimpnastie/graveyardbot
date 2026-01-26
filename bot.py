@app.route("/")
async def index():
    # 1. Fetch all linked users from your DB
    linked_users = await bot.db_users.find().to_list(length=1000)
    
    dashboard_data = []
    
    for user in linked_users:
        discord_id = int(user["_id"])
        player_tag = user["player_id"]
        clean_tag = player_tag.replace("#", "")
        
        # --- A. Get Discord Name ---
        # Try to get from cache; if None, it returns "Unknown"
        discord_user = bot.get_user(discord_id)
        discord_name = discord_user.name if discord_user else f"Unknown ({discord_id})"
        
        # --- B. Get Clash Stats (Trophies & Rank) ---
        # We use the existing fetch_api helper from your bot
        clash_data = await bot.fetch_api(f"https://proxy.royaleapi.dev/v1/players/%23{clean_tag}")
        
        if clash_data:
            trophies = clash_data.get("trophies", 0)
            # "Arena" is usually the best indicator of Rank/League
            rank = clash_data.get("arena", {}).get("name", "Unknown Arena")
            # Optional: Use "LeagueStatistics" if you want Ultimate Champion ranks, 
            # but Arena is safer for general users.
        else:
            trophies = "N/A"
            rank = "N/A"

        dashboard_data.append({
            "discord_name": discord_name,
            "player_tag": player_tag,
            "rank": rank,
            "trophies": trophies
        })

    # Sort by Trophies (High to Low) because it looks cooler
    dashboard_data.sort(key=lambda x: x["trophies"] if isinstance(x["trophies"], int) else 0, reverse=True)

    return await render_template("index.html", users=dashboard_data)
