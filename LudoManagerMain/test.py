"""
LudoManager - Pyrogram Listener (test.py)
==========================================
This file handles Pyrogram client for detecting:
1. New admin table messages in the group
2. Edited admin table messages for winner detection

When events are detected, it calls the corresponding handlers in bot.py
"""

from pyrogram import Client, filters
import re
from datetime import datetime

# Import the business logic module
try:
    # Try relative import for package usage
    from . import bot
except ImportError:
    # Fall back to direct import for standalone usage
    import bot

# Configuration - Replace with your actual values
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
        "created_at": datetime.now(),
        "status": "active"
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
    """
    Handle new admin messages that might contain game tables.
    Extracts game data and calls bot.handle_new_game() if valid.
    """
    game_data = extract_game_data_from_message(message.text)
    if game_data:
        # Store the game locally
        games[message.id] = game_data
        print(f"Game created: {game_data}")
        
        # Call bot.py handler for new game
        try:
            bot.handle_new_game(game_data, message.id, message.from_user.id)
            print("✅ bot.handle_new_game() called successfully")
        except Exception as e:
            print(f"❌ Error calling bot.handle_new_game(): {e}")

@app.on_edited_message(filters.chat(GROUP_ID) & filters.user(ADMIN_IDS) & filters.text)
def on_admin_edit_message(client, message):
    """
    Handle edited admin messages for winner detection.
    Looks for checkmark (✅) next to username and calls bot.handle_winner() if found.
    """
    winner = extract_winner_from_edited_message(message.text)
    if winner and message.id in games:
        # Get and remove the game data
        game_data = games.pop(message.id)
        print(f"Winner: {winner} for game: {game_data}")
        
        # Call bot.py handler for winner
        try:
            bot.handle_winner(game_data, winner, message.id, message.from_user.id)
            print("✅ bot.handle_winner() called successfully")
        except Exception as e:
            print(f"❌ Error calling bot.handle_winner(): {e}")
            # Re-add game to dict if bot handler failed
            games[message.id] = game_data
            print("🔄 Game re-added to active games due to handler error")

def start_with_bot_manager(bot_manager_instance=None):
    """
    Start the Pyrogram listener with a specific bot manager instance.
    This ensures proper integration when run as a module.
    """
    if bot_manager_instance:
        # Store the bot manager instance globally for handlers to use
        global _bot_manager_instance
        _bot_manager_instance = bot_manager_instance
        print("✅ Bot manager instance received and stored")
    
    print("🚀 Starting LudoManager Pyrogram Listener...")
    print(f"👥 Monitoring group: {GROUP_ID}")
    print(f"🔑 Admin IDs: {ADMIN_IDS}")
    print("📡 Listening for new game tables and winner edits...")
    print("Bot is running...")
    
    try:
        print("🔄 Setting up event loop for Pyrogram...")
        
        # Create a new event loop for this thread
        import asyncio
        
        # Check if we're in the main thread
        import threading
        if threading.current_thread() is threading.main_thread():
            print("🧵 Running in main thread - using app.run()")
            app.run()
        else:
            print("🧵 Running in background thread - creating new event loop")
            # Create and set a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Now run the Pyrogram app
            app.run()
        
        print("⚠️ Pyrogram app.run() returned - this shouldn't happen unless there was an error")
        
    except Exception as e:
        print(f"❌ Error in Pyrogram startup: {e}")
        import traceback
        print(f"❌ Full traceback: {traceback.format_exc()}")
        raise

def start_standalone():
    """
    Start the Pyrogram listener in standalone mode.
    This initializes its own bot manager instance.
    """
    print("🚀 Starting LudoManager Pyrogram Listener (Standalone Mode)...")
    print(f"👥 Monitoring group: {GROUP_ID}")
    print(f"🔑 Admin IDs: {ADMIN_IDS}")
    print("📡 Listening for new game tables and winner edits...")
    
    # Initialize bot manager for standalone mode
    try:
        bot.initialize_bot_manager()
        print("✅ Bot manager initialized for standalone mode")
    except Exception as e:
        print(f"⚠️ Bot manager initialization failed: {e}")
        print("🔄 Continuing with limited functionality...")
    
    print("Bot is running...")
    app.run()

# Global variable to store bot manager instance
_bot_manager_instance = None

if __name__ == "__main__":
    start_standalone()
