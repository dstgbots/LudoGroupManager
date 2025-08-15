#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import logging
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union

import pyrogram
from pyrogram import Client, filters as pyrogram_filters
from pyrogram.types import Message, MessageEntity

# Try to import Pyrogram enums, fallback to string constants if not available
try:
    from pyrogram.enums import MessageEntityType
    PYROGRAM_ENUMS_AVAILABLE = True
    print("✅ Pyrogram enums available")
except ImportError:
    PYROGRAM_ENUMS_AVAILABLE = False
    print("⚠️ Pyrogram enums not available, using string constants")
    # Create a dummy MessageEntityType class for compatibility
    class MessageEntityType:
        MENTION = "mention"
        TEXT_MENTION = "text_mention"

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB setup (you'll need to install pymongo)
try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure
    
    # Replace with your MongoDB connection string
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb+srv://rolex1:rolex1@cluster0.wndb12x.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
    client = MongoClient(MONGO_URI)
    client.admin.command('ping')
    db = client['ludo_bot']
    users_collection = db['users']
    games_collection = db['games']
    transactions_collection = db['transactions']
    balance_sheet_collection = db['balance_sheet']
    
    print("✅ Connected to MongoDB successfully")
except (ConnectionFailure, ImportError) as e:
    print(f"❌ MongoDB connection failed: {e}")
    print("⚠️ Running in limited mode without database persistence")

class LudoManagerBot:
    def __init__(self, bot_token: str, api_id: int, api_hash: str, group_id: int, admin_ids: List[int]):
        self.bot_token = bot_token
        self.api_id = api_id
        self.api_hash = api_hash
        self.group_id = group_id
        self.admin_ids = admin_ids
        
        # Active games storage - using string IDs for consistency
        self.active_games = {}
        
        # Pyrogram client will be initialized later
        self.pyro_client = None
        
        # Balance sheet management
        self.pinned_balance_msg_id = None
        self._load_pinned_message_id()
        
        # Check if Pyrogram is available
        self.pyrogram_available = True
        try:
            import pyrogram
        except ImportError:
            self.pyrogram_available = False
            print("⚠️ Pyrogram not installed. Edited message handling will be limited.")

    def is_configured_group(self, chat_id: int) -> bool:
        """Check if the message is from the configured group"""
        return str(chat_id) == str(self.group_id)
    
    def _generate_message_link(self, chat_id: int, message_id: int) -> str:
        """Generate a Telegram message link for the given chat and message"""
        try:
            # Convert chat_id to proper format for Telegram links
            # For groups: remove -100 prefix from chat_id
            if str(chat_id).startswith('-100'):
                link_chat_id = str(chat_id)[4:]  # Remove '-100' prefix
            else:
                link_chat_id = str(chat_id).lstrip('-')  # Remove any minus sign
            
            # Create the Telegram message link
            link = f"https://t.me/c/{link_chat_id}/{message_id}"
            logger.info(f"view game table: {link}")
            return link
        except Exception as e:
            logger.error(f"❌ Error generating message link: {e}")
            return f"Message ID: {message_id }"

    async def _resolve_user_mention(self, identifier: str, update: Update) -> Optional[Dict]:
        """Resolve user from mention, user ID, or username with comprehensive matching"""
        try:
            logger.info(f"🔍 Resolving user identifier: {identifier}")
            
            # First, check if it's a numeric user ID
            if identifier.isdigit():
                user_id = int(identifier)
                user_data = users_collection.find_one({'user_id': user_id})
                if user_data:
                    logger.info(f"✅ Found user by ID: {user_id}")
                    return user_data
            
            # Try direct username match
            user_data = users_collection.find_one({'username': identifier})
            if user_data:
                logger.info(f"✅ Found user by direct username match: {identifier}")
                return user_data
            
            # Try case-insensitive username match
            user_data = users_collection.find_one({'username': {'$regex': f'^{re.escape(identifier)}$', '$options': 'i'}})
            if user_data:
                logger.info(f"✅ Found user by case-insensitive match: {identifier} -> {user_data['username']}")
                return user_data
            
            # Try first name match (case-insensitive)
            user_data = users_collection.find_one({'first_name': {'$regex': f'^{re.escape(identifier)}$', '$options': 'i'}})
            if user_data:
                logger.info(f"✅ Found user by first name match: {identifier} -> {user_data['first_name']}")
                return user_data
            
            # If still not found, check if it's a mention in the current message
            if update.message and update.message.entities:
                for entity in update.message.entities:
                    if entity.type == "text_mention" and entity.user:
                        # Check if this is the user we're looking for
                        if str(entity.user.id) == identifier or \
                           (entity.user.username and entity.user.username.lower() == identifier.lower()) or \
                           (entity.user.first_name and entity.user.first_name.lower() == identifier.lower()):
                            # Create or update user in database
                            user_data = {
                                'user_id': entity.user.id,
                                'username': entity.user.username,
                                'first_name': entity.user.first_name,
                                'last_name': entity.user.last_name,
                                'is_admin': entity.user.id in self.admin_ids,
                                'created_at': datetime.now(),
                                'last_active': datetime.now(),
                                'balance': 0
                            }
                            
                            # Update or insert user
                            users_collection.update_one(
                                {'user_id': entity.user.id},
                                {'$set': user_data, '$setOnInsert': {'created_at': datetime.now()}},
                                upsert=True
                            )
                            
                            # Retrieve the updated user data
                            user_data = users_collection.find_one({'user_id': entity.user.id})
                            logger.info(f"✅ Created/updated user from mention: {user_data}")
                            return user_data
            
            logger.warning(f"❌ Could not resolve user identifier: {identifier}")
            return None
        except Exception as e:
            logger.error(f"❌ Error resolving user mention: {e}")
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
            return None
        
    def _extract_mentions_from_message(self, message_text: str, message_entities: List = None) -> List[str]:
        """Extract user mentions from message using Telegram entities (more reliable than regex)"""
        mentions = []
        
        try:
            if not message_entities:
                logger.debug("No message entities found, falling back to regex parsing")
                return self._extract_mentions_with_regex(message_text)
            
            logger.debug(f"🔍 Processing {len(message_entities)} message entities")
            
            for entity in message_entities:
                logger.debug(f"🔍 Entity: {entity} | Type: {getattr(entity, 'type', 'unknown')}")
                
                # Handle @username mentions (MessageEntity.MENTION)
                if hasattr(entity, 'type') and (entity.type == 'mention' or (PYROGRAM_ENUMS_AVAILABLE and entity.type == MessageEntityType.MENTION)):
                    mention_text = message_text[entity.offset:entity.offset + entity.length]
                    mentions.append(mention_text)
                    logger.debug(f"Found @mention: {mention_text}")
                
                # Handle direct user mentions (when someone taps on a contact) (MessageEntity.TEXT_MENTION)
                elif hasattr(entity, 'type') and (entity.type == 'text_mention' or (PYROGRAM_ENUMS_AVAILABLE and entity.type == MessageEntityType.TEXT_MENTION)):
                    if hasattr(entity, 'user') and entity.user:
                        user = entity.user
                        # Create user entry if not exists
                        user_data = {
                            'user_id': user.id,
                            'username': user.username or user.first_name,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'is_admin': user.id in self.admin_ids,
                            'last_active': datetime.now(),
                            'balance': 0
                        }
                        
                        # Insert or update user
                        users_collection.update_one(
                            {'user_id': user.id},
                            {
                                '$set': user_data,
                                '$setOnInsert': {'created_at': datetime.now()}
                            },
                            upsert=True
                        )
                        
                        # Add the mention text (usually first name)
                        mention_text = message_text[entity.offset:entity.offset + entity.length]
                        mentions.append(mention_text)
                        logger.info(f"✅ Created/updated user from text_mention: {user.first_name}")
                        logger.debug(f"Found text_mention: {mention_text}")
                
                # Debug: log all entity types we encounter
                else:
                    logger.debug(f"🔍 Unhandled entity type: {getattr(entity, 'type', 'unknown')}")
            
            if not mentions:
                logger.debug("No entities found, falling back to regex parsing")
                return self._extract_mentions_with_regex(message_text)
            
            logger.info(f"✅ Extracted {len(mentions)} mentions using entities: {mentions}")
            return mentions
            
        except Exception as e:
            logger.error(f"❌ Error extracting mentions from entities: {e}")
            logger.debug("Falling back to regex parsing")
            return self._extract_mentions_with_regex(message_text)

    def _extract_mentions_with_regex(self, message_text: str) -> List[str]:
        """Fallback regex-based mention extraction for when entities are not available"""
        mentions = []
        try:
            # Extract username with or without @ (support both username and first name)
            matches = re.findall(r"@?([a-zA-Z0-9_\u00C0-\u017F\u0600-\u06FF\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF\u0B00-\u0B7F\u0B80-\u0BFF\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F\u0D80-\u0DFF\u0E00-\u0E7F\u0E80-\u0EFF\u0F00-\u0F7F\u0F80-\u0FFF\u1000-\u109F\u10A0-\u10FF\u1100-\u11FF\u1200-\u137F\u1380-\u139F\u13A0-\u13FF\u1400-\u167F\u1680-\u169F\u16A0-\u16FF\u1700-\u171F\u1720-\u173F\u1740-\u175F\u1760-\u177F\u1780-\u17FF\u1800-\u18AF\u1900-\u194F\u1950-\u197F\u1980-\u19DF\u19E0-\u19FF\u1A00-\u1A1F\u1A20-\u1AAF\u1AB0-\u1AFF\u1B00-\u1B7F\u1B80-\u1BBF\u1BC0-\u1BFF\u1C00-\u1C4F\u1C50-\u1C7F\u1C80-\u1CDF\u1CD0-\u1CFF\u1D00-\u1D7F\u1D80-\u1DBF\u1DC0-\u1DFF\u1E00-\u1EFF\u1F00-\u1FFF\u2000-\u206F\u2070-\u209F\u20A0-\u20CF\u20D0-\u20FF\u2100-\u214F\u2150-\u218F\u2190-\u21FF\u2200-\u22FF\u2300-\u23FF\u2400-\u243F\u2440-\u245F\u2460-\u24FF\u2500-\u257F\u2580-\u259F\u25A0-\u25FF\u2600-\u26FF\u2700-\u27BF\u27C0-\u27EF\u27F0-\u27FF\u2800-\u28FF\u2900-\u297F\u2980-\u29FF\u2A00-\u2AFF\u2B00-\u2BFF\u2C00-\u2C5F\u2C60-\u2C7F\u2C80-\u2CFF\u2D00-\u2D2F\u2D30-\u2D7F\u2D80-\u2DDF\u2DE0-\u2DFF\u2E00-\u2E7F\u2E80-\u2EFF\u2F00-\u2FDF\u2FE0-\u2FEF\u2FF0-\u2FFF\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u3100-\u312F\u3130-\u318F\u3190-\u319F\u31A0-\u31BF\u31C0-\u31EF\u31F0-\u31FF\u3200-\u32FF\u3300-\u33FF\u3400-\u4DBF\u4DC0-\u4DFF\u4E00-\u9FFF\uA000-\uA48F\uA490-\uA4CF\uA4D0-\uA4FF\uA500-\uA63F\uA640-\uA69F\uA6A0-\uA6FF\uA700-\uA71F\uA720-\uA7FF\uA800-\uA82F\uA830-\uA83F\uA840-\uA87F\uA880-\uA8DF\uA8E0-\uA8FF\uA900-\uA92F\uA930-\uA95F\uA960-\uA97F\uA980-\uA9DF\uA9E0-\uA9FF\uAA00-\uAA5F\uAA60-\uAA7F\uAA80-\uAADF\uAAE0-\uAAFF\uAB00-\uAB2F\uAB30-\uAB6F\uAB70-\uABBF\uABC0-\uABFF\uAC00-\uD7AF\uD7B0-\uD7FF\uD800-\uDB7F\uDB80-\uDBFF\uDC00-\uDFFF\uE000-\uF8FF\uF900-\uFAFF\uFB00-\uFB4F\uFB50-\uFDFF\uFE00-\uFE0F\uFE10-\uFE1F\uFE20-\uFE2F\uFE30-\uFE4F\uFE50-\uFE6F\uFE70-\uFEFF\uFF00-\uFFEF\uFFF0-\uFFFF]+)", message_text)
            for match in matches:
                username = match
                # Filter out common non-username words
                if len(username) > 2 and not username.lower() in ['full', 'table', 'game']:
                    mentions.append(username)
                    logger.debug(f"👥 Player found via regex: {username}")
            
            logger.info(f"✅ Extracted {len(mentions)} mentions using regex: {mentions}")
            return mentions
            
        except Exception as e:
            logger.error(f"❌ Error extracting mentions with regex: {e}")
            return []

    async def start_bot(self):
        """Start the main bot application"""
        try:
            logger.info("🚀 Starting Ludo Manager Bot...")
            
            # Create the Application and pass it your bot's token
            application = Application.builder().token(self.bot_token).build()
            
            # Store application for use in other methods
            self.application = application
            
            # Initialize Pyrogram in the main event loop (CRITICAL FIX)
            if self.pyrogram_available:
                await self.initialize_pyrogram()
            
            # Set up command handlers
            self.setup_handlers(application)
            
            # Add job queue for periodic tasks
            job_queue = application.job_queue
            if job_queue:
                # Schedule game expiration check every 5 minutes
                job_queue.run_repeating(
                    callback=self.expire_old_games,
                    interval=300,
                    first=60,
                    name="expire_games"
                )
                logger.info("✅ Game expiration monitor started (checks every 5 minutes)")
                
                # Schedule balance sheet update every 5 minutes
                job_queue.run_repeating(
                    callback=self.periodic_balance_sheet_update,
                    interval=300,
                    first=120,
                    name="balance_sheet_update"
                )
                logger.info("✅ Balance sheet auto-update started (updates every 5 minutes)")
            else:
                logger.warning("⚠️ JobQueue not available. Game expiration and balance sheet monitoring disabled.")
            
            # Start the Bot
            logger.info("🚀 Starting bot with polling...")
            await application.initialize()
            await application.start()
            await application.updater.start_polling(
                allowed_updates=["message", "edited_message", "callback_query"],
                drop_pending_updates=True
            )
            
            logger.info("✅ Bot is running and listening for updates")
            
            # Keep the bot running
            while True:
                await asyncio.sleep(3600)
                
        except Exception as e:
            logger.error(f"❌ Critical error starting bot: {e}")
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")

    async def initialize_pyrogram(self):
        """Initialize Pyrogram client properly in the main event loop"""
        if not self.pyrogram_available:
            logger.warning("⚠️ Pyrogram not available - edited message handling will be limited")
            return False
            
        try:
            logger.info("🔧 Initializing Pyrogram client in main event loop...")
            
            self.pyro_client = Client(
                "ludo_bot_pyrogram",
                api_id=self.api_id,
                api_hash=self.api_hash,
                bot_token=self.bot_token
            )
            
            # Start in the SAME event loop as the main bot
            await self.pyro_client.start()
            logger.info("✅ Pyrogram client started successfully in main event loop")
            
            # Set up handlers immediately after starting
            self._setup_pyrogram_handlers()
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Pyrogram client: {e}")
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
            self.pyro_client = None
            return False
    
    def _setup_pyrogram_handlers(self):
        """Set up Pyrogram handlers for edited messages"""
        if not self.pyro_client:
            logger.warning("⚠️ Cannot set up Pyrogram handlers - client not available")
            return
            
        try:
            @self.pyro_client.on_edited_message(
                pyrogram_filters.chat(int(self.group_id)) & 
                pyrogram_filters.user(self.admin_ids) & 
                pyrogram_filters.text
            )
            async def on_admin_edit_message(client, message):
                """Handle edited messages from admins in the group"""
                try:
                    logger.info(f"🔄 Received edited message: ID={message.id}")
                    logger.info(f"📝 Message content: {message.text}")
                    
                    # Convert message ID to string for consistent matching (CRITICAL FIX)
                    msg_id_str = str(message.id)
                    logger.info(f"🆔 Message ID (string): {msg_id_str}")
                    
                    # Log all active game IDs for debugging
                    active_game_ids = list(self.active_games.keys())
                    logger.info(f"🔍 Active game IDs: {active_game_ids}")
                    
                    # First, check if this message contains the "Full" keyword
                    # This helps confirm it's a game table message
                    if not re.search(r'\b(?:Full|full)\b', message.text):
                        logger.info("❌ Message doesn't contain 'Full' keyword - not a game table")
                        return
                    
                    # Check if it contains ✅ marks (indicating winners)
                    winner = self._extract_winner_from_edited_message(message.text)
                    
                    if not winner:
                        logger.info("❌ No winners found in edited message")
                        return
                    
                    logger.info(f"🏆 Winner extracted: {winner}")
                    
                    # Check if this is a game we're tracking
                    if msg_id_str in self.active_games:
                        logger.info(f"✅ Found matching game for edited message")
                        game_data = self.active_games.pop(msg_id_str)
                        
                        # Format winner as a single player for compatibility
                        winners = [{'username': winner, 'bet_amount': game_data['bet_amount']}]
                        
                        # Process the game result
                        await self.process_game_result_from_winner(game_data, winners, message)
                    else:
                        logger.warning("⚠️ No active game found for this edited message")
                        
                except Exception as e:
                    logger.error(f"❌ Error handling edited message: {e}")
                    logger.error(f"❌ Full traceback: {traceback.format_exc()}")
            
            logger.info("✅ Pyrogram edited message handler registered")
        except Exception as e:
            logger.error(f"❌ Failed to set up Pyrogram handlers: {e}")
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
    
    def _extract_winner_from_edited_message(self, message_text: str) -> Optional[str]:
        """Extract winner username from edited message text with proper error handling"""
        try:
            # Look for username with ✅ mark using multiple patterns
            patterns = [
                r'@([a-zA-Z0-9_]+)\s*✅',  # Username + space + checkmark
                r'@([a-zA-Z0-9_]+)✅',     # Username + checkmark (no space)
                r'@([a-zA-Z0-9_]+).*?✅',  # Username + anything + checkmark
                r'✅.*?@([a-zA-Z0-9_]+)',  # Checkmark + anything + username
                r'([a-zA-Z0-9_]+)\s*✅',   # Just username (no @) + checkmark
                r'([a-zA-Z0-9_]+)✅',      # Just username (no @) + checkmark (no space)
                r'([^\n]+)\s*✅',          # Any text (not containing newline) + checkmark
                r'✅\s*([^\n]+)'           # Checkmark followed by any text
            ]
            
            for pattern in patterns:
                match = re.search(pattern, message_text)
                if match:
                    # If we found a match with any text (not just alphanumeric), try to extract a username
                    username = match.group(1).strip()
                    # Remove any non-username characters (like punctuation)
                    username = re.sub(r'[^\w]', '', username)
                    logger.info(f"✅ Winner extracted using pattern '{pattern}': {username}")
                    return username
            
            # Try line-by-line approach
            lines = message_text.split('\n')
            for line in lines:
                if '✅' in line:
                    # Extract any text before the checkmark
                    match = re.search(r'(.*)\s*✅', line)
                    if match:
                        username = match.group(1).strip()
                        # Remove @ if present and clean up
                        username = username.lstrip('@')
                        username = re.sub(r'[^\w]', '', username)
                        logger.info(f"✅ Winner extracted from line '{line}': {username}")
                        return username
            
            logger.warning("❌ Could not extract winner from message: " + message_text)
            return None
        except Exception as e:
            logger.error(f"❌ Error in winner extraction: {e}")
            return None
    
    async def _extract_game_data_from_message(self, message_text: str, admin_user_id: int, message_id: int, chat_id: int, message_entities: List = None) -> Optional[Dict]:
        """Extract game data from message text using message entities for user mentions"""
        try:
            logger.info(f"📄 Processing game table message...")
            logger.info(f"📝 Message content: {message_text}")
            
            # First, extract all mentioned users from message entities (CRITICAL FIX)
            mentioned_users = []
            if message_entities:
                for entity in message_entities:
                    if hasattr(entity, 'type') and entity.type == "text_mention" and hasattr(entity, 'user') and entity.user:
                        # User mentioned by first name (no username)
                        mentioned_users.append({
                            "user_id": entity.user.id,
                            "username": entity.user.username or f"user_{entity.user.id}",
                            "first_name": entity.user.first_name,
                            "is_mention": True
                        })
                    elif hasattr(entity, 'type') and entity.type == "mention":
                        # User mentioned with username (@username)
                        mention_text = message_text[entity.offset:entity.offset + entity.length]
                        username = mention_text.lstrip('@')
                        mentioned_users.append({
                            "username": username,
                            "is_mention": True
                        })
            
            # Also check for usernames in the message text (for cases where users aren't properly mentioned)
            lines = message_text.strip().split("\n")
            usernames_from_text = []
            amount = None
    
            for line in lines:
                logger.debug(f"🔍 Processing line: {line}")
                
                # Look for amount with "Full" keyword
                if "full" in line.lower():
                    match = re.search(r"(\d+)\s*[Ff]ull", line)
                    if match:
                        amount = int(match.group(1))
                        logger.info(f"💰 Amount found: {amount}")
                else:
                    # Extract username with or without @
                    match = re.search(r"@?([a-zA-Z0-9_]+)", line)
                    if match:
                        username = match.group(1)
                        # Filter out common non-username words
                        if len(username) > 2 and not username.lower() in ['full', 'table', 'game']:
                            usernames_from_text.append(username)
                            logger.info(f"👥 Player found from text: {username}")
            
            # Combine mentioned users and users from text
            all_user_identifiers = []
            for user in mentioned_users:
                if 'user_id' in user:
                    all_user_identifiers.append(str(user['user_id']))
                elif 'username' in user:
                    all_user_identifiers.append(user['username'])
            
            all_user_identifiers.extend([u for u in usernames_from_text if u not in all_user_identifiers])
            
            # Verify users exist in our database
            valid_players = []
            for identifier in all_user_identifiers:
                # First try to resolve the user
                user_data = await self._resolve_user_mention(identifier, None)
                if user_data:
                    valid_players.append({
                        'username': user_data['username'],
                        'user_id': user_data['user_id'],
                        'first_name': user_data.get('first_name', '')
                    })
                    logger.info(f"✅ Valid player: {user_data['username']} (ID: {user_data['user_id']})")
            
            if not valid_players or not amount:
                logger.warning("❌ Invalid table format - missing usernames or amount")
                return None
    
            if len(valid_players) < 2:
                logger.warning("❌ Need at least 2 players for a game")
                return None
    
            # Create game data with STRING ID for consistency (CRITICAL FIX)
            game_id = f"game_{int(datetime.now().timestamp())}_{message_id}"
            game_data = {
                'game_id': game_id,
                'admin_user_id': admin_user_id,
                'admin_message_id': str(message_id),  # Store as string
                'chat_id': chat_id,
                'bet_amount': amount,
                'players': [{'username': player['username'], 'user_id': player['user_id'], 'bet_amount': amount} for player in valid_players],
                'total_amount': amount * len(valid_players),
                'status': 'active',
                'created_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(hours=1)
            }
            
            logger.info(f"🎮 Game data created: {game_data}")
            return game_data
        except Exception as e:
            logger.error(f"❌ Error extracting game data: {e}")
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
            return None
    
    async def detect_and_process_game_table(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Automatically detect and process game tables when admins send messages with 'Full' keyword"""
        if not self.is_configured_group(update.effective_chat.id):
            return
    
        # Only admins can create game tables
        if update.effective_user.id not in self.admin_ids:
            return
    
        # CRITICAL FIX: Check if this is a valid message update
        if not update.message or not update.message.text:
            return
    
        # Check if message contains "Full" keyword
        if "Full" in update.message.text or "full" in update.message.text:
            logger.info("📝 Detected potential game table from admin")
            
            # Extract game data using message entities
            game_data = await self._extract_game_data_from_message(
                update.message.text,
                update.effective_user.id,
                update.message.message_id,
                update.effective_chat.id,
                update.message.entities  # Pass message entities for mention detection
            )
            
            if game_data:
                # Store game with STRING ID for consistency (CRITICAL FIX)
                self.active_games[str(update.message.message_id)] = game_data
                
                logger.info(f"🎮 Game created and stored with message ID: {update.message.message_id}")
                logger.info(f"🔍 Current active games count: {len(self.active_games)}")
                
                # Send confirmation to group - FIXED: Properly escaped for MarkdownV2
                await self._send_group_confirmation(context, update.effective_chat.id)
                
                # Send winner selection message to admin's DM
                await self._send_winner_selection_to_admin(
                    game_data, 
                    update.effective_user.id
                )
            else:
                logger.warning("❌ Failed to extract game data from message")
    
    async def _send_table_rejection_message(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_text: str):
        """Send rejection message to group with auto-deletion after 5 seconds"""
        try:
            # Analyze the table to determine the specific issue
            lines = message_text.strip().split("\n")
            usernames = []
            amount = None
            
            for line in lines:
                if "full" in line.lower():
                    # Support both formats: "1000 Full", "1k Full", "10k Full", etc.
                    logger.debug(f"🔍 Rejection check - Processing amount line: '{line}'")
                    match = re.search(r"(\d+(?:k|K)?)\s*[Ff]ull", line)
                    if match:
                        amount_str = match.group(1)
                        logger.debug(f"🔍 Rejection check - Matched amount string: '{amount_str}'")
                        # Convert k format to actual number
                        if amount_str.lower().endswith('k'):
                            amount = int(amount_str[:-1]) * 1000
                            logger.debug(f"🔍 Rejection check - K format amount: {amount_str} = ₹{amount}")
                        else:
                            amount = int(amount_str)
                            logger.debug(f"🔍 Rejection check - Regular amount: {amount_str} = ₹{amount}")
                    else:
                        logger.warning(f"⚠️ Rejection check - No amount match found in line: '{line}'")
                else:
                    match = re.search(r"@?([a-zA-Z0-9_]+)", line)
                    if match:
                        username = match.group(1)
                        if len(username) > 2 and not username.lower() in ['full', 'table', 'game']:
                            usernames.append(username)
            
            # Determine the specific rejection reason
            if not usernames:
                rejection_message = "❌ **Invalid Table Format!**\n\nNo valid usernames found in the table.\n\nPlease send a table with exactly 2 different usernames and amount."
            elif len(usernames) != 2:
                rejection_message = f"❌ **Invalid Player Count!**\n\nFound {len(usernames)} players, but only 2 players are allowed.\n\nPlease send a table with exactly 2 different usernames and amount."
            elif len(set(usernames)) != len(usernames):
                rejection_message = "❌ **Duplicate Username Detected!**\n\nYou cannot play against yourself.\n\nPlease send a table with 2 different usernames and amount."
            elif not amount:
                rejection_message = "❌ **Invalid Amount!**\n\nNo valid amount found in the table.\n\nPlease send a table with exactly 2 different usernames and amount.\n\n**Supported formats:** 1000, 2000, 1k, 2k, 10k, 50k"
            else:
                rejection_message = "❌ **Invalid Table Format!**\n\nPlease send a table with exactly 2 different usernames and amount.\n\n**Supported formats:** 1000, 2000, 1k, 2k, 10k, 50k"
            
            # Send rejection message to group
            message = await context.bot.send_message(
                chat_id=chat_id,
                text=rejection_message,
                parse_mode="HTML"
            )
            
            # Auto-delete the rejection message after 5 seconds
            async def delete_rejection_message():
                try:
                    await asyncio.sleep(5)
                    await context.bot.delete_message(
                        chat_id=chat_id,
                        message_id=message.message_id
                    )
                    logger.info(f"🗑️ Deleted table rejection message {message.message_id}")
                except Exception as e:
                    logger.warning(f"Could not delete rejection message: {e}")
            
            # Create task for deletion (fire and forget)
            asyncio.create_task(delete_rejection_message())
            logger.info("✅ Table rejection message sent and scheduled for deletion")
            
        except Exception as e:
            logger.error(f"❌ Error sending table rejection message: {e}")

    async def _deduct_player_bets(self, game_data: Dict, context: ContextTypes.DEFAULT_TYPE = None) -> bool:
        """Deduct bet amounts from all players' balances when game is created"""
        try:
            logger.info(f"💳 Deducting bet amounts for game {game_data['game_id']}")
            
            successful_deductions = []
            failed_players = []
            
            for i, player in enumerate(game_data['players']):
                username = player['username']
                bet_amount = player['bet_amount']
                
                try:
                    # Use the new user mention resolver
                    user_data = await self._resolve_user_mention(username, context)
                    
                    if not user_data:
                        logger.error(f"❌ Player {username} not found in database")
                        failed_players.append(username)
                        continue
                    
                    # Deduct bet amount from user balance (allow negative balances)
                    old_balance = user_data.get('balance', 0)
                    new_balance = old_balance - bet_amount
                    
                    # Update user balance
                    users_collection.update_one(
                        {'_id': user_data['_id']},
                        {
                            '$set': {
                                'balance': new_balance,
                                'last_updated': datetime.now()
                            }
                        }
                    )
                    
                    # Record bet transaction
                    transaction_data = {
                        'user_id': user_data['user_id'],
                        'type': 'bet',
                        'amount': -bet_amount,  # Negative because it's a deduction
                        'description': f'Bet placed in game {game_data["game_id"]}',
                        'timestamp': datetime.now(),
                        'game_id': game_data['game_id'],
                        'old_balance': old_balance,
                        'new_balance': new_balance
                    }
                    transactions_collection.insert_one(transaction_data)
                    
                    # Update player data with user_id for later use
                    game_data['players'][i]['user_id'] = user_data['user_id']
                    
                    logger.info(f"✅ Deducted ₹{bet_amount} from {username} (₹{old_balance} → ₹{new_balance})")
                    successful_deductions.append(username)
                    
                    # Notify player about bet deduction
                    try:
                        # Generate link to the original game table message
                        table_link = self._generate_message_link(
                            game_data['chat_id'], 
                            int(game_data['admin_message_id'])
                        )
                        
                        await self.application.bot.send_message(
                            chat_id=user_data['user_id'],
                            text=(
                                f"🎮 <b>Game Joined!</b>\n\n"
                                f"💰 <b>Bet Amount:</b> ₹{bet_amount}\n"
                                f"📊 <b>Updated Balance:</b> ₹{new_balance}\n\n"
                                f"🔍 <a href='{table_link}'>View Game Table</a>\n\n"
                                f"Good luck! 🍀"
                            ),
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                        logger.info(f"✅ Bet notification sent to {username}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not notify {username} about bet: {e}")
                        
                except Exception as e:
                    logger.error(f"❌ Error deducting bet for {username}: {e}")
                    failed_players.append(username)
            
            if failed_players:
                logger.error(f"❌ Failed to deduct bets for players: {failed_players}")
                # Refund successful deductions since game creation failed
                await self._refund_failed_game(successful_deductions, game_data)
                return False
            
            logger.info(f"✅ Successfully deducted bets from all {len(successful_deductions)} players")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error in _deduct_player_bets: {e}")
            return False
    
    async def _refund_failed_game(self, successful_players: List[str], game_data: Dict):
        """Refund bet amounts if game creation fails"""
        try:
            logger.info(f"🔄 Refunding bets for failed game {game_data['game_id']}")
            
            for username in successful_players:
                user_data = await self._resolve_user_mention(username, None)
                
                if user_data:
                    bet_amount = next(p['bet_amount'] for p in game_data['players'] if p['username'] == username)
                    old_balance = user_data.get('balance', 0)
                    new_balance = old_balance + bet_amount
                    
                    # Refund the bet amount
                    users_collection.update_one(
                        {'_id': user_data['_id']},
                        {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                    )
                    
                    # Record refund transaction
                    transaction_data = {
                        'user_id': user_data['user_id'],
                        'type': 'refund',
                        'amount': bet_amount,
                        'description': f'Refund for failed game {game_data["game_id"]}',
                        'timestamp': datetime.now(),
                        'game_id': game_data['game_id']
                    }
                    transactions_collection.insert_one(transaction_data)
                    
                    logger.info(f"✅ Refunded ₹{bet_amount} to {username}")
                    
        except Exception as e:
            logger.error(f"❌ Error refunding failed game: {e}")
        finally:
            # Always attempt to refresh balance sheet after refunds
            try:
                if hasattr(self, 'application') and self.application:
                    await self.update_balance_sheet(None)
            except Exception as e:
                logger.warning(f"⚠️ Could not update balance sheet after failed-game refunds: {e}")
    
    async def _send_group_confirmation(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        """Send confirmation message to group with proper MarkdownV2 formatting"""
        try:
            # Properly escape special characters for MarkdownV2
            # Note: In MarkdownV2, special characters need to be escaped with a backslash
            confirmation_msg = (
                "✅ Game table received\\!\n\n"
                "🏆 \\*Winner Selection\\*\n"
                "• Click the winner button in your DM\n"
                "• Or edit this message and add ✅ after winner's username\n\n"
                "⏳ \\*Game Timer\\*: 60 minutes\n"
                "💰 \\*Total Pot\\*: Calculated automatically"
            )
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=confirmation_msg,
                parse_mode="MarkdownV2"  # Must be "MarkdownV2" for PTB v20+
            )
            logger.info("✅ Group confirmation message sent successfully")
        except Exception as e:
            logger.error(f"❌ Error sending group confirmation: {e}")
    
    async def _send_winner_selection_to_admin(self, game_data: Dict, admin_user_id: int):
        """Send winner selection message to admin's DM with proper formatting"""
        if not self.pyro_client or not self.pyro_client.is_connected:
            logger.warning("⚠️ Pyrogram client not available for sending winner selection")
            return
            
        try:
            # Create inline keyboard for winner selection
            keyboard = []
            for player in game_data['players']:
                username = player['username']
                # Create button text with proper escaping
                button_text = f"🏆 {username}"
                callback_data = f"winner_{game_data['game_id']}_{username}"
                
                keyboard.append([
                    InlineKeyboardButton(
                        button_text, 
                        callback_data=callback_data
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Prepare message - use HTML to avoid parse mode issues
            players_list = ", ".join([f"@{p['username']}" for p in game_data['players']])
            
            # CRITICAL FIX: Use HTML instead of Markdown to avoid parse mode errors
            html_message = (
                f"<b>🎮 Game Table Processed!</b>\n\n"
                f"<b>Players:</b> {players_list}\n"
                f"<b>Amount:</b> ₹{game_data['total_amount']}\n\n"
                f"<b>Select the winner:</b>"
            )
            
            # Send message to admin's DM
            await self.pyro_client.send_message(
                chat_id=admin_user_id,
                text=html_message,
                reply_markup=reply_markup,
                parse_mode="html"  # CRITICAL: Use "html" instead of "markdown"
            )
            logger.info(f"✅ Winner selection sent to admin {admin_user_id}")
        except Exception as e:
            logger.error(f"❌ Error sending winner selection to admin: {e}")
            logger.error(f"❌ Full error details: {str(e)}")
    
    async def process_game_result_from_winner(self, game_data: Dict, winners: List[Dict], message: Optional[Message] = None):
        """Process game results when winner is determined"""
        try:
            logger.info(f"🎯 Processing game result for {game_data['game_id']}")
            logger.info(f"🏆 Winners: {[w['username'] for w in winners]}")
            
            # Calculate total pot and commission
            total_pot = game_data['total_amount']
            commission_rate = 0.1  # 10% commission
            commission_amount = int(total_pot * commission_rate)
            winner_amount = total_pot - commission_amount
            
            logger.info(f"💰 Total Pot: ₹{total_pot}")
            logger.info(f"💼 Commission (10%): ₹{commission_amount}")
            logger.info(f"🎉 Winner Amount: ₹{winner_amount}")
            
            # Update winner's balance
            for winner in winners:
                # CRITICAL FIX: Comprehensive user resolution
                username = winner['username']
                
                # First try to find by username
                user_data = users_collection.find_one({'username': username})
                
                # If not found, try case-insensitive match
                if not user_data:
                    user_data = users_collection.find_one({'username': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}})
                
                # If still not found, try first name match
                if not user_data:
                    user_data = users_collection.find_one({'first_name': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}})
                
                # If still not found, try by user ID if it's numeric
                if not user_data and username.isdigit():
                    user_data = users_collection.find_one({'user_id': int(username)})
                
                if user_data:
                    # Update balance
                    new_balance = user_data.get('balance', 0) + winner_amount
                    
                    users_collection.update_one(
                        {'_id': user_data['_id']},
                        {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                    )
                    
                    # Record winning transaction
                    transaction_data = {
                        'user_id': user_data['user_id'],
                        'type': 'win',
                        'amount': winner_amount,
                        'description': f'Won game {game_data["game_id"]} (Commission: ₹{commission_amount})',
                        'timestamp': datetime.now(),
                        'game_id': game_data['game_id']
                    }
                    transactions_collection.insert_one(transaction_data)
                    
                    # Notify winner
                    try:
                        await self.application.bot.send_message(
                            chat_id=user_data['user_id'],
                            text=(
                                f"🎉 *Congratulations! You won!*\n\n"
                                f"*Game:* {game_data['game_id']}\n"
                                f"*Winnings:* ₹{winner_amount}\n"
                                f"*New Balance:* ₹{new_balance}"
                            ),
                            parse_mode="MarkdownV2"
                        )
                        logger.info(f"✅ Notification sent to winner {user_data['user_id']}")
                    except Exception as e:
                        logger.error(f"❌ Could not notify winner {user_data['user_id']}: {e}")
                else:
                    logger.warning(f"⚠️ Winner {username} not found in database")
            
            # Update game status
            games_collection.update_one(
                {'game_id': game_data['game_id']},
                {
                    '$set': {
                        'status': 'completed',
                        'winner': winners[0]['username'],
                        'winner_amount': winner_amount,
                        'admin_fee': commission_amount,
                        'completed_at': datetime.now()
                    }
                }
            )
            
            # Notify group
            try:
                # Format winner name - use first name if available
                winner_info = users_collection.find_one({'username': winners[0]['username']})
                display_name = winner_info['first_name'] if winner_info and 'first_name' in winner_info else winners[0]['username']
                
                group_message = (
                    f"🎉 *GAME COMPLETED!*\n\n"
                    f"🏆 *Winner:* {display_name}\n"
                    f"💰 *Winnings:* ₹{winner_amount}\n"
                    f"💼 *Commission:* ₹{commission_amount}\n"
                    f"🆔 *Game ID:* {game_data['game_id']}"
                )
                
                await self.application.bot.send_message(
                    chat_id=int(self.group_id),
                    text=group_message,
                    parse_mode="MarkdownV2"
                )
                logger.info("✅ Completion message sent to group")
            except Exception as e:
                logger.error(f"❌ Could not send completion message to group: {e}")
            
            logger.info("✅ Game result processed successfully")
            
        except Exception as e:
            logger.error(f"❌ Error processing game result: {e}")
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")

    def setup_handlers(self, application: Application):
        """Set up all command and message handlers"""
        # Command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("ping", self.ping_command))
        application.add_handler(CommandHandler("myid", self.myid_command))
        application.add_handler(CommandHandler("balance", self.balance_command))
        application.add_handler(CommandHandler("addbalance", self.addbalance_command))
        application.add_handler(CommandHandler("withdraw", self.withdraw_command))
        application.add_handler(CommandHandler("activegames", self.active_games_command))
        application.add_handler(CommandHandler("expiregames", self.expire_games_command))
        application.add_handler(CommandHandler("setcommission", self.set_commission_command))
        application.add_handler(CommandHandler("balancesheet", self.balance_sheet_command))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(CommandHandler("cancel", self.cancel_table_command))
        
        # Message handlers
        application.add_handler(MessageHandler(
            filters.TEXT & 
            filters.Chat(int(self.group_id)) & 
            filters.User(self.admin_ids),
            self.detect_and_process_game_table
        ))
        
        # Edited message handler (for cases where Pyrogram isn't available)
        application.add_handler(MessageHandler(
            filters.TEXT & 
            filters.Chat(int(self.group_id)) & 
            filters.User(self.admin_ids) &
            filters.UpdateType.EDITED_MESSAGE,
            self.handle_edited_message
        ))
        
        # Callback query handler for winner selection
        application.add_handler(CallbackQueryHandler(
            self.winner_selection_callback, 
            pattern=r'^winner_'
        ))

    async def handle_edited_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle edited messages (fallback when Pyrogram isn't available)"""
        try:
            logger.info("🔄 Processing edited message (PTB fallback)")
            logger.info(f"📝 Edited message content: {update.edited_message.text}")
            
            # First, check if this message contains the "Full" keyword
            if not re.search(r'\b(?:Full|full)\b', update.edited_message.text):
                logger.info("❌ Message doesn't contain 'Full' keyword - not a game table")
                return
            
            # Check if it contains ✅ marks (indicating winners)
            winner = self._extract_winner_from_edited_message(update.edited_message.text)
            
            if not winner:
                logger.info("❌ No winners found in edited message")
                return
            
            logger.info(f"🏆 Winner extracted: {winner}")
            
            # Convert message ID to string for consistent matching
            msg_id_str = str(update.edited_message.message_id)
            
            # Check if this is a game we're tracking
            if msg_id_str in self.active_games:
                logger.info(f"✅ Found matching game for edited message")
                game_data = self.active_games.pop(msg_id_str)
                
                # Format winner as a single player for compatibility
                winners = [{'username': winner, 'bet_amount': game_data['bet_amount']}]
                
                # Process the game result
                await self.process_game_result_from_winner(game_data, winners, None)
            else:
                logger.warning("⚠️ No active game found for this edited message")
                
        except Exception as e:
            logger.error(f"❌ Error handling edited message: {e}")
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        is_group = self.is_configured_group(update.effective_chat.id)
        
        # In group, only admins can use start command
        if is_group and user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use commands in the group. Please message me privately to start.")
            return
        
        try:
            # Create or update user in database
            user_data = {
                'user_id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_admin': user.id in self.admin_ids,
                'last_active': datetime.now(),
                'balance': 0
                # REMOVED created_at from here - it's only set on insert
            }
            
            # Update or insert user
            users_collection.update_one(
                {'user_id': user.id},
                {
                    '$set': user_data,
                    '$setOnInsert': {'created_at': datetime.now()}  # Only set on insert
                },
                upsert=True
            )
            
            # Send welcome message
            welcome_msg = (
                "🎮 Welcome to Ludo Group Manager!\n\n"
                "I'm your assistant for managing Ludo games in the group.\n\n"
                "📌 *Features:*\n"
                "• Automatic game table processing\n"
                "• Winner selection and balance updates\n"
                "• Commission management\n"
                "• Balance tracking\n"
                "• Game statistics\n\n"
                "Use /help for more commands."
            )
            
            if is_group:
                await self.send_group_response(update, context, welcome_msg)
            else:
                await update.message.reply_text(welcome_msg, parse_mode="markdown")
                
        except Exception as e:
            logger.error(f"❌ Error in start command: {e}")
            error_msg = "❌ Sorry, there was an error setting up your account. Please try again later."
            if is_group:
                await self.send_group_response(update, context, error_msg)
            else:
                await update.message.reply_text(error_msg)
            
    async def ping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ping command - simple health check"""
        user = update.effective_user
        user_id = user.id
        username = user.username or user.first_name
        is_admin = user_id in self.admin_ids
        
        message = (
            f"🏓 **Pong!**\n\n"
            f"✅ Bot is running\n"
            f"👤 **User:** @{username}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"👑 **Admin:** {'Yes' if is_admin else 'No'}\n"
            f"🔍 **Admin IDs:** {self.admin_ids}\n"
            f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        if self.is_configured_group(update.effective_chat.id):
            await self.send_group_response(update, context, message)
        else:
            await update.message.reply_text(message, parse_mode="HTML")

    async def myid_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /myid command - shows user's Telegram ID"""
        user = update.effective_user
        user_id = user.id
        username = user.username or user.first_name
        is_admin = user_id in self.admin_ids
        
        message = (
            f"👤 **Your Information:**\n\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"👤 **Username:** @{username}\n"
            f"👑 **Admin Status:** {'✅ Yes' if is_admin else '❌ No'}\n"
            f"🔍 **Admin IDs in bot:** {self.admin_ids}\n\n"
            f"💡 **Tip:** If you're not an admin, add your ID ({user_id}) to the ADMIN_IDS list in the bot code."
        )
        
        if self.is_configured_group(update.effective_chat.id):
            await self.send_group_response(update, context, message)
        else:
            await update.message.reply_text(message, parse_mode="HTML")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        is_admin = update.effective_user.id in self.admin_ids
        is_group = self.is_configured_group(update.effective_chat.id)
        
        if is_group and not is_admin:
            # Non-admin in group gets limited help
            help_message = (
                "🎮 Ludo Group Manager Bot\n\n"
                "This bot helps manage Ludo games in the group.\n\n"
                            "📌 *Available Commands:*\n"
            "/ping - Check if bot is running\n"
            "/start - Create your account\n"
            "/balance - Check your balance\n"
            "/myid - Show your Telegram ID\n"
            "/help - Show this help message\n\n"
                "⚠️ Note: Only admins can create games and manage balances."
            )
            await self.send_group_response(update, context, help_message)
            return
        
        # Admin help message
        help_message = (
            "🎮 Ludo Group Manager Bot - ADMIN PANEL\n\n"
            "📝 **NEW GAME PROCESS:**\n"
            "• Send table directly with 'Full' keyword\n"
            "• Bot automatically detects and processes\n"
            "• Bot sends winner selection buttons to your DM\n"
            "• Click winner button OR manually edit table to add ✅ for winners\n"
            "• Bot automatically processes results\n\n"
            "📝 **MANUAL EDITING (if buttons don't work):**\n"
            "• Edit your table message in the group\n"
            "• Add ✅ after the winner's username\n"
            "• Example: @player1 ✅\n"
            "• Bot will detect the edit and process results\n\n"
            "Example table format:\n"
            "@player1\n"
            "@player2\n"
            "400 Full\n\n"
            "**Amount formats supported:**\n"
            "• Regular: 1000, 2000, 5000\n"
            "• K format: 1k, 2k, 5k, 10k, 50k\n\n"
            "**User mentions supported:**\n"
            "• Username: @username\n"
            "• First name: @FirstName\n"
            "• Direct contact tap (no @ needed)\n"
            "• Works even without @ symbol\n"
            "• Supports international characters\n"
            "• Uses Telegram's native mention system\n\n"
            "⚠️ **IMPORTANT:** Only 2 players allowed per game. Same username cannot play against itself.\n\n"
            "📊 **ADMIN COMMANDS:**\n"
            "/ping - Check if bot is running\n"
            "/myid - Show your Telegram ID and admin status\n"
            "/activegames - Show all currently running games\n"
            "/addbalance @username amount - Add balance to user\n"
            "/withdraw @username amount - Withdraw from user\n"
                         "/setcommission @username percentage - Set custom commission rate (e.g., 10 for 10%)\n"
             "/expiregames - Manually expire old games\n"
             "/balancesheet - Create/update pinned balance sheet\n"
             "/stats - Show game and user statistics\n"
             "/cancel - Cancel a game table (reply to table message)"
        )
        
        if is_group:
            await self.send_group_response(update, context, help_message)
        else:
            await update.message.reply_text(help_message)

    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balance command"""
        user = update.effective_user
        is_group = self.is_configured_group(update.effective_chat.id)
        
        try:
            # Get user data with case-insensitive username matching
            user_data = users_collection.find_one({'user_id': user.id})
            
            if user_data:
                balance = user_data.get('balance', 0)
                
                # Format balance message based on whether it's positive, negative, or zero
                if balance > 0:
                    balance_message = f"💰 **Your Balance: ₹{balance}**"
                elif balance < 0:
                    balance_message = f"💸 **Your Balance: -₹{abs(balance)} (Debt)**"
                else:
                    balance_message = f"💰 **Your Balance: ₹{balance}**"
                
                if is_group:
                    await self.send_group_response(update, context, balance_message)
                else:
                    await update.message.reply_text(balance_message, parse_mode="HTML")
            else:
                balance_message = "❌ Account not found. Please use /start to create your account."
                if is_group:
                    await self.send_group_response(update, context, balance_message)
                else:
                    await update.message.reply_text(balance_message)
                    
        except Exception as e:
            logger.error(f"❌ Error in balance command: {e}")
            error_msg = "❌ Error retrieving balance. Please try again later."
            if is_group:
                await self.send_group_response(update, context, error_msg)
            else:
                await update.message.reply_text(error_msg)

    async def addbalance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addbalance command"""
        # Debug logging for admin check
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        logger.info(f"🔍 Admin check - User ID: {user_id}, Username: {username}")
        logger.info(f"🔍 Admin check - Admin IDs: {self.admin_ids}")
        logger.info(f"🔍 Admin check - Is admin: {user_id in self.admin_ids}")
        
        if user_id not in self.admin_ids:
            await self.send_group_response(update, context, f"❌ Only admins can use this command. Your ID: {user_id}")
            return
            
        try:
            if len(context.args) != 2:
                await self.send_group_response(update, context, "Usage: /addbalance @username amount")
                return
                
            username = context.args[0].replace('@', '')
            amount = int(context.args[1])
            
            if amount <= 0:
                await self.send_group_response(update, context, "❌ Amount must be positive!")
                return
                
            # Find user using the new mention resolver
            user_data = await self._resolve_user_mention(username, context)
            
            if not user_data:
                await self.send_group_response(update, context, f"❌ User @{username} not found in database!")
                return
                
            # Update balance
            old_balance = user_data.get('balance', 0)
            new_balance = old_balance + amount
            
            users_collection.update_one(
                {'user_id': user_data['user_id']},
                {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
            )
            
            # Record transaction
            transaction_data = {
                'user_id': user_data['user_id'],
                'type': 'manual_add',
                'amount': amount,
                'description': f'Manual balance addition by admin',
                'timestamp': datetime.now(),
                'admin_id': update.effective_user.id,
                'old_balance': old_balance,
                'new_balance': new_balance
            }
            transactions_collection.insert_one(transaction_data)
            
            # Prepare response
            response_msg = f"✅ Added ₹{amount} to @{username}\n"
            response_msg += f"💰 Balance: ₹{old_balance} → ₹{new_balance}"
            
            await self.send_group_response(update, context, response_msg)
            
            # Update balance sheet
            await self.update_balance_sheet(context)
            
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=user_data['user_id'],
                    text=(
                        f"💰 <b>Deposit Balance Added</b>\n\n"
                        f"₹{amount} your account by admin.\n\n"
                        f"<b>Update balance:</b> ₹{new_balance}"
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Could not notify user {user_data['user_id']}: {e}")
                
        except ValueError:
            await self.send_group_response(update, context, "❌ Invalid amount. Please enter a number.")
        except Exception as e:
            logger.error(f"Error in addbalance command: {e}")
            await self.send_group_response(update, context, f"❌ Error processing balance addition: {str(e)}")

    async def withdraw_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /withdraw command"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
            
        try:
            if len(context.args) != 2:
                await self.send_group_response(update, context, "Usage: /withdraw @username amount")
                return
                
            username = context.args[0].replace('@', '')
            amount = int(context.args[1])
            
            if amount <= 0:
                await self.send_group_response(update, context, "❌ Amount must be positive!")
                return
                
            # Find user using the new mention resolver
            user_data = await self._resolve_user_mention(username, context)
            
            if not user_data:
                await self.send_group_response(update, context, f"❌ User @{username} not found in database!")
                return
                
            # Get current balance and calculate new balance
            old_balance = user_data.get('balance', 0)
            new_balance = old_balance - amount
            
            # Update user balance
            users_collection.update_one(
                {'_id': user_data['_id']},
                {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
            )
            
            # Record transaction
            transaction_data = {
                'user_id': user_data['user_id'],
                'type': 'manual_withdraw',
                'amount': amount,
                'description': f'Manual balance withdrawal by admin',
                'timestamp': datetime.now(),
                'admin_id': update.effective_user.id,
                'old_balance': old_balance,
                'new_balance': new_balance
            }
            transactions_collection.insert_one(transaction_data)
            
            # Prepare detailed response message
            display_name = user_data.get('username', user_data.get('first_name', 'Unknown User'))
            
            if old_balance < 0:
                # User already had negative balance
                response_msg = (
                    f"✅ **Withdrew ₹{amount} from {display_name}**\n\n"
                    f"💰 **Previous Balance:** -₹{abs(old_balance)} (Debt)\n"
                    f"💸 **Amount Withdrawn:** ₹{amount}\n"
                    f"📊 **New Balance:** -₹{abs(new_balance)} (Debt)"
                )
            else:
                response_msg = (
                    f"✅ **Withdrew ₹{amount} from {display_name}**\n\n"
                    f"💰 **Previous Balance:** ₹{old_balance}\n"
                    f"💸 **Amount Withdrawn:** ₹{amount}\n"
                    f"📊 **New Balance:** ₹{new_balance}"
                )
            
            if new_balance < 0:
                response_msg += "\n\n⚠️ **User now has negative balance (debt)!**"
                
            await self.send_group_response(update, context, response_msg)
            
            # Update balance sheet
            await self.update_balance_sheet(context)
            
            # Notify user with detailed breakdown
            try:
                if old_balance < 0:
                    user_notification = (
                        f"💸 **Withdrawal Notice**\n\n"
                        f"₹{amount} has been withdrawn from your account by admin.\n\n"
                        f"📊 **Breakdown:**\n"
                        f"• Previous Balance: -₹{abs(old_balance)} (Debt)\n"
                        f"• Amount Withdrawn: ₹{amount}\n"
                        f"• New Balance: -₹{abs(new_balance)} (Debt)\n\n"
                        f"⚠️ **You now have a debt of ₹{abs(new_balance)}**"
                    )
                else:
                    user_notification = (
                        f"💸 **Withdrawal Notice**\n\n"
                        f"₹{amount} has been withdrawn from your account by admin.\n\n"
                        f"📊 **Breakdown:**\n"
                        f"• Previous Balance: ₹{old_balance}\n"
                        f"• Amount Withdrawn: ₹{amount}\n"
                        f"• New Balance: ₹{new_balance}"
                    )
                
                if new_balance < 0:
                    user_notification += f"\n\n⚠️ **You now have a debt of ₹{abs(new_balance)}**"
                
                await context.bot.send_message(
                    chat_id=user_data['user_id'],
                    text=user_notification,
                    parse_mode="HTML"
                )
                logger.info(f"✅ Withdrawal notification sent to {username}")
            except Exception as e:
                logger.warning(f"⚠️ Could not notify user {username}: {e}")
                
        except ValueError:
            await self.send_group_response(update, context, "❌ Invalid amount. Please enter a number.")
        except Exception as e:
            logger.error(f"Error in withdraw command: {e}")
            await self.send_group_response(update, context, f"❌ Error processing withdrawal: {str(e)}")

    async def active_games_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all currently running games"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
            
        try:
            # Get active games from database
            active_games = list(games_collection.find({'status': 'active'}))
            
            if not active_games:
                await self.send_group_response(update, context, "ℹ️ No active games running.")
                return
                
            games_list = "🎮 **ACTIVE GAMES**\n\n"
            
            for game in active_games:
                players = ", ".join([f"@{p['username']}" for p in game['players']])
                total_pot = sum(player['bet_amount'] for player in game['players'])
                time_left = game['expires_at'] - datetime.now()
                minutes_left = max(0, int(time_left.total_seconds() / 60))
                
                games_list += f"🆔 Game ID: {game['game_id']}\n"
                games_list += f"👥 Players: {players}\n"
                games_list += f"💰 Total Pot: ₹{total_pot}\n"
                games_list += f"⏰ Time Left: {minutes_left} minutes\n\n"
                
            await self.send_group_response(update, context, games_list)
            
        except Exception as e:
            logger.error(f"Error in active_games_command: {e}")
            await self.send_group_response(update, context, "❌ Error retrieving active games.")

    async def expire_games_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually expire old games (admin only)"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can expire games.")
            return
            
        try:
            await self.expire_old_games(context)
            await self.send_group_response(update, context, "✅ Checked and expired old games if any.")
        except Exception as e:
            logger.error(f"Error in expire_games_command: {e}")
            await self.send_group_response(update, context, "❌ Error expiring games.")

    async def set_commission_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set commission rate for a user"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
            
        try:
            if len(context.args) != 2:
                await self.send_group_response(update, context, "Usage: /setcommission @username percentage (e.g., /setcommission @user 10 for 10%)")
                return
                
            username = context.args[0].replace('@', '')
            commission_percentage = float(context.args[1])
            
            if commission_percentage < 0 or commission_percentage > 100:
                await self.send_group_response(update, context, "❌ Commission rate must be between 0 and 100 (e.g., 10 for 10%, 100 for 100%)")
                return
                
            # Convert percentage to decimal for storage (10% = 0.1)
            commission_rate = commission_percentage / 100
                
            # Find user using the new mention resolver
            user_data = await self._resolve_user_mention(username, context)
            
            if not user_data:
                await self.send_group_response(update, context, f"❌ User @{username} not found in database!")
                return
                
            # Update commission rate (store as decimal)
            users_collection.update_one(
                {'user_id': user_data['user_id']},
                {'$set': {'commission_rate': commission_rate}}
            )
            
            # Format rate for display
            display_rate = f"{int(commission_percentage)}%"
            
            await self.send_group_response(update, context, f"✅ Commission rate set to {display_rate} for @{username}")
            
        except ValueError:
            await self.send_group_response(update, context, "❌ Invalid rate. Please enter a number between 0 and 100 (e.g., 10 for 10%).")
        except Exception as e:
            logger.error(f"Error in set_commission_command: {e}")
            await self.send_group_response(update, context, f"❌ Error setting commission rate: {str(e)}")

    async def expire_old_games(self, context: ContextTypes.DEFAULT_TYPE):
        """Check and expire old games"""
        try:
            current_time = datetime.now()
            logger.info(f"⏰ Checking for expired games (current time: {current_time})")
            
            # Find expired games
            expired_games = list(games_collection.find({
                'status': 'active',
                'expires_at': {'$lt': current_time}
            }))
            
            logger.info(f"⏳ Found {len(expired_games)} expired games")
            
            for game in expired_games:
                logger.info(f"⌛ Expiring game: {game['game_id']}")
                
                # Refund all players
                for player in game['players']:
                    user_data = await self._resolve_user_mention(player['username'], context)
                    
                    if user_data:
                        refund_amount = player['bet_amount']
                        new_balance = user_data.get('balance', 0) + refund_amount
                        
                        users_collection.update_one(
                            {'_id': user_data['_id']},
                            {'$set': {'balance': new_balance, 'last_updated': current_time}}
                        )
                        
                        # Record refund transaction
                        transaction_data = {
                            'user_id': user_data['user_id'],
                            'type': 'refund',
                            'amount': refund_amount,
                            'description': f'Refund for expired game {game["game_id"]}',
                            'timestamp': current_time,
                            'game_id': game['game_id']
                        }
                        transactions_collection.insert_one(transaction_data)
                        
                        # Notify user
                        try:
                            # Generate link to the original game table message
                            table_link = self._generate_message_link(
                                game['chat_id'], 
                                int(game['admin_message_id'])
                            )
                            
                            await context.bot.send_message(
                                chat_id=user_data['user_id'],
                                text=(
                                    f"⌛ <b>Game Expired & Refunded</b>\n\n"
                                    f"💰 <b>Refund Amount:</b> ₹{refund_amount}\n"
                                    f"📊 <b>Updated Balance:</b> ₹{new_balance}\n\n"
                                    f"🔍 <a href='{table_link}'>View Game Table</a>"
                                ),
                                parse_mode="HTML",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            logger.warning(f"Could not notify user {user_data['user_id']}: {e}")
                
                # Update game status
                games_collection.update_one(
                    {'game_id': game['game_id']},
                    {
                        '$set': {
                            'status': 'expired',
                            'expired_at': current_time
                        }
                    }
                )
                
                # Remove from active games
                if str(game['admin_message_id']) in self.active_games:
                    del self.active_games[str(game['admin_message_id'])]
                
                # Notify group - DISABLED: No group notification needed
                # try:
                #     await context.bot.send_message(
                #         chat_id=int(self.group_id),
                #         text=(
                #             f"⌛ Game {game['game_id']} has expired and all players refunded.\n"
                #             f"Total refunded: ₹{game['total_amount']}"
                #         )
                #     )
                # except Exception as e:
                #     logger.error(f"Could not send expiration message to group: {e}")
                
                logger.info(f"ℹ️ Game {game['game_id']} expired - players notified via DM only")
            
            logger.info(f"✅ Expired {len(expired_games)} games")
            
            # After processing expired games, refresh balance sheet
            try:
                await self.update_balance_sheet(context)
            except Exception as e:
                logger.warning(f"⚠️ Could not update balance sheet after expiring games: {e}")
            
        except Exception as e:
            logger.error(f"❌ Error expiring games: {e}")
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")

    async def periodic_balance_sheet_update(self, context: ContextTypes.DEFAULT_TYPE):
        """Update balance sheet periodically"""
        try:
            logger.info("📊 Updating balance sheet...")
            await self.update_balance_sheet(context)
            logger.info("✅ Balance sheet updated successfully")
        except Exception as e:
            logger.error(f"❌ Error updating balance sheet: {e}")

    async def winner_selection_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle winner selection from inline buttons"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Parse callback data
            _, game_id, winner_username = query.data.split('_', 2)
            
            logger.info(f"🎯 Winner selected: {winner_username} for game {game_id}")
            
            # Find the game
            game_data = games_collection.find_one({'game_id': game_id})
            
            if not game_data or game_data['status'] != 'active':
                await query.edit_message_text("❌ Game not found or already completed.")
                return
                
            # Format winner as a single player
            winner = next(p for p in game_data['players'] if p['username'] == winner_username)
            winners = [{'username': winner_username, 'bet_amount': winner['bet_amount']}]
            
            # Process the game result
            await self.process_game_result_from_winner(game_data, winners, None)
            
            # Update the message
            await query.edit_message_text(
                f"✅ Winner selected: @{winner_username}\n"
                "Processing game results..."
            )
            
        except Exception as e:
            logger.error(f"❌ Error in winner selection: {e}")
            await query.edit_message_text(f"❌ Error processing winner: {str(e)}")

    async def balance_sheet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balancesheet command: delete old pinned, send fresh, and pin it"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        
        try:
            logger.info(f"📊 Balance sheet command received from admin {update.effective_user.id}")
            
            # If an old pinned balance sheet exists, try to unpin and delete it first
            if self.pinned_balance_msg_id:
                try:
                    # Unpin if possible (ignore failures)
                    try:
                        await context.bot.unpin_chat_message(
                            chat_id=int(self.group_id),
                            message_id=self.pinned_balance_msg_id
                        )
                    except Exception as unpin_err:
                        logger.warning(f"⚠️ Could not unpin old balance sheet: {unpin_err}")
                    
                    # Delete the old message (ignore failures)
                    try:
                        await context.bot.delete_message(
                            chat_id=int(self.group_id),
                            message_id=self.pinned_balance_msg_id
                        )
                        logger.info("🗑️ Deleted old pinned balance sheet message")
                    except Exception as del_err:
                        logger.warning(f"⚠️ Could not delete old balance sheet: {del_err}")
                    
                    # Clear stored ID in memory and DB
                    self.pinned_balance_msg_id = None
                    try:
                        balance_sheet_collection.update_one(
                            {'type': 'pinned_balance_sheet'},
                            {'$set': {'message_id': None, 'updated_at': datetime.now()}},
                            upsert=True
                        )
                    except Exception as db_err:
                        logger.warning(f"⚠️ Could not clear pinned balance id in DB: {db_err}")
                except Exception as cleanup_err:
                    logger.warning(f"⚠️ Cleanup error before recreating balance sheet: {cleanup_err}")
            
            # Create and pin a fresh balance sheet
            await self.create_new_balance_sheet(context)
            
            # Send confirmation message
            await self.send_group_response(update, context, "✅ Balance sheet refreshed and pinned successfully!")
            
        except Exception as e:
            logger.error(f"❌ Error in balance sheet command: {e}")
            await self.send_group_response(update, context, f"❌ Error updating balance sheet: {str(e)}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command to show game and user statistics"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        
        try:
            logger.info(f"📈 Stats command received from admin {update.effective_user.id}")
            
            # Generate comprehensive statistics
            stats_message = await self._generate_comprehensive_stats()
            
            # Send stats message
            await self.send_group_response(update, context, stats_message)
            
        except Exception as e:
            logger.error(f"❌ Error in stats command: {e}")
            await self.send_group_response(update, context, f"❌ Error generating statistics: {str(e)}")

    async def cancel_table_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel command to cancel a game table by replying to it"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        
        # Check if this is a reply to a message
        if not update.message.reply_to_message:
            await self.send_group_response(update, context, "❌ Please reply to a game table message with /cancel to cancel it.")
            return
        
        try:
            # Get the replied message ID
            replied_message_id = str(update.message.reply_to_message.message_id)
            logger.info(f"🔄 Cancel command received for message ID: {replied_message_id}")
            
            # Check if this message ID corresponds to an active game
            if replied_message_id not in self.active_games:
                await self.send_group_response(update, context, "❌ No active game found for this message. The game might have already been completed or expired.")
                return
            
            # Get the game data
            game_data = self.active_games[replied_message_id]
            logger.info(f"🎮 Cancelling game: {game_data['game_id']}")
            
            # Cancel the game and refund all players
            success = await self._cancel_and_refund_game(game_data, update.effective_user.id)
            
            if success:
                # Remove from active games
                del self.active_games[replied_message_id]
                
                # Update game status in database
                games_collection.update_one(
                    {'game_id': game_data['game_id']},
                    {
                        '$set': {
                            'status': 'cancelled',
                            'cancelled_at': datetime.now(),
                            'cancelled_by': update.effective_user.id
                        }
                    }
                )
                
                # Update balance sheet
                await self.update_balance_sheet(context)
                
                await self.send_group_response(update, context, f"✅ Game {game_data['game_id']} has been cancelled and all players refunded.")
                logger.info(f"✅ Game {game_data['game_id']} cancelled successfully")
            else:
                await self.send_group_response(update, context, "❌ Failed to cancel the game. Please try again.")
                
        except Exception as e:
            logger.error(f"❌ Error in cancel table command: {e}")
            await self.send_group_response(update, context, f"❌ Error cancelling game: {str(e)}")

    async def _cancel_and_refund_game(self, game_data: Dict, admin_id: int) -> bool:
        """Cancel a game and refund all players' bet amounts"""
        try:
            logger.info(f"🔄 Cancelling game {game_data['game_id']} and refunding players")
            
            successful_refunds = []
            failed_players = []
            
            for player in game_data['players']:
                username = player['username']
                bet_amount = player['bet_amount']
                
                try:
                    # Use the new user mention resolver
                    user_data = await self._resolve_user_mention(username, None)
                    
                    if not user_data:
                        logger.error(f"❌ Player {username} not found in database")
                        failed_players.append(username)
                        continue
                    
                    # Refund the bet amount
                    old_balance = user_data.get('balance', 0)
                    new_balance = old_balance + bet_amount
                    
                    # Update user balance
                    users_collection.update_one(
                        {'_id': user_data['_id']},
                        {
                            '$set': {
                                'balance': new_balance,
                                'last_updated': datetime.now()
                            }
                        }
                    )
                    
                    # Record refund transaction
                    transaction_data = {
                        'user_id': user_data['user_id'],
                        'type': 'refund',
                        'amount': bet_amount,
                        'description': f'Refund for cancelled game {game_data["game_id"]}',
                        'timestamp': datetime.now(),
                        'game_id': game_data['game_id'],
                        'admin_id': admin_id,
                        'old_balance': old_balance,
                        'new_balance': new_balance
                    }
                    transactions_collection.insert_one(transaction_data)
                    
                    logger.info(f"✅ Refunded ₹{bet_amount} to {username} (₹{old_balance} → ₹{new_balance})")
                    successful_refunds.append(username)
                    
                    # Notify player about game cancellation and refund
                    try:
                        # Generate link to the original game table message
                        table_link = self._generate_message_link(
                            game_data['chat_id'], 
                            int(game_data['admin_message_id'])
                        )
                        
                        await self.application.bot.send_message(
                            chat_id=user_data['user_id'],
                            text=(
                                f"🚫 <b>Game Cancelled & Refunded</b>\n\n"
                                f"💰 <b>Refund Amount:</b> ₹{bet_amount}\n"
                                f"📊 <b>Updated Balance:</b> ₹{new_balance}\n\n"
                                f"🔍 <a href='{table_link}'>View Game Table</a>"
                            ),
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                        logger.info(f"✅ Cancellation notification sent to {username}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not notify {username} about cancellation: {e}")
                        
                except Exception as e:
                    logger.error(f"❌ Error refunding {username}: {e}")
                    failed_players.append(username)
            
            if failed_players:
                logger.error(f"❌ Failed to refund players: {failed_players}")
                return False
            
            logger.info(f"✅ Successfully refunded all {len(successful_refunds)} players")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error in _cancel_and_refund_game: {e}")
            return False

    async def _generate_comprehensive_stats(self) -> str:
        """Generate comprehensive statistics including games, users, and transactions"""
        try:
            current_time = datetime.now()
            
                        # Game Statistics
            total_games = games_collection.count_documents({})
            active_games_count = games_collection.count_documents({'status': 'active'})
            completed_games = games_collection.count_documents({'status': 'completed'})
            expired_games = games_collection.count_documents({'status': 'expired'})
            cancelled_games = games_collection.count_documents({'status': 'cancelled'})
            
            # User Statistics
            total_users = users_collection.count_documents({})
            users_with_balance = users_collection.count_documents({'balance': {'$gt': 0}})
            
            # Calculate total balances
            pipeline = [
                {'$group': {
                    '_id': None,
                    'total_positive': {'$sum': {'$cond': [{'$gt': ['$balance', 0]}, '$balance', 0]}},
                    'total_negative': {'$sum': {'$cond': [{'$lt': ['$balance', 0]}, '$balance', 0]}},
                    'total_balance': {'$sum': '$balance'}
                }}
            ]
            balance_stats = list(users_collection.aggregate(pipeline))
            
            if balance_stats:
                total_positive = balance_stats[0]['total_positive']
                total_negative = balance_stats[0]['total_negative']
                total_balance = balance_stats[0]['total_balance']
            else:
                total_positive = total_negative = total_balance = 0
            
            # Transaction Statistics (last 30 days)
            thirty_days_ago = current_time - timedelta(days=30)
            recent_transactions = transactions_collection.count_documents({
                'timestamp': {'$gte': thirty_days_ago}
            })
            
            # Commission earned (from completed games) - Time-based breakdown
            # Today's commission
            today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = current_time.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            today_commission_pipeline = [
                {'$match': {
                    'status': 'completed',
                    'completed_at': {'$gte': today_start, '$lte': today_end}
                }},
                {'$group': {
                    '_id': None,
                    'total_commission': {'$sum': '$admin_fee'}
                }}
            ]
            today_commission_stats = list(games_collection.aggregate(today_commission_pipeline))
            today_commission = today_commission_stats[0]['total_commission'] if today_commission_stats else 0
            
            # Yesterday's commission
            yesterday_start = today_start - timedelta(days=1)
            yesterday_end = today_start - timedelta(seconds=1)
            
            yesterday_commission_pipeline = [
                {'$match': {
                    'status': 'completed',
                    'completed_at': {'$gte': yesterday_start, '$lte': yesterday_end}
                }},
                {'$group': {
                    '_id': None,
                    'total_commission': {'$sum': '$admin_fee'}
                }}
            ]
            yesterday_commission_stats = list(games_collection.aggregate(yesterday_commission_pipeline))
            yesterday_commission = yesterday_commission_stats[0]['total_commission'] if yesterday_commission_stats else 0
            
            # This month's commission
            month_start = current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            month_commission_pipeline = [
                {'$match': {
                    'status': 'completed',
                    'completed_at': {'$gte': month_start, '$lte': current_time}
                }},
                {'$group': {
                    '_id': None,
                    'total_commission': {'$sum': '$admin_fee'}
                }}
            ]
            month_commission_stats = list(games_collection.aggregate(month_commission_pipeline))
            month_commission = month_commission_stats[0]['total_commission'] if month_commission_stats else 0
            
            # Total commission (all time)
            total_commission_pipeline = [
                {'$match': {'status': 'completed'}},
                {'$group': {
                    '_id': None,
                    'total_commission': {'$sum': '$admin_fee'}
                }}
            ]
            total_commission_stats = list(games_collection.aggregate(total_commission_pipeline))
            total_commission = total_commission_stats[0]['total_commission'] if total_commission_stats else 0
            
                        # Top 5 users by balance (positive and negative)
            top_positive_users = list(users_collection.find(
                {'balance': {'$gt': 0}},
                {'username': 1, 'first_name': 1, 'balance': 1}
            ).sort('balance', -1).limit(5))
            
            top_negative_users = list(users_collection.find(
                {'balance': {'$lt': 0}},
                {'username': 1, 'first_name': 1, 'balance': 1}
            ).sort('balance', 1).limit(5))  # Sort ascending for negative (closest to 0 first)
            
            # Recent game activity breakdown
            seven_days_ago = current_time - timedelta(days=7)
            recent_games = games_collection.count_documents({
                'created_at': {'$gte': seven_days_ago}
            })
            
            # Today's games
            today_games = games_collection.count_documents({
                'created_at': {'$gte': today_start, '$lte': today_end}
            })
            
            # Yesterday's games
            yesterday_games = games_collection.count_documents({
                'created_at': {'$gte': yesterday_start, '$lte': yesterday_end}
            })
            
            # This month's games
            month_games = games_collection.count_documents({
                'created_at': {'$gte': month_start, '$lte': current_time}
            })
            
            # Format statistics message
            stats_message = (
                "📊 **LUDO BOT STATISTICS**\n\n"
                
                                "🎮 **GAME STATISTICS:**\n"
                f"• Total Games: {total_games}\n"
                f"• Active Games: {active_games_count}\n"
                f"• Completed Games: {completed_games}\n"
                f"• Expired Games: {expired_games}\n"
                f"• Cancelled Games: {cancelled_games}\n\n"
                
                "📅 **GAME ACTIVITY:**\n"
                f"• Today: {today_games} games\n"
                f"• Yesterday: {yesterday_games} games\n"
                f"• This Month: {month_games} games\n"
                f"• Last 7 days: {recent_games} games\n\n"
                
                "👥 **USER STATISTICS:**\n"
                f"• Total Users: {total_users}\n"
                f"• Users with Balance: {users_with_balance}\n"
                f"• Total Positive Balance: ₹{total_positive}\n"
                f"• Total Negative Balance: ₹{total_negative}\n"
                f"• Net Balance: ₹{total_balance}\n\n"
                
                "💰 **COMMISSION EARNINGS:**\n"
                f"• Today: ₹{today_commission}\n"
                f"• Yesterday: ₹{yesterday_commission}\n"
                f"• This Month: ₹{month_commission}\n"
                f"• Total (All Time): ₹{total_commission}\n\n"
                
                "📈 **TRANSACTION ACTIVITY:**\n"
                f"• Transactions (30 days): {recent_transactions}\n\n"
                
                                "🏆 **TOP 5 USERS BY POSITIVE BALANCE:**\n"
            )
            
            if top_positive_users:
                for i, user in enumerate(top_positive_users, 1):
                    name = user.get('first_name', user.get('username', 'Unknown'))
                    balance = user.get('balance', 0)
                    stats_message += f"{i}. {name}: ₹{balance}\n"
            else:
                stats_message += "No users with positive balance\n"
            
            stats_message += "\n💸 **TOP 5 USERS BY NEGATIVE BALANCE (DEBT):**\n"
            
            if top_negative_users:
                for i, user in enumerate(top_negative_users, 1):
                    name = user.get('first_name', user.get('username', 'Unknown'))
                    balance = user.get('balance', 0)
                    stats_message += f"{i}. {name}: -₹{abs(balance)} (Debt)\n"
            else:
                stats_message += "No users with negative balance\n"
            
            stats_message += f"\n🕐 Generated: {current_time.strftime('%d/%m/%Y %H:%M:%S')}"
            
            return stats_message
            
        except Exception as e:
            logger.error(f"❌ Error generating comprehensive stats: {e}")
            return f"❌ Error generating statistics: {str(e)}"

    async def send_group_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        """Send response in group with auto-deletion of both command and response after 5 seconds"""
        if self.is_configured_group(update.effective_chat.id):
            # In group - send with auto-deletion and delete user command too
            message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text
            )
            
            # Delete the user's command message after 5 seconds
            async def delete_user_command():
                try:
                    await asyncio.sleep(5)
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )
                    logger.info(f"🗑️ Deleted user command message {update.message.message_id}")
                except Exception as e:
                    logger.warning(f"Could not delete user command: {e}")
            
            # Delete the bot's response after 5 seconds (same as user command)
            async def delete_bot_response():
                try:
                    await asyncio.sleep(5)
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=message.message_id
                    )
                    logger.info(f"🗑️ Deleted bot response message {message.message_id}")
                except Exception as e:
                    logger.warning(f"Could not delete bot response: {e}")
            
            # Create tasks for deletion (fire and forget)
            asyncio.create_task(delete_user_command())
            asyncio.create_task(delete_bot_response())
        else:
            # Private chat - send normally
            await update.message.reply_text(text)

    def _load_pinned_message_id(self):
        """Load the pinned balance sheet message ID from database"""
        try:
            result = balance_sheet_collection.find_one({'type': 'pinned_balance_sheet'})
            if result:
                self.pinned_balance_msg_id = result.get('message_id')
                logger.info(f"📌 Loaded pinned balance sheet message ID: {self.pinned_balance_msg_id}")
            else:
                logger.info("📌 No pinned balance sheet found in database")
        except Exception as e:
            logger.error(f"❌ Error loading pinned message ID: {e}")

    async def generate_balance_sheet_content(self) -> str:
        """Generate the balance sheet content with all users and their balances"""
        try:
            # Get all users and sort alphabetically by name
            users = list(users_collection.find({}, {
                'username': 1, 'balance': 1, 'first_name': 1
            }))
            
            # Sort alphabetically by account name (first_name or username)
            users.sort(key=lambda user: (user.get('first_name', user.get('username', 'Unknown User'))).lower())
            
            if not users:
                return "#BALANCESHEET\n\n❌ No users found in database"
            
            # Header with game rules and info
            content = "#BALANCESHEET GAme RuLes - ✅BET_RULE DEPOSIT=QR/NUMBER ✅SOMYA_000 MESSAGE\n"
            content += "=" * 50 + "\n\n"
            
            # Only show actual users from database with their current balances
            for user in users:
                # Use first name (account name) instead of username
                account_name = user.get('first_name', user.get('username', 'Unknown User'))
                balance = user.get('balance', 0)
                
                # Format with appropriate emoji based on balance status
                if balance > 0:
                    content += f"💰 {account_name} = ₹{balance}\n"
                elif balance < 0:
                    content += f"💸 {account_name} = -₹{abs(balance)} (Debt)\n"
                else:
                    content += f"🔺{account_name} = ₹{balance}\n"
            
            content += "\n" + "=" * 50 + "\n"
            content += f"📊 Total Users: {len(users)}"
            
            # Add timestamp
            content += f"\n🕐 Last Updated: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
            
            return content
            
        except Exception as e:
            logger.error(f"❌ Error generating balance sheet: {e}")
            return "#BALANCESHEET - Error generating balance sheet"

    async def update_balance_sheet(self, context: ContextTypes.DEFAULT_TYPE = None):
        """Update the pinned balance sheet message"""
        try:
            if not self.pinned_balance_msg_id:
                logger.warning("⚠️ No pinned message ID found, creating new balance sheet")
                await self.create_new_balance_sheet(context)
                return
            
            # Generate new content
            balance_sheet_content = await self.generate_balance_sheet_content()
            
            # Update the pinned message
            if context:
                await context.bot.edit_message_text(
                    chat_id=int(self.group_id),
                    message_id=self.pinned_balance_msg_id,
                    text=balance_sheet_content
                )
            elif self.application:
                await self.application.bot.edit_message_text(
                    chat_id=int(self.group_id),
                    message_id=self.pinned_balance_msg_id,
                    text=balance_sheet_content
                )
            else:
                logger.error("❌ No bot context available for updating balance sheet")
                return
            
            logger.info("✅ Pinned balance sheet updated successfully")
            
        except Exception as e:
            logger.error(f"❌ Error updating pinned balance sheet: {e}")
            logger.warning("⚠️ Attempting to create new balance sheet...")
            await self.create_new_balance_sheet(context)

    async def create_new_balance_sheet(self, context: ContextTypes.DEFAULT_TYPE = None):
        """Create and pin a new balance sheet message"""
        try:
            # Generate balance sheet content
            balance_sheet_content = await self.generate_balance_sheet_content()
            
            # Send the message
            if context:
                message = await context.bot.send_message(
                    chat_id=int(self.group_id),
                    text=balance_sheet_content
                )
            elif self.application:
                message = await self.application.bot.send_message(
                    chat_id=int(self.group_id),
                    text=balance_sheet_content
                )
            else:
                logger.error("❌ No bot context available for creating balance sheet")
                return
            
            logger.info(f"✅ Balance sheet message sent with ID: {message.message_id}")
            
            # Pin the message
            try:
                # First, attempt to unpin all just in case multiple pins exist
                try:
                    if context:
                        await context.bot.unpin_all_chat_messages(chat_id=int(self.group_id))
                    elif self.application:
                        await self.application.bot.unpin_all_chat_messages(chat_id=int(self.group_id))
                except Exception as unpin_all_err:
                    logger.warning(f"⚠️ Could not unpin all messages (may not be necessary): {unpin_all_err}")
                
                if context:
                    await context.bot.pin_chat_message(
                        chat_id=int(self.group_id),
                        message_id=message.message_id,
                        disable_notification=True
                    )
                elif self.application:
                    await self.application.bot.pin_chat_message(
                        chat_id=int(self.group_id),
                        message_id=message.message_id,
                        disable_notification=True
                    )
                
                logger.info("📌 Balance sheet pinned successfully")
                
                # Store the message ID
                self.pinned_balance_msg_id = message.message_id
                balance_sheet_collection.update_one(
                    {'type': 'pinned_balance_sheet'},
                    {'$set': {'message_id': message.message_id, 'updated_at': datetime.now()}},
                    upsert=True
                )
                
                logger.info(f"💾 Balance sheet ID stored: {message.message_id}")
                
            except Exception as pin_error:
                logger.error(f"❌ Could not pin balance sheet: {pin_error}")
                logger.error(f"📊 Bot might not have admin permissions in group {self.group_id}")
                
                # Still store the message ID even if pinning failed
                self.pinned_balance_msg_id = message.message_id
                balance_sheet_collection.update_one(
                    {'type': 'pinned_balance_sheet'},
                    {'$set': {'message_id': message.message_id, 'updated_at': datetime.now()}},
                    upsert=True
                )
            
            logger.info(f"✅ New balance sheet created with ID: {message.message_id}")
            
        except Exception as e:
            logger.error(f"❌ Error creating balance sheet: {e}")
            logger.error(f"🔍 Group ID: {self.group_id}")

async def main():
    """Main entry point"""
    # Configuration - replace with your actual values
    BOT_TOKEN = "8205474950:AAG9aRfiLDC6-I0wwjf4vbNtU-zUTsPfwFI"
    API_ID = 18274091
    API_HASH = "97afe4ab12cb99dab4bed25f768f5bbc"
    GROUP_ID = -1002849354155
    ADMIN_IDS = [2109516065]
    
    print(f"🚀 Starting Ludo Manager Bot...")
    print(f"🔑 Bot Token: {BOT_TOKEN[:20]}...")
    print(f"📱 API ID: {API_ID}")
    print(f"🔐 API Hash: {API_HASH[:20]}...")
    print(f"👥 Group ID: {GROUP_ID}")
    print(f"👑 Admin IDs: {ADMIN_IDS}")
    
    # Create and start the bot
    bot = LudoManagerBot(BOT_TOKEN, API_ID, API_HASH, GROUP_ID, ADMIN_IDS)
    await bot.start_bot()

if __name__ == "__main__":
    try:
        logger.info("Starting application...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
