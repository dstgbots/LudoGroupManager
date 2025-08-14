from pyrogram import Client, filters
import re
from datetime import datetime

API_ID = 18274091
API_HASH = "97afe4ab12cb99dab4bed25f768f5bbc"
BOT_TOKEN = "5664706056:AAGweTBRqnaS1oQVEWkgxXl1WL9wUO_zuiA"
ADMIN_IDS = [2109516065]
GROUP_ID = -1002849354155

app = Client("ludo_manager", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

games = {}  # Store active games temporarily

def extract_game_data_from_message(message_text):
    lines = message_text.strip().split("\n")
    usernames = []
    amount = None

    for line in lines:
        if "full" in line.lower():
            match = re.search(r"(\d+)\s*[Ff]ull", line)
            if match:
                amount = int(match.group(1))
        else:
            match = re.search(r"@?(\w+)", line)
            if match:
                usernames.append(match.group(1))

    if not usernames or not amount:
        return None

    return {
        "players": usernames,
        "amount": amount,
        "created_at": datetime.now()
    }

def extract_winner_from_edited_message(message_text):
    patterns = [
        r'@(\w+)\s*✅',
        r'(\w+)\s*✅',
        r'✅\s*@(\w+)',
        r'✅\s*(\w+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, message_text)
        if match:
            return match.group(1)
    return None

@app.on_message(filters.chat(GROUP_ID) & filters.user(ADMIN_IDS) & filters.text)
def on_admin_table_message(client, message):
    game_data = extract_game_data_from_message(message.text)
    if game_data:
        games[message.id] = game_data
        print(f"Game created: {game_data}")

@app.on_edited_message(filters.chat(GROUP_ID) & filters.user(ADMIN_IDS) & filters.text)
def on_admin_edit_message(client, message):
    winner = extract_winner_from_edited_message(message.text)
    if winner and message.id in games:
        game_data = games.pop(message.id)
        print(f"Winner: {winner} for game: {game_data}")
        
        # ✅ Send message to the group announcing the winner
        client.send_message(
            GROUP_ID,
            f"🎉 Winner Found: @{winner}\n💰 Prize: {game_data['amount']}"
        )

print("Bot is running...")
app.run()
