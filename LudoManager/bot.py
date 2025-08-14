"""
LudoManager - Business Logic (bot.py)
====================================
This file contains the core business logic for handling:
1. New game creation and database storage
2. Winner processing and notifications

Called by test.py when game events are detected.
"""

import logging
import os
from datetime import datetime
from typing import Dict, Any
import asyncio

# Third-party imports
try:
    from pymongo import MongoClient
    PYMONGO_AVAILABLE = True
except ImportError:
    PYMONGO_AVAILABLE = False
    logging.warning("⚠️ pymongo not available - database features disabled")

try:
    from pyrogram import Client
    PYROGRAM_AVAILABLE = True
except ImportError:
    PYROGRAM_AVAILABLE = False
    logging.warning("⚠️ pyrogram not available - message sending disabled")

# Configure logging
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = "5664706056:AAGweTBRqnaS1oQVEWkgxXl1WL9wUO_zuiA"
GROUP_ID = -1002849354155
MONGO_URI = "mongodb://localhost:27017/"
DATABASE_NAME = "ludo_bot"
API_ID = 18274091
API_HASH = "97afe4ab12cb99dab4bed25f768f5bbc"

# Global variables
mongo_client = None
database = None
pyrogram_client = None


def initialize_database():
    """Initialize MongoDB connection."""
    global mongo_client, database
    
    if not PYMONGO_AVAILABLE:
        logger.warning("⚠️ MongoDB not available - database operations will be logged only")
        return None
    
    try:
        mongo_client = MongoClient(MONGO_URI)
        database = mongo_client[DATABASE_NAME]
        mongo_client.admin.command('ping')
        logger.info("✅ MongoDB connection established successfully")
        return database
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {e}")
        return None


def initialize_pyrogram_client():
    """Initialize Pyrogram client for sending messages."""
    global pyrogram_client
    
    if not PYROGRAM_AVAILABLE:
        logger.warning("⚠️ Pyrogram not available - messages will be logged only")
        return None
    
    try:
        pyrogram_client = Client(
            "ludo_bot_sender",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            no_updates=True
        )
        logger.info("✅ Pyrogram client initialized for message sending")
        return pyrogram_client
    except Exception as e:
        logger.error(f"❌ Failed to initialize Pyrogram client: {e}")
        return None


async def send_message_to_group(text: str) -> bool:
    """Send a message to the group using Pyrogram client."""
    global pyrogram_client
    
    try:
        if not pyrogram_client:
            logger.error("❌ Pyrogram client not initialized")
            return False
        
        if not pyrogram_client.is_connected:
            await pyrogram_client.start()
        
        await pyrogram_client.send_message(chat_id=GROUP_ID, text=text)
        logger.info(f"✅ Message sent to group: {text}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send message to group: {e}")
        return False


def store_game_in_database(game_data: Dict[str, Any]) -> bool:
    """Store game data in MongoDB database."""
    try:
        if not database:
            logger.warning("⚠️ Database not available - game not stored")
            return False
        
        game_document = {
            "players": game_data["players"],
            "amount": game_data["amount"],
            "created_at": game_data["created_at"],
            "status": "active",
            "winner": None,
            "completed_at": None
        }
        
        result = database.games.insert_one(game_document)
        
        if result.inserted_id:
            logger.info(f"✅ Game stored in database with ID: {result.inserted_id}")
            return True
        else:
            logger.error("❌ Failed to store game in database")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error storing game in database: {e}")
        return False


def update_game_winner_in_database(game_data: Dict[str, Any], winner: str) -> bool:
    """Update game in database with winner information."""
    try:
        if not database:
            logger.warning("⚠️ Database not available - winner not recorded")
            return False
        
        query = {
            "players": game_data["players"],
            "amount": game_data["amount"],
            "status": "active"
        }
        
        update_data = {
            "$set": {
                "status": "completed",
                "winner": winner,
                "completed_at": datetime.now()
            }
        }
        
        result = database.games.update_one(query, update_data)
        
        if result.modified_count > 0:
            logger.info(f"✅ Game updated in database with winner: {winner}")
            return True
        else:
            logger.warning(f"⚠️ No matching active game found in database for winner: {winner}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error updating game winner in database: {e}")
        return False


def handle_new_game(game_data: Dict[str, Any]) -> None:
    """
    Handle new game creation.
    
    This function is called by test.py when a new game table is detected.
    
    Args:
        game_data: Dictionary containing:
            - players: List of player usernames
            - amount: Game amount
            - created_at: Creation timestamp
    """
    try:
        logger.info("🎮 NEW GAME DETECTED")
        logger.info(f"👥 Players: {', '.join(game_data['players'])}")
        logger.info(f"💰 Amount: {game_data['amount']}")
        logger.info(f"📅 Created: {game_data['created_at']}")
        
        # Store in database
        db_success = store_game_in_database(game_data)
        
        if db_success:
            logger.info("✅ New game processed successfully")
        else:
            logger.warning("⚠️ New game processed but database storage failed")
            
    except Exception as e:
        logger.error(f"❌ Error handling new game: {e}")


def handle_winner(game_data: Dict[str, Any], winner: str) -> None:
    """
    Handle winner detection and processing.
    
    This function is called by test.py when a winner is detected.
    
    Args:
        game_data: Dictionary containing game information
        winner: Username of the winner (without @)
    """
    try:
        logger.info("🏆 WINNER DETECTED")
        logger.info(f"🏆 Winner: {winner}")
        logger.info(f"👥 Players: {', '.join(game_data['players'])}")
        logger.info(f"💰 Prize: {game_data['amount']}")
        
        # Update database with winner
        db_success = update_game_winner_in_database(game_data, winner)
        
        # Prepare winner announcement message
        winner_message = f"🎉 **WINNER ANNOUNCED!**\n\n🏆 Winner: @{winner}\n💰 Prize: {game_data['amount']}\n👥 Players: {', '.join(['@' + p for p in game_data['players']])}"
        
        # Send winner announcement to group
        async def send_announcement():
            success = await send_message_to_group(winner_message)
            if success:
                logger.info("✅ Winner announcement sent to group")
            else:
                logger.error("❌ Failed to send winner announcement to group")
        
        # Run the async function
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(send_announcement())
            else:
                loop.run_until_complete(send_announcement())
        except RuntimeError:
            asyncio.run(send_announcement())
        
        if db_success:
            logger.info("✅ Winner processed successfully")
        else:
            logger.warning("⚠️ Winner processed but database update failed")
            
    except Exception as e:
        logger.error(f"❌ Error handling winner: {e}")


def initialize():
    """Initialize all required components."""
    logger.info("🚀 Initializing LudoManager business logic...")
    initialize_database()
    initialize_pyrogram_client()
    logger.info("✅ LudoManager business logic initialized")


# Auto-initialize when module is imported
try:
    initialize()
except Exception as e:
    logger.error(f"❌ Failed to initialize bot module: {e}")


if __name__ == "__main__":
    # Test the functions when run directly
    logger.info("🧪 Testing bot.py functions...")
    
    test_game_data = {
        "players": ["player1", "player2", "player3", "player4"],
        "amount": 100,
        "created_at": datetime.now()
    }
    
    handle_new_game(test_game_data)
    handle_winner(test_game_data, "player1")
    
    logger.info("🧪 Bot.py test completed")
