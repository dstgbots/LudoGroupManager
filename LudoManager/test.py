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
import logging
from datetime import datetime

# Import the business logic module
import bot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration - Replace with your actual values
API_ID = 18274091
API_HASH = "97afe4ab12cb99dab4bed25f768f5bbc"
BOT_TOKEN = "5664706056:AAGweTBRqnaS1oQVEWkgxXl1WL9wUO_zuiA"
ADMIN_IDS = [2109516065]  # Add your admin user IDs here
GROUP_ID = -1002849354155  # Your group chat ID

# Initialize Pyrogram client
app = Client("ludo_manager", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Store active games temporarily (message_id -> game_data)
games = {}


def extract_game_data_from_message(message_text):
    """
    Extract game data from admin message.
    Expected format:
    @player1
    @player2
    @player3
    @player4
    100 Full
    
    Returns:
    {
        "players": ["player1", "player2", "player3", "player4"],
        "amount": 100,
        "created_at": datetime.now()
    }
    """
    try:
        lines = message_text.strip().split("\n")
        usernames = []
        amount = None

        logger.debug(f"Parsing message with {len(lines)} lines")

        for line in lines:
            line = line.strip()
            
            # Check for amount with "full" keyword
            if "full" in line.lower():
                match = re.search(r"(\d+)\s*[Ff]ull", line)
                if match:
                    amount = int(match.group(1))
                    logger.debug(f"Found amount: {amount}")
            else:
                # Extract username (with or without @)
                match = re.search(r"@?(\w+)", line)
                if match and match.group(1):
                    username = match.group(1)
                    usernames.append(username)
                    logger.debug(f"Found player: {username}")

        # Validate extracted data
        if not usernames or not amount:
            logger.debug(f"Invalid game data: usernames={usernames}, amount={amount}")
            return None

        game_data = {
            "players": usernames,
            "amount": amount,
            "created_at": datetime.now()
        }
        
        logger.info(f"✅ Extracted game data: {len(usernames)} players, {amount} amount")
        return game_data

    except Exception as e:
        logger.error(f"❌ Error extracting game data: {e}")
        return None


def extract_winner_from_edited_message(message_text):
    """
    Extract winner from edited message by looking for checkmark (✅) patterns.
    
    Supported patterns:
    - @username ✅
    - username ✅
    - ✅ @username
    - ✅ username
    
    Returns: winner username (without @) or None
    """
    try:
        patterns = [
            r'@(\w+)\s*✅',  # @username ✅
            r'(\w+)\s*✅',   # username ✅
            r'✅\s*@(\w+)',  # ✅ @username
            r'✅\s*(\w+)'    # ✅ username
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message_text)
            if match:
                winner = match.group(1)
                logger.info(f"🏆 Winner extracted: {winner}")
                return winner
                
        logger.debug("No winner pattern found in edited message")
        return None
        
    except Exception as e:
        logger.error(f"❌ Error extracting winner: {e}")
        return None


@app.on_message(filters.chat(GROUP_ID) & filters.user(ADMIN_IDS) & filters.text)
def on_admin_table_message(client, message):
    """
    Handle new admin messages that might contain game tables.
    Extracts game data and calls bot.handle_new_game() if valid.
    """
    try:
        logger.info(f"📝 New admin message received (ID: {message.id})")
        logger.debug(f"Message content: {message.text}")
        
        # Extract game data from the message
        game_data = extract_game_data_from_message(message.text)
        
        if game_data:
            # Store the game locally
            games[message.id] = game_data
            logger.info(f"🎮 Game stored locally (ID: {message.id})")
            logger.info(f"🎮 Total active games: {len(games)}")
            
            # Call bot.py handler for new game
            try:
                bot.handle_new_game(game_data)
                logger.info("✅ bot.handle_new_game() called successfully")
            except Exception as e:
                logger.error(f"❌ Error calling bot.handle_new_game(): {e}")
        else:
            logger.debug("📝 Message doesn't contain valid game table format")
            
    except Exception as e:
        logger.error(f"❌ Error processing new message: {e}")


@app.on_edited_message(filters.chat(GROUP_ID) & filters.user(ADMIN_IDS) & filters.text)
def on_admin_edit_message(client, message):
    """
    Handle edited admin messages for winner detection.
    Looks for checkmark (✅) next to username and calls bot.handle_winner() if found.
    """
    try:
        logger.info(f"🔄 Edited message received (ID: {message.id})")
        logger.debug(f"Edited content: {message.text}")
        
        # Check if this message has an active game
        if message.id not in games:
            logger.debug(f"No active game found for message ID: {message.id}")
            logger.debug(f"Available game IDs: {list(games.keys())}")
            return
        
        # Extract winner from edited message
        winner = extract_winner_from_edited_message(message.text)
        
        if winner:
            # Get and remove the game data
            game_data = games.pop(message.id)
            logger.info(f"🏆 Winner detected: {winner}")
            logger.info(f"🎮 Game found: {game_data}")
            logger.info(f"🎮 Remaining active games: {len(games)}")
            
            # Call bot.py handler for winner
            try:
                bot.handle_winner(game_data, winner)
                logger.info("✅ bot.handle_winner() called successfully")
            except Exception as e:
                logger.error(f"❌ Error calling bot.handle_winner(): {e}")
                # Re-add game to dict if bot handler failed
                games[message.id] = game_data
                logger.info("🔄 Game re-added to active games due to handler error")
        else:
            logger.debug("🔍 Edited message doesn't contain winner marker (✅)")
            
    except Exception as e:
        logger.error(f"❌ Error processing edited message: {e}")


def main():
    """
    Main function to start the Pyrogram client and begin listening.
    """
    try:
        logger.info("🚀 Starting LudoManager Pyrogram Listener...")
        logger.info(f"👥 Monitoring group: {GROUP_ID}")
        logger.info(f"🔑 Admin IDs: {ADMIN_IDS}")
        logger.info("📡 Listening for new game tables and winner edits...")
        
        # Start the client
        app.run()
        
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise


if __name__ == "__main__":
    main()
