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
from pyrogram.enums import ParseMode as PyroParseMode

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

    def _extract_user_from_entities(self, message_entities: List, message_text: str) -> Optional[Dict]:
        """Extract user information directly from message entities (most reliable method)"""
        if not message_entities:
            return None
        
        for entity in message_entities:
            # Handle @username mentions (entity.type == "mention")
            if hasattr(entity, 'type') and entity.type == "mention":
                mention_text = message_text[entity.offset:entity.offset + entity.length]
                username = mention_text.lstrip('@')
                logger.info(f"🔍 Found @mention entity: {username}")
                
                # Find user by username in database
                user_data = users_collection.find_one({'username': {'$regex': f'^{username}$', '$options': 'i'}})
                if user_data:
                    # Add display_name field for consistency
                    user_data['display_name'] = user_data.get('username', username)
                    logger.info(f"✅ Found user by @mention: {username}")
                    return user_data
                else:
                    logger.warning(f"⚠️ User not found by @mention: {username}")
                    return None
            
            # Handle direct user mentions by tapping contact (entity.type == "text_mention")
            elif hasattr(entity, 'type') and entity.type == "text_mention":
                user = getattr(entity, 'user', None)
                if user:
                    logger.info(f"🔍 Found text_mention entity: {user.first_name} (ID: {user.id})")
                    
                    # Check if user exists in database
                    user_data = users_collection.find_one({'user_id': user.id})
                    if user_data:
                        # Add display_name field for consistency
                        first_name = user_data.get('first_name', user.first_name)
                        last_name = user_data.get('last_name', user.last_name)
                        user_data['display_name'] = f"{first_name}"
                        if last_name:
                            user_data['display_name'] += f" {last_name}"
                        logger.info(f"✅ Found existing user by text_mention: {user.first_name}")
                        return user_data
                    else:
                        # Create new user entry
                        display_name = f"{user.first_name}"
                        if user.last_name:
                            display_name += f" {user.last_name}"
                        
                        new_user_data = {
                            'user_id': user.id,
                            'username': user.username or f"user_{user.id}",
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'display_name': display_name,
                            'is_admin': user.id in self.admin_ids,
                            'last_active': datetime.now()
                        }
                        
                        result = users_collection.insert_one({**new_user_data, 'balance': 0, 'created_at': datetime.now()})
                        new_user_data['_id'] = result.inserted_id
                        
                        logger.info(f"✅ Created new user from text_mention: {user.first_name} (ID: {user.id})")
                        return new_user_data
                else:
                    logger.warning(f"⚠️ text_mention entity has no user object")
        
        return None

    async def _resolve_user_mention(self, identifier: str, context: ContextTypes.DEFAULT_TYPE = None) -> Optional[Dict]:
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
            if context and hasattr(context, 'bot'):
                try:
                    # Try to get chat member info (this works for users in the group)
                    chat_members = await context.bot.get_chat_administrators(int(self.group_id))
                    for member in chat_members:
                        if (member.user.username and member.user.username.lower() == identifier.lower()) or \
                           (member.user.first_name and member.user.first_name.lower() == identifier.lower()):
                            # Create user entry if not exists
                            user_data = {
                                'user_id': member.user.id,
                                'username': member.user.username or member.user.first_name,
                                'first_name': member.user.first_name,
                                'last_name': member.user.last_name,
                                'is_admin': member.user.id in self.admin_ids,
                                'last_active': datetime.now()
                            }
                            
                            # Insert or update user
                            users_collection.update_one(
                                {'user_id': member.user.id},
                                {
                                    '$set': user_data,
                                    '$setOnInsert': {'created_at': datetime.now(), 'balance': 0}
                                },
                                upsert=True
                            )
                            
                            logger.info(f"✅ Created/updated user from group member: {member.user.first_name}")
                            return user_data
                except Exception as e:
                    logger.warning(f"⚠️ Could not get group member info: {e}")
            
            # If still not found, check if it's a mention in the current message
            # Note: 'update' is not available in this scope; rely only on provided context/DB
            if False:
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
                                'last_active': datetime.now()
                            }
                            
                            # Update or insert user
                            users_collection.update_one(
                                {'user_id': entity.user.id},
                                {'$set': user_data, '$setOnInsert': {'created_at': datetime.now(), 'balance': 0}},
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
        """Extract user mentions from message using Telegram entity types (string-based)"""
        mentions = []
        
        try:
            if not message_entities:
                logger.debug("No message entities found, falling back to regex parsing")
                return self._extract_mentions_with_regex(message_text)
            
            logger.debug(f"🔍 Processing {len(message_entities)} message entities")
            
            for entity in message_entities:
                logger.debug(f"🔍 Entity: {entity} | Type: {getattr(entity, 'type', 'unknown')}")
                
                # Handle @username mentions (entity.type == "mention")
                if hasattr(entity, 'type') and entity.type == "mention":
                    mention_text = message_text[entity.offset:entity.offset + entity.length]
                    mentions.append(mention_text)
                    logger.debug(f"Found @mention: {mention_text}")
                
                # Handle direct user mentions by tapping contact (entity.type == "text_mention")
                elif hasattr(entity, 'type') and entity.type == "text_mention":
                    # ent.user carries the User object with real Telegram user data
                    user = getattr(entity, 'user', None)
                    if user:
                        # Create user entry if not exists
                        user_data = {
                            'user_id': user.id,
                            'username': user.username or user.first_name,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'is_admin': user.id in self.admin_ids,
                            'last_active': datetime.now()
                        }
                        
                        # Insert or update user
                        users_collection.update_one(
                            {'user_id': user.id},
                            {
                                '$set': user_data,
                                '$setOnInsert': {'created_at': datetime.now(), 'balance': 0}
                            },
                            upsert=True
                        )
                        
                        # Add the mention text (usually first name)
                        mention_text = message_text[entity.offset:entity.offset + entity.length]
                        mentions.append(mention_text)
                        logger.info(f"✅ Created/updated user from text_mention: {user.first_name} (ID: {user.id})")
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
                # job_queue.run_repeating(
                #     callback=self.periodic_balance_sheet_update,
                #     interval=300,
                #     first=120,
                #     name="balance_sheet_update"
                # )
                # logger.info("✅ Balance sheet auto-update started (updates every 5 minutes)")
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
            
            # Set start time for uptime tracking
            self._start_time = datetime.now()
            
            logger.info("✅ Bot is running and listening for updates")
            
            # Notify all admins about bot startup
            try:
                await self.notify_all_admins_startup(application.context)
                logger.info("✅ Startup notifications sent to all admins")
            except Exception as e:
                logger.error(f"❌ Error sending startup notifications: {e}")
            
            # Schedule periodic health check every 6 hours
            if hasattr(application, 'job_queue') and application.job_queue:
                application.job_queue.run_repeating(
                    callback=self.periodic_health_check,
                    interval=21600,  # 6 hours in seconds
                    first=3600,      # First check after 1 hour
                    name="health_check"
                )
                logger.info("✅ Periodic health check started (every 6 hours)")
            
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
                    winner_info = self._extract_winner_from_edited_message(message.text, message.entities)
                    
                    if not winner_info:
                        logger.info("❌ No winners found in edited message")
                        return
                    
                    logger.info(f"🏆 Winner info extracted: {winner_info}")
                    
                    # Check if this is a game we're tracking
                    if msg_id_str in self.active_games:
                        logger.info(f"✅ Found matching game for edited message")
                        game_data = self.active_games.pop(msg_id_str)
                        
                                    # Find the actual winner player from the game data using priority matching
                        winner_player = None
                        logger.info(f"🔍 Looking for winner '{winner_info}' in game players: {game_data['players']}")
                        
                        # Priority 1: Match by user_id (exact match for text_mention)
                        if winner_info.get('type') == 'text_mention' and winner_info.get('user_id'):
                            target_user_id = winner_info['user_id']
                            for player in game_data['players']:
                                if player.get('user_id') == target_user_id:
                                    winner_player = player
                                    logger.info(f"🎯 Winner found by user_id (exact): {winner_player}")
                                    break
                        
                        # Priority 2: Match by username (case-insensitive for @mention and fallback_mention)
                        if not winner_player and winner_info.get('type') in ['mention', 'fallback_mention']:
                            target_username = winner_info.get('username', '').lower()
                            logger.info(f"🔍 Matching @mention by username: '{target_username}'")
                            for player in game_data['players']:
                                player_username = player.get('username', '').lower()
                                if player_username == target_username:
                                    winner_player = player
                                    logger.info(f"🎯 Winner found by username (case-insensitive): {winner_player}")
                                    break
                        
                        # Priority 3: For fallback (plain text), try username match first, then display_name
                        if not winner_player and winner_info.get('type') == 'fallback':
                            target_name = winner_info.get('username', '').lower()
                            logger.info(f"🔍 Fallback matching for: '{target_name}'")
                            
                            # Try username match first (exact)
                            for player in game_data['players']:
                                player_username = player.get('username', '').lower()
                                if player_username == target_name:
                                    winner_player = player
                                    logger.info(f"🎯 Winner found by fallback username match: {winner_player}")
                                    break
                            
                            # If not found by username, try display_name match
                            if not winner_player:
                                for player in game_data['players']:
                                    player_display_name = player.get('display_name', '').lower()
                                    # Full match first
                                    if player_display_name == target_name:
                                        winner_player = player
                                        logger.info(f"🎯 Winner found by fallback display_name (full match): {winner_player}")
                                        break
                                    # Partial match (check if target is contained in player name)
                                    elif target_name in player_display_name:
                                        winner_player = player
                                        logger.info(f"🎯 Winner found by fallback display_name (partial match): {winner_player}")
                                        break
                            
                            # If still not found, try fuzzy matching with first names
                            if not winner_player:
                                for player in game_data['players']:
                                    player_first_name = player.get('display_name', '').split()[0].lower() if player.get('display_name') else ''
                                    if player_first_name and target_name in player_first_name:
                                        winner_player = player
                                        logger.info(f"🎯 Winner found by fallback first name match: {winner_player}")
                                        break
                        
                        if winner_player:
                            logger.info(f"✅ Found winner player: {winner_player}")
                            winners = [{
                                'username': winner_player['username'], 
                                'bet_amount': winner_player['bet_amount'], 
                                'user_id': winner_player.get('user_id'),
                                'display_name': winner_player.get('display_name', '')
                            }]
                        else:
                            logger.warning(f"⚠️ Winner '{winner_info}' not found in game players, using fallback")
                            logger.warning(f"⚠️ Available players: {[p.get('username', 'no_username') for p in game_data['players']]}")
                            
                            # Try to find the winner in the database even if not in game players
                            fallback_username = winner_info.get('username', winner_info.get('display_name', 'Unknown'))
                            fallback_user_data = None
                            
                            # Try to find user by username, first name, or display name
                            if fallback_username:
                                fallback_user_data = users_collection.find_one({'username': fallback_username})
                                if not fallback_user_data:
                                    fallback_user_data = users_collection.find_one({'username': {'$regex': f'^{re.escape(fallback_username)}', '$options': 'i'}})
                                if not fallback_user_data:
                                    fallback_user_data = users_collection.find_one({'first_name': {'$regex': f'^{re.escape(fallback_username)}', '$options': 'i'}})
                                if not fallback_user_data:
                                    fallback_user_data = users_collection.find_one({'display_name': {'$regex': f'^{re.escape(fallback_username)}', '$options': 'i'}})
                            
                            if fallback_user_data:
                                logger.info(f"✅ Found fallback winner in database: {fallback_user_data}")
                                winners = [{
                                    'username': fallback_user_data['username'],
                                    'bet_amount': game_data['bet_amount'],
                                    'user_id': fallback_user_data.get('user_id'),
                                    'display_name': fallback_user_data.get('display_name', fallback_user_data.get('first_name', ''))
                                }]
                            else:
                                # Last resort: use the fallback username
                                logger.warning(f"⚠️ Winner not found in database, using fallback username: {fallback_username}")
                                winners = [{'username': fallback_username, 'bet_amount': game_data['bet_amount']}]
                        
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
    
    def _extract_winner_from_edited_message(self, message_text: str, message_entities: List = None) -> Optional[Dict]:
        """Extract winner information from edited message using entities + line with ✅"""
        try:
            logger.info(f"🔍 Extracting winner from message: {message_text}")
            logger.info(f"🔍 Message entities: {message_entities}")
            
            # Split message into lines and find lines with ✅
            lines = message_text.split('\n')
            winner_info = None
            
            for line_num, line in enumerate(lines):
                if '✅' in line:
                    logger.info(f"🔍 Found ✅ in line {line_num}: '{line}'")
                    
                    # Extract text before ✅
                    match = re.search(r'(.*)\s*✅', line)
                    if not match:
                        continue
                    
                    winner_text = match.group(1).strip()
                    logger.info(f"🔍 Winner text extracted: '{winner_text}'")
                    
                    # Clean the winner text by removing any remaining checkmarks and extra characters
                    cleaned_winner_text = re.sub(r'✅+', '', winner_text).strip()
                    logger.info(f"🔍 Cleaned winner text: '{cleaned_winner_text}'")
                    
                    # Check if this line has entities (text_mention or mention)
                    if message_entities:
                        # Find entities that overlap with this line
                        line_start = message_text.find(line)
                        line_end = line_start + len(line)
                        
                        for entity in message_entities:
                            entity_start = getattr(entity, 'offset', 0)
                            entity_end = entity_start + getattr(entity, 'length', 0)
                            
                            # Check if entity overlaps with the line containing ✅
                            if (entity_start < line_end and entity_end > line_start):
                                logger.info(f"🔍 Found overlapping entity: type={getattr(entity, 'type', 'unknown')}")
                                
                                if getattr(entity, 'type', '') == "text_mention":
                                    # Gold standard: we have the user ID
                                    user = getattr(entity, 'user', None)
                                    if user:
                                        winner_info = {
                                            'type': 'text_mention',
                                            'user_id': user.id,
                                            'username': user.username or f"user_{user.id}",
                                            'display_name': cleaned_winner_text
                                        }
                                        logger.info(f"✅ Winner found via text_mention: {winner_info}")
                                        return winner_info
                                
                                elif getattr(entity, 'type', '') == "mention":
                                    # @username mention - extract username correctly
                                    mention_text = message_text[entity_start:entity_end]
                                    username = mention_text.lstrip('@')
                                    winner_info = {
                                        'type': 'mention',
                                        'username': username,
                                        'display_name': cleaned_winner_text  # Use cleaned text for display
                                    }
                                    logger.info(f"✅ Winner found via @mention: {winner_info}")
                                    return winner_info
                    
                    # Fallback: no entities, parse the cleaned text before ✅
                    if cleaned_winner_text.startswith('@'):
                        # It's an @mention without entity data
                        username = cleaned_winner_text.lstrip('@')
                        winner_info = {
                            'type': 'fallback_mention',
                            'username': username,
                            'display_name': cleaned_winner_text
                        }
                    else:
                        # Plain text fallback - use cleaned text
                        winner_info = {
                            'type': 'fallback',
                            'username': cleaned_winner_text,
                            'display_name': cleaned_winner_text
                        }
                    logger.info(f"✅ Winner found via fallback: {winner_info}")
                    return winner_info
            
            logger.warning("❌ No winner found in message")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error in winner extraction: {e}")
            return None
    
    async def _extract_game_data_from_message(self, message_text: str, admin_user_id: int, message_id: int, chat_id: int, message_entities: List = None) -> Optional[Dict]:
        """Extract game data from message text using message entities for user mentions"""
        try:
            logger.info(f"📄 Processing game table message...")
            logger.info(f"📝 Message content: {message_text}")
            
            # First, extract all mentioned users from message entities using Telegram entity types
            mentioned_users = []
            if message_entities:
                for entity in message_entities:
                    # Handle @username mentions (entity.type == "mention")
                    if hasattr(entity, 'type') and entity.type == "mention":
                        mention_text = message_text[entity.offset:entity.offset + entity.length]
                        username = mention_text.lstrip('@')
                        mentioned_users.append({
                            "username": username,
                            "is_mention": True,
                            "entity_type": "mention"
                        })
                        logger.debug(f"Found @mention entity: {username}")
                    
                    # Handle direct user mentions by tapping contact (entity.type == "text_mention")
                    elif hasattr(entity, 'type') and entity.type == "text_mention":
                        user = getattr(entity, 'user', None)
                        if user:
                            # Create/update user entry automatically
                            user_data = {
                                'user_id': user.id,
                                'username': user.username or f"user_{user.id}",
                                'first_name': user.first_name,
                                'last_name': user.last_name,
                                'is_admin': user.id in self.admin_ids,
                                'last_active': datetime.now()
                            }
                            
                            # Insert or update user
                            users_collection.update_one(
                                {'user_id': user.id},
                                {
                                    '$set': user_data,
                                    '$setOnInsert': {'created_at': datetime.now(), 'balance': 0}
                                },
                                upsert=True
                            )
                            
                            mentioned_users.append({
                                "user_id": user.id,
                                "username": user.username or f"user_{user.id}",
                                "first_name": user.first_name,
                                "is_mention": True,
                                "entity_type": "text_mention",
                                "telegram_user_id": user.id
                            })
                            logger.info(f"✅ Created/updated user from game table text_mention: {user.first_name} (ID: {user.id})")
                            logger.debug(f"Found text_mention entity: {user.first_name} (ID: {user.id})")
                    
                    # Debug: log all entity types we encounter
                    else:
                        logger.debug(f"🔍 Unhandled entity type: {getattr(entity, 'type', 'unknown')}")
            
            # Also check for usernames in the message text (for cases where users aren't properly mentioned)
            lines = message_text.strip().split("\n")
            usernames_from_text = []
            amount = None
    
            for line in lines:
                logger.debug(f"🔍 Processing line: {line}")
                
                # Look for amount with "Full" keyword
                if "full" in line.lower():
                    # Support both formats: "1000 Full", "1k Full", "10k Full", etc.
                    # Pattern: matches numbers like 1000, 1k, 2k, 10k, 20k, 15k
                    match = re.search(r"(\d+(?:k|K)?)\s*[Ff]ull", line)
                    if match:
                        amount_str = match.group(1)
                        logger.info(f"💰 Amount string found: {amount_str}")
                        
                        # Convert k format to actual number
                        if amount_str.lower().endswith('k'):
                            # Remove 'k' and multiply by 1000
                            number_part = int(amount_str[:-1])
                            amount = number_part * 1000
                            logger.info(f"💰 K format amount: {amount_str} = ₹{amount}")
                        else:
                            # Regular number format
                            amount = int(amount_str)
                            logger.info(f"💰 Regular amount: {amount_str} = ₹{amount}")
                        
                        # Validate amount (must be positive and reasonable)
                        if amount <= 0:
                            logger.warning(f"⚠️ Invalid amount: {amount} (must be positive)")
                            amount = None
                        elif amount > 1000000:  # 1 million limit
                            logger.warning(f"⚠️ Amount too high: {amount} (max ₹1,000,000)")
                            amount = None
                        else:
                            logger.info(f"✅ Valid amount: ₹{amount}")
                else:
                    # Extract username with or without @
                    match = re.search(r"@?([a-zA-Z0-9_]+)", line)
                    if match:
                        username = match.group(1)
                        # Filter out common non-username words
                        if len(username) > 2 and not username.lower() in ['full', 'table', 'game']:
                            usernames_from_text.append({
                                "username": username,
                                "entity_type": "text_regex",
                                "is_mention": False
                            })
                            logger.info(f"👥 Player found from text: {username}")
            
            # Combine mentioned users and users from text
            all_user_identifiers = []
            for user in mentioned_users:
                if 'user_id' in user:
                    all_user_identifiers.append(str(user['user_id']))
                elif 'username' in user:
                    all_user_identifiers.append(user['username'])
            
            # Handle text-based usernames (now in dict format)
            for user_info in usernames_from_text:
                username = user_info['username']
                if username not in [u.get('username', '') for u in mentioned_users]:
                    all_user_identifiers.append(username)
            
            # Log summary of found users
            logger.info(f"🔍 Found {len(mentioned_users)} mentioned users and {len(usernames_from_text)} text-based users")
            for user in mentioned_users:
                if user.get('entity_type') == 'text_mention':
                    logger.info(f"   📱 Contact tap: {user.get('first_name', 'Unknown')} (ID: {user.get('user_id', 'Unknown')})")
                elif user.get('entity_type') == 'mention':
                    logger.info(f"   @ Username: {user.get('username', 'Unknown')}")
            
            # Verify users exist in our database and prevent duplicates
            valid_players = []
            seen_user_ids = set()
            seen_usernames = set()
            
            for identifier in all_user_identifiers:
                # First try to resolve the user
                user_data = await self._resolve_user_mention(identifier, None)
                if user_data:
                    user_id = user_data['user_id']
                    username = user_data['username']
                    first_name = user_data.get('first_name', '')
                    last_name = user_data.get('last_name', '')
                    
                    # Create display name (e.g., "Gopal M")
                    display_name = f"{first_name}"
                    if last_name:
                        display_name += f" {last_name}"
                    
                    # Check if we already have this user (by user_id or username)
                    if user_id in seen_user_ids or username in seen_usernames:
                        logger.warning(f"⚠️ Duplicate user detected: {username} (ID: {user_id}) - skipping")
                        continue
                    
                    valid_players.append({
                        'user_id': user_id,
                        'username': username,
                        'display_name': display_name,
                        'bet_amount': amount
                    })
                    seen_user_ids.add(user_id)
                    seen_usernames.add(username)
                    logger.info(f"✅ Valid player: {display_name} (ID: {user_id}, username: {username})")
            
            if not valid_players or not amount:
                logger.warning("❌ Invalid table format - missing usernames or amount")
                return None
    
            if len(valid_players) < 2:
                logger.warning("❌ Need at least 2 players for a game")
                return None
    
            # Create game data with STRING ID for consistency (CRITICAL FIX)
            game_id = f"game_{int(datetime.now().timestamp())}_{message_id}"
            
            # Get commission rates for each player
            player_commission_rates = {}
            for player in valid_players:
                username = player['username']
                user_id = player.get('user_id')
                
                # Find user in database to get their commission rate
                user_data = None
                if user_id:
                    user_data = users_collection.find_one({'user_id': int(user_id)})
                
                if not user_data:
                    user_data = users_collection.find_one({'username': username})
                
                if not user_data:
                    user_data = users_collection.find_one({'username': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}})
                
                if user_data:
                    # Get user's personal commission rate, default to 5% if not set
                    commission_rate = user_data.get('commission_rate', 0.05)
                    player_commission_rates[username] = commission_rate
                    logger.info(f"💰 Player {username} commission rate: {int(commission_rate * 100)}%")
                else:
                    # Default commission rate if user not found
                    player_commission_rates[username] = 0.05
                    logger.warning(f"⚠️ Player {username} not found, using default 5% commission")
            
            game_data = {
                'game_id': game_id,
                'admin_user_id': admin_user_id,
                'admin_message_id': str(message_id),  # Store as string
                'chat_id': chat_id,
                'bet_amount': amount,
                'players': valid_players,  # Already in correct format with user_id, username, display_name, bet_amount
                'total_amount': amount * len(valid_players),
                'status': 'active',
                'created_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(hours=1),
                'player_commission_rates': player_commission_rates  # Store commission rates for each player
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
            logger.info(f"🔍 Message entities: {update.message.entities}")
            
            # Log detailed entity information for game tables
            if update.message.entities:
                logger.info(f"🔍 Game table has {len(update.message.entities)} entities:")
                for i, entity in enumerate(update.message.entities):
                    logger.info(f"   Entity {i+1}: type={getattr(entity, 'type', 'unknown')}, "
                              f"offset={getattr(entity, 'offset', 'unknown')}, "
                              f"length={getattr(entity, 'length', 'unknown')}")
                    if hasattr(entity, 'user') and entity.user:
                        logger.info(f"     User: ID={entity.user.id}, "
                                  f"Username={entity.user.username or 'None'}, "
                                  f"FirstName={entity.user.first_name or 'None'}")
            else:
                logger.info("🔍 Game table has no entities")
            
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
                
                # Store game in database
                games_collection.insert_one(game_data)
                logger.info(f"✅ Game {game_data['game_id']} created successfully")
                
                # Removed noisy group confirmation message per user request
                # await self._send_group_confirmation(context, update.effective_chat.id)
                
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
            
            # Get the bet amount from game data
            bet_amount = game_data['bet_amount']  # Each player's bet
            
            # Get commission rates from game data (already stored when game was created)
            player_commission_rates = game_data.get('player_commission_rates', {})
            
            # Process winners first to get their commission rates
            winner_commission_rates = {}
            for winner in winners:
                username = winner['username']
                
                # Use commission rate from game data if available, otherwise fallback to user lookup
                if username in player_commission_rates:
                    commission_rate = player_commission_rates[username]
                    winner_commission_rates[username] = commission_rate
                    logger.info(f"💰 Winner {username} commission rate from game data: {int(commission_rate * 100)}%")
                else:
                    # Fallback: find winner's user data to get their commission rate
                    user_id = winner.get('user_id')
                    user_data = None
                    
                    if user_id and str(user_id).isdigit():
                        user_data = users_collection.find_one({'user_id': int(user_id)})
                    
                    if not user_data:
                        user_data = users_collection.find_one({'username': username})
                    
                    if not user_data:
                        user_data = users_collection.find_one({'username': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}})
                    
                    if user_data:
                        # Get winner's personal commission rate, default to 5% if not set
                        personal_commission_rate = user_data.get('commission_rate', 0.05)
                        winner_commission_rates[username] = personal_commission_rate
                        logger.info(f"💰 Winner {username} commission rate from user data: {int(personal_commission_rate * 100)}%")
                    else:
                        # Default commission rate if user not found
                        winner_commission_rates[username] = 0.05
                        logger.warning(f"⚠️ Winner {username} not found, using default 5% commission")
            
            # Calculate commission and profit for each winner
            winner_profits = {}
            total_commission = 0
            
            for winner in winners:
                username = winner['username']
                commission_rate = winner_commission_rates[username]
                commission_amount = int(bet_amount * commission_rate)
                winner_profit = bet_amount - commission_amount
                
                winner_profits[username] = winner_profit
                total_commission += commission_amount
                
                logger.info(f"💰 Winner {username}: Bet ₹{bet_amount}, Commission ₹{commission_amount} ({int(commission_rate * 100)}%), Profit ₹{winner_profit}")
            
            logger.info(f"💼 Total Commission: ₹{total_commission}")
            
            # First, process losers - deduct their bet amount
            winner_usernames = [w['username'] for w in winners]
            winner_user_ids = [w.get('user_id') for w in winners if w.get('user_id')]
            
            losers = []
            for player in game_data['players']:
                # Exclude if username matches
                if player['username'] in winner_usernames:
                    continue
                # Exclude if user_id matches (prevents double-counting when username doesn't match)
                if player.get('user_id') in winner_user_ids:
                    continue
                losers.append(player)
            
            logger.info(f"😔 Processing {len(losers)} losers: {[l['username'] for l in losers]}")
            
            # Deduct bet amount from each loser
            for loser in losers:
                username = loser['username']
                user_id = loser.get('user_id')
                
                logger.info(f"🔍 Processing loser: username='{username}', user_id='{user_id}'")
                
                user_data = None
                
                # First, if we have a user_id (from text_mention entity), use it directly
                if user_id and str(user_id).isdigit():
                    user_data = users_collection.find_one({'user_id': int(user_id)})
                    if user_data:
                        logger.info(f"✅ Found loser by user_id: {user_id}")
                    else:
                        logger.warning(f"⚠️ User ID {user_id} not found in database")
                
                # If not found by user_id, try username-based lookup
                if not user_data:
                    # First try to find by username
                    user_data = users_collection.find_one({'username': username})
                    
                    # If not found, try case-insensitive match
                    if not user_data:
                        user_data = users_collection.find_one({'username': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}})
                    
                    # If still not found, try first name match
                    if not user_data:
                        user_data = users_collection.find_one({'first_name': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}})
                    
                    # If still not found, try partial first name match (for cases like "Mahli" matching "Mahli M")
                    if not user_data:
                        user_data = users_collection.find_one({'first_name': {'$regex': f'^{re.escape(username)}', '$options': 'i'}})
                    
                    # If still not found, try display_name match
                    if not user_data:
                        user_data = users_collection.find_one({'display_name': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}})
                    
                    if user_data:
                        logger.info(f"✅ Found loser by username: {username}")
                    else:
                        logger.warning(f"⚠️ Loser {username} not found in database")
                
                if user_data:
                    # Deduct bet amount from loser's balance
                    old_balance = user_data.get('balance', 0)
                    new_balance = old_balance - bet_amount
                    
                    users_collection.update_one(
                        {'_id': user_data['_id']},
                        {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                    )
                    
                    # Record losing transaction
                    transaction_data = {
                        'user_id': user_data['user_id'],
                        'type': 'bet_loss',
                        'amount': -bet_amount,  # Negative because it's a deduction
                        'description': f'Lost game {game_data["game_id"]} - bet deducted',
                        'timestamp': datetime.now(),
                        'game_id': game_data['game_id'],
                        'old_balance': old_balance,
                        'new_balance': new_balance
                    }
                    transactions_collection.insert_one(transaction_data)
                    
                    logger.info(f"💸 Deducted ₹{bet_amount} from loser {username} (₹{old_balance} → ₹{new_balance})")
                    
                    # Notify loser about the loss
                    try:
                        # Generate link to the original game table message
                        table_link = self._generate_message_link(
                            game_data['chat_id'], 
                            int(game_data['admin_message_id'])
                        )
                        
                        await self.application.bot.send_message(
                            chat_id=user_data['user_id'],
                            text=(
                                f"😔 <b>You Lost!</b>\n\n"
                                f"💰 <b>Amount Lost:</b> ₹{bet_amount}\n"
                                f"📊 <b>Updated Balance:</b> ₹{new_balance}\n\n"
                                f"🔍 <a href='{table_link}'>View Game Table</a>\n\n"
                                f"Better luck next time! 🍀"
                            ),
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                        logger.info(f"✅ Loser notification sent to {user_data['user_id']}")
                    except Exception as e:
                        logger.error(f"❌ Could not notify loser {user_data['user_id']}: {e}")
                else:
                    logger.warning(f"⚠️ Loser {username} not found in database")
            
            # Now, update winner's balance - add only the profit (winner keeps their original bet)
            for winner in winners:
                # CRITICAL FIX: Enhanced user resolution for both entity types
                username = winner['username']
                user_id = winner.get('user_id')  # This will be present for text_mention users
                
                logger.info(f"🔍 Processing winner: username='{username}', user_id='{user_id}'")
                
                user_data = None
                
                # First, if we have a user_id (from text_mention entity), use it directly
                if user_id and str(user_id).isdigit():
                    user_data = users_collection.find_one({'user_id': int(user_id)})
                    if user_data:
                        logger.info(f"✅ Found winner by user_id: {user_id}")
                    else:
                        logger.warning(f"⚠️ User ID {user_id} not found in database")
                
                # If not found by user_id, try username-based lookup
                if not user_data:
                    # First try to find by username
                    user_data = users_collection.find_one({'username': username})
                    
                    # If not found, try case-insensitive match
                    if not user_data:
                        user_data = users_collection.find_one({'username': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}})
                    
                    # If still not found, try first name match
                    if not user_data:
                        user_data = users_collection.find_one({'first_name': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}})
                    
                    # If still not found, try partial first name match (for cases like "Mahli" matching "Mahli M")
                    if not user_data:
                        user_data = users_collection.find_one({'first_name': {'$regex': f'^{re.escape(username)}', '$options': 'i'}})
                    
                    # If still not found, try display_name match
                    if not user_data:
                        user_data = users_collection.find_one({'display_name': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}})
                    
                    if user_data:
                        logger.info(f"✅ Found winner by username: {username}")
                    else:
                        logger.warning(f"⚠️ Winner {username} not found in database")
                
                if user_data:
                    # Get this winner's profit based on their personal commission rate
                    winner_profit = winner_profits.get(username, 0)
                    commission_rate = winner_commission_rates.get(username, 0.05)
                    commission_amount = int(bet_amount * commission_rate)
                    
                    # Update balance - add only the profit (winner keeps their original bet)
                    old_balance = user_data.get('balance', 0)
                    new_balance = old_balance + winner_profit
                    
                    users_collection.update_one(
                        {'_id': user_data['_id']},
                        {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                    )
                    
                    # Record winning transaction
                    transaction_data = {
                        'user_id': user_data['user_id'],
                        'type': 'win',
                        'amount': winner_profit,
                        'description': f'Won game {game_data["game_id"]} - profit from opponent bet (₹{bet_amount}) minus {int(commission_rate * 100)}% commission (₹{commission_amount})',
                        'timestamp': datetime.now(),
                        'game_id': game_data['game_id'],
                        'old_balance': old_balance,
                        'new_balance': new_balance,
                        'commission_rate': commission_rate,
                        'commission_amount': commission_amount
                    }
                    transactions_collection.insert_one(transaction_data)
                    
                    logger.info(f"🎉 Added ₹{winner_profit} profit to winner {username} (₹{old_balance} → ₹{new_balance}) with {int(commission_rate * 100)}% commission")
                    
                    # Notify winner
                    try:
                        # Generate link to the original game table message
                        table_link = self._generate_message_link(
                            game_data['chat_id'], 
                            int(game_data['admin_message_id'])
                        )
                        
                        await self.application.bot.send_message(
                            chat_id=user_data['user_id'],
                            text = (
                                f"💰 <b>Profit Credited:</b> ₹{winner_profit}\n"
                                f"📊 <b>Updated Balance:</b> ₹{new_balance}\n\n"
                                f"💡 Your bet (₹{bet_amount}) was safe – only profit added!\n\n"
                                f"💸 <a href='https://t.me/SOMYA_000'>Click to Instant Withdraw</a>\n\n"
                                f"🔍 <a href='{table_link}'>View Table</a>"
                            ),
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                        logger.info(f"✅ Winner notification sent to {user_data['user_id']}")
                    except Exception as e:
                        logger.error(f"❌ Could not notify winner {user_data['user_id']}: {e}")
                else:
                    logger.warning(f"⚠️ Winner {username} not found in database")
            
            # Update game status with commission information
            games_collection.update_one(
                {'game_id': game_data['game_id']},
                {
                    '$set': {
                        'status': 'completed',
                        'winner': winners[0]['username'],
                        'winner_amount': winner_profits.get(winners[0]['username'], 0),
                        'admin_fee': total_commission,
                        'completed_at': datetime.now(),
                        'commission_rates': winner_commission_rates  # Store commission rates for future reference
                    }
                }
            )
            
            # Group notification removed - no more "GAME COMPLETED" messages
            
            logger.info("✅ Game result processed successfully")
            
            # Update balance sheet after game completion
            try:
                await self.update_balance_sheet(None)
            except Exception as e:
                logger.warning(f"⚠️ Could not update balance sheet after game completion: {e}")
            
        except Exception as e:
            logger.error(f"❌ Error processing game result: {e}")
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")

    def setup_handlers(self, application: Application):
        """Set up all command and message handlers"""
        # Command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("ping", self.ping_command))
        application.add_handler(CommandHandler("debugmessage", self.debug_message_command))
        application.add_handler(CommandHandler("testgametable", self.test_game_table_entities_command))
        application.add_handler(CommandHandler("testmentions", self.test_mentions_command))
        application.add_handler(CommandHandler("myid", self.myid_command))
        application.add_handler(CommandHandler("balance", self.balance_command))
        application.add_handler(CommandHandler("add", self.addbalance_command))
        application.add_handler(CommandHandler("nil", self.withdraw_command))
        application.add_handler(CommandHandler("activegames", self.active_games_command))
        application.add_handler(CommandHandler("expiregames", self.expire_games_command))
        application.add_handler(CommandHandler("set", self.set_commission_command))
        application.add_handler(CommandHandler("listpin", self.balance_sheet_command))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(CommandHandler("cancel", self.cancel_table_command))
        application.add_handler(CommandHandler("testkformat", self.test_k_format_command))
        application.add_handler(CommandHandler("health", self.health_check_command))
        application.add_handler(CommandHandler("cleardata", self.clear_all_data_command))
        application.add_handler(CommandHandler("clearusers", self.clear_users_command))
        application.add_handler(CommandHandler("cleargames", self.clear_games_command))
        application.add_handler(CommandHandler("resetbot", self.reset_bot_command))
        
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
            await self.send_group_response(update, context, "🚫 **Access Denied!** Only admins can use commands in the group. Please message me privately to start.")
            return
        
        try:
            # Create or update user in database (do not overwrite existing balance)
            user_data = {
                'user_id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'is_admin': user.id in self.admin_ids,
                'last_active': datetime.now()
                # balance is set only on insert to avoid overwriting existing balance
            }
            
            # Update or insert user
            users_collection.update_one(
                {'user_id': user.id},
                {
                    '$set': user_data,
                    '$setOnInsert': {'created_at': datetime.now(), 'balance': 0}  # Only set on insert
                },
                upsert=True
            )
            
            # Create stylish developer button
            developer_button = InlineKeyboardButton(
                "👨‍💻 Developer",
                url="https://telegram.me/Codewithjaadu"
            )
            #Admin button
            admin_button = InlineKeyboardButton(
                "🫅 Admin",
                url="https://telegram.me/SOMYA_000"
            )
            keyboard = InlineKeyboardMarkup([[developer_button, admin_button]])
            
            # Send welcome message with stylish formatting
            welcome_msg = (
                "🎮 **Welcome to Ludo Group Manager!** 🎮\n\n"
                "🚀 I'm your intelligent assistant for managing Ludo games in the group.\n\n"
                "✨ **Key Features:**\n"
                "• 🎯 Automatic game table processing\n"
                "• 🏆 Smart winner selection & balance updates\n"
                "• 💰 Commission management system\n"
                "• 📊 Real-time balance tracking\n"
                "• 📈 Comprehensive game statistics\n"
                "• 🔄 Automatic message editing\n\n"
                "💡 Use `/help` for detailed command information.\n\n"
                "🎯 **Ready to start managing your Ludo games!**"
            )
            
            if is_group:
                await self.send_group_response(update, context, welcome_msg)
            else:
                await update.message.reply_text(
                    welcome_msg, 
                    parse_mode="markdown",
                    reply_markup=keyboard
                )
                
        except Exception as e:
            logger.error(f"❌ Error in start command: {e}")
            error_msg = "🚨 **Oops!** There was an error setting up your account. Please try again later."
            if is_group:
                await self.send_group_response(update, context, error_msg)
            else:
                await update.message.reply_text(error_msg, parse_mode="markdown")
            
    async def debug_message_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /debugmessage command - show raw message data for debugging"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "🚫 **Access Denied!** Only admins can use this command.")
            return
        
        try:
            message = update.message
            message_text = "🔍 **Message Debug Information**\n\n"
            
            # Basic message info
            message_text += f"**📱 Message Details:**\n"
            message_text += f"• Message ID: `{message.message_id}`\n"
            message_text += f"• Chat ID: `{message.chat.id}`\n"
            message_text += f"• Chat Type: `{message.chat.type}`\n"
            message_text += f"• From User ID: `{message.from_user.id}`\n"
            message_text += f"• From Username: `{message.from_user.username or 'None'}`\n"
            message_text += f"• From First Name: `{message.from_user.first_name or 'None'}`\n"
            message_text += f"• Date: `{message.date}`\n\n"
            
            # Message text
            message_text += f"**📝 Message Text:**\n`{message.text}`\n\n"
            
            # Message entities
            if message.entities:
                message_text += f"**🔍 Message Entities ({len(message.entities)}):**\n"
                for i, entity in enumerate(message.entities):
                    message_text += f"\n**Entity {i+1}:**\n"
                    message_text += f"• Type: `{getattr(entity, 'type', 'unknown')}`\n"
                    message_text += f"• Offset: `{getattr(entity, 'offset', 'unknown')}`\n"
                    message_text += f"• Length: `{getattr(entity, 'length', 'unknown')}`\n"
                    
                    # Check if it's a Pyrogram entity
                    if hasattr(entity, '__class__'):
                        message_text += f"• Class: `{entity.__class__.__name__}`\n"
                    
                    # Check for user info
                    if hasattr(entity, 'user') and entity.user:
                        message_text += f"• User ID: `{entity.user.id}`\n"
                        message_text += f"• Username: `{entity.user.username or 'None'}`\n"
                        message_text += f"• First Name: `{entity.user.first_name or 'None'}`\n"
                        message_text += f"• Last Name: `{entity.user.last_name or 'None'}`\n"
                    
                    # Check for URL (for text_link entities)
                    if hasattr(entity, 'url'):
                        message_text += f"• URL: `{entity.url}`\n"
                    
                    # Check for language (for pre entities)
                    if hasattr(entity, 'language'):
                        message_text += f"• Language: `{entity.language}`\n"
            else:
                message_text += "**❌ No message entities found**\n"
            
            # Raw message object info
            message_text += f"\n**🔧 Raw Message Object:**\n"
            message_text += f"• Class: `{message.__class__.__name__}`\n"
            message_text += f"• Module: `{message.__class__.__module__}`\n"
            
            # Check for additional attributes
            additional_attrs = ['forward_from', 'reply_to_message', 'edit_date', 'media_group_id']
            for attr in additional_attrs:
                if hasattr(message, attr):
                    value = getattr(message, attr)
                    message_text += f"• {attr}: `{value}`\n"
            
            await self.send_group_response(update, context, message_text)
            
        except Exception as e:
            logger.error(f"Error in debug_message command: {e}")
            await self.send_group_response(update, context, f"❌ Error debugging message: {str(e)}")

    async def test_game_table_entities_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /testgametable command - test game table entity detection"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "🚫 **Access Denied!** Only admins can use this command.")
            return
        
        try:
            message = update.message
            message_text = "🔍 **Game Table Entity Test**\n\n"
            
            # Check if message contains "Full" keyword (like a game table)
            if "Full" in message.text or "full" in message.text:
                message_text += "✅ **Game table format detected!**\n\n"
                
                # Test the game table entity extraction
                if message.entities:
                    message_text += f"🔍 **Found {len(message.entities)} entities:**\n"
                    for i, entity in enumerate(message.entities):
                        message_text += f"\n**Entity {i+1}:**\n"
                        message_text += f"• Type: `{getattr(entity, 'type', 'unknown')}`\n"
                        message_text += f"• Offset: `{getattr(entity, 'offset', 'unknown')}`\n"
                        message_text += f"• Length: `{getattr(entity, 'length', 'unknown')}`\n"
                        
                        if hasattr(entity, 'user') and entity.user:
                            message_text += f"• User ID: `{entity.user.id}`\n"
                            message_text += f"• Username: `{entity.user.username or 'None'}`\n"
                            message_text += f"• First Name: `{entity.user.first_name or 'None'}`\n"
                            message_text += f"• Last Name: `{entity.user.last_name or 'None'}`\n"
                    
                    # Test the new entity extraction function
                    message_text += f"\n🔍 **Testing entity extraction:**\n"
                    mentioned_users = []
                    
                    for entity in message.entities:
                        if hasattr(entity, 'type') and entity.type == "mention":
                            mention_text = message.text[entity.offset:entity.offset + entity.length]
                            username = mention_text.lstrip('@')
                            mentioned_users.append({
                                "username": username,
                                "is_mention": True,
                                "entity_type": "mention"
                            })
                            message_text += f"✅ @mention: {username}\n"
                        
                        elif hasattr(entity, 'type') and entity.type == "text_mention":
                            user = getattr(entity, 'user', None)
                            if user:
                                mentioned_users.append({
                                    "user_id": user.id,
                                    "username": user.username or f"user_{user.id}",
                                    "first_name": user.first_name,
                                    "is_mention": True,
                                    "entity_type": "text_mention",
                                    "telegram_user_id": user.id
                                })
                                message_text += f"✅ text_mention: {user.first_name} (ID: {user.id})\n"
                    
                    message_text += f"\n📊 **Total mentioned users:** {len(mentioned_users)}\n"
                    
                else:
                    message_text += "❌ **No entities found** - This might be a text-only game table\n"
            else:
                message_text += "❌ **Not a game table format** - Message must contain 'Full' keyword\n"
                message_text += "\n💡 **Try this format:**\n"
                message_text += "```\n@username1\n@username2\n1000 Full\n```"
                message_text += "\nOr with contact taps:\n"
                message_text += "```\n[Tap User1's contact]\n[Tap User2's contact]\n1000 Full\n```"
            
            await self.send_group_response(update, context, message_text)
            
        except Exception as e:
            logger.error(f"Error in test_game_table_entities command: {e}")
            await self.send_group_response(update, context, f"❌ Error testing game table entities: {str(e)}")

    async def test_mentions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /testmentions command - test mention detection"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "🚫 **Access Denied!** Only admins can use this command.")
            return
        
        try:
            # Check if this message has entities
            if update.message.entities:
                message = "🔍 **Message Entities Found:**\n\n"
                for i, entity in enumerate(update.message.entities):
                    message += f"**Entity {i+1}:**\n"
                    message += f"• Type: `{getattr(entity, 'type', 'unknown')}`\n"
                    message += f"• Offset: `{getattr(entity, 'offset', 'unknown')}`\n"
                    message += f"• Length: `{getattr(entity, 'length', 'unknown')}`\n"
                    
                    # Check if it's a Pyrogram entity
                    if hasattr(entity, '__class__'):
                        message += f"• Class: `{entity.__class__.__name__}`\n"
                    
                    # Check for user info
                    if hasattr(entity, 'user') and entity.user:
                        message += f"• User ID: `{entity.user.id}`\n"
                        message += f"• Username: `{entity.user.username or 'None'}`\n"
                        message += f"• First Name: `{entity.user.first_name or 'None'}`\n"
                    
                    message += "\n"
                
                # Test mention extraction
                mentions = self._extract_mentions_from_message(update.message.text, update.message.entities)
                message += f"**Extracted Mentions:** {mentions}\n"
                
            else:
                message = "❌ **No message entities found**\n\n"
                message += "Try mentioning a user with @username or by tapping their contact."
            
            await self.send_group_response(update, context, message)
            
        except Exception as e:
            logger.error(f"Error in test_mentions command: {e}")
            await self.send_group_response(update, context, f"❌ Error testing mentions: {str(e)}")

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
                "🎮 **Ludo Group Manager Bot** 🎮\n\n"
                "This intelligent bot helps manage Ludo games in your group.\n\n"
                "📋 **Available Commands:**\n"
                "• `/ping` - Check if bot is running\n"
                "• `/start` - Create your account\n"
                "• `/balance` - Check your balance\n"
                "• `/myid` - Show your Telegram ID\n"
                "• `/help` - Show this help message\n\n"
                "⚠️ **Note:** Only admins can create games and manage balances."
            )
            await self.send_group_response(update, context, help_message)
            return
        
        # Admin help message with stylish formatting
        help_message = (
            "🎮 **Ludo Group Manager Bot - ADMIN PANEL** 🎮\n\n"
            "🚀 **NEW GAME PROCESS:**\n"
            "• 📤 Send table directly with 'Full' keyword\n"
            "• 🤖 Bot automatically detects and processes\n"
            "• 📱 Bot sends winner selection buttons to your DM\n"
            "• 🎯 Click winner button OR manually edit table to add ✅ for winners\n"
            "• ⚡ Bot automatically processes results\n\n"
            "✏️ **MANUAL EDITING (if buttons don't work):**\n"
            "• 🔄 Edit your table message in the group\n"
            "• ✅ Add ✅ after the winner's username\n"
            "• 📝 Example: @player1 ✅\n"
            "• 🤖 Bot will detect the edit and process results\n\n"
            "📋 **Example table format:**\n"
            "```\n"
            "@player1\n"
            "@player2\n"
            "400 Full\n"
            "```\n\n"
            "💰 **Amount formats supported:**\n"
            "• Regular: 1000, 2000, 5000\n"
            "• K format: 1k, 2k, 5k, 10k, 50k\n\n"
            "👥 **User mentions supported:**\n"
            "• Username: @username\n"
            "• First name: @FirstName\n"
            "• **Direct contact tap (no @ needed)** - Most reliable!\n"
            "• Works even without @ symbol\n"
            "• Supports international characters\n"
            "• Uses Telegram's native entity system\n"
            "• **NEW**: Automatic user creation from contact taps\n\n"
            "⚠️ **IMPORTANT:** Only 2 players allowed per game. Same username cannot play against itself.\n\n"
            "🛠️ **ADMIN COMMANDS:**\n"
            "• `/ping` - Check if bot is running\n"
            "• `/health` - Check detailed bot health status\n"
            "• `/debugmessage` - Show raw message data for debugging\n"
            "• `/testgametable` - Test game table entity detection\n"
            "• `/testmentions` - Test mention detection\n"
            "• `/myid` - Show your Telegram ID and admin status\n"
            "• `/activegames` - Show all currently running games\n"
            "• `/add @username amount` - Add balance to user\n"
            "  Examples: `/add @Gopal 500`\n"
            "           `/add [Tap Gopal's contact] 500`\n"
            "• `/nil @username amount` - Withdraw from user\n"
            "  Examples: `/nil @Gopal 500`\n"
            "           `/nil [Tap Gopal's contact] 500`\n"
            "• `/set @username percentage` - Set custom commission rate\n"
            "  Examples: `/set @Gopal 10`\n"
            "           `/set [Tap Gopal's contact] 10`\n"
            "• `/expiregames` - Manually expire old games\n"
            "• `/listpin` - Create/update pinned balance sheet\n"
            "• `/stats` - Show game and user statistics\n"
            "• `/cancel` - Cancel a game table (reply to table message)\n\n"
            "🗑️ **DATA CLEAR COMMANDS:**\n"
            "• `/cleardata` - Clear ALL bot data (users, games, transactions)\n"
            "• `/clearusers` - Clear only user data and balances\n"
            "• `/cleargames` - Clear only game data\n"
            "• `/resetbot` - Complete bot reset (factory settings)\n\n"
            "🎯 **Ready to manage your Ludo games efficiently!**"
        )
        
        if is_group:
            await self.send_group_response(update, context, help_message)
        else:
            await update.message.reply_text(help_message, parse_mode="markdown")

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
                    balance_message = f"💰 **Your Balance: ₹{balance}** 💰"
                elif balance < 0:
                    balance_message = f"💸 **Your Balance: -₹{abs(balance)} (Debt)** 💸"
                else:
                    balance_message = f"💰 **Your Balance: ₹{balance}** 💰"
                
                if is_group:
                    await self.send_group_response(update, context, balance_message)
                else:
                    await update.message.reply_text(balance_message, parse_mode="markdown")
            else:
                balance_message = "❌ **Account not found!** Please use `/start` to create your account."
                if is_group:
                    await self.send_group_response(update, context, balance_message)
                else:
                    await update.message.reply_text(balance_message, parse_mode="markdown")
                    
        except Exception as e:
            logger.error(f"❌ Error in balance command: {e}")
            error_msg = "❌ **Error retrieving balance.** Please try again later."
            if is_group:
                await self.send_group_response(update, context, error_msg)
            else:
                await update.message.reply_text(error_msg, parse_mode="markdown")

    async def addbalance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add command"""
        # Debug logging for admin check
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        logger.info(f"🔍 Admin check - User ID: {user_id}, Username: {username}")
        logger.info(f"🔍 Admin check - Admin IDs: {self.admin_ids}")
        logger.info(f"🔍 Admin check - Is admin: {user_id in self.admin_ids}")
        
        if user_id not in self.admin_ids:
            await self.send_group_response(update, context, f"🚫 **Access Denied!** Only admins can use this command. Your ID: {user_id}")
            return
        
        # Log message entities for debugging
        logger.info(f"🔍 /add command received")
        logger.info(f"🔍 Message text: '{update.message.text}'")
        logger.info(f"🔍 Message entities: {update.message.entities}")
        
        if update.message.entities:
            for i, entity in enumerate(update.message.entities):
                logger.info(f"🔍 Entity {i+1}:")
                logger.info(f"   Type: {getattr(entity, 'type', 'unknown')}")
                logger.info(f"   Offset: {getattr(entity, 'offset', 'unknown')}")
                logger.info(f"   Length: {getattr(entity, 'length', 'unknown')}")
                
                # Check if it's a Pyrogram entity
                if hasattr(entity, '__class__'):
                    logger.info(f"   Class: {entity.__class__.__name__}")
                
                # Check for user info
                if hasattr(entity, 'user') and entity.user:
                    logger.info(f"   User ID: {entity.user.id}")
                    logger.info(f"   Username: {entity.user.username or 'None'}")
                    logger.info(f"   First Name: {entity.user.first_name or 'None'}")
        else:
            logger.info(f"🔍 No message entities found")
            
        try:
            if len(context.args) < 2:
                await self.send_group_response(update, context, "Usage: /add @username amount OR /add \"First Name\" amount")
                return
            
            # Initialize variables to ensure they're always defined
            username = None
            amount = None
            user_data = None
            
            # Try to extract user directly from message entities first (most reliable)
            user_data = self._extract_user_from_entities(update.message.entities, update.message.text)
            
            if user_data:
                logger.info(f"✅ Found user from entities: {user_data.get('first_name', user_data.get('username', 'Unknown'))}")
                # For entity-based users, use display name or username
                username = user_data.get('display_name') or user_data.get('username') or user_data.get('first_name', 'Unknown')
            else:
                # Fallback to parsing command arguments for names with spaces
                logger.info("🔍 No user found in entities, trying command argument parsing")
                
                # Handle names with spaces: /add "Gopal M" 500
                # The last argument is always the amount
                username_parts = context.args[:-1]  # Everything except amount
                username = ' '.join(username_parts).replace('@', '')  # Join with spaces and remove @
                
                logger.info(f"🔍 Parsed command - Username: '{username}', Amount: {amount}")
                
                # Find user using the fallback mention resolver
                user_data = await self._resolve_user_mention(username, None)
            
            # Extract amount from command arguments
            amount = int(context.args[-1])  # Last argument is amount
            
            if amount <= 0:
                await self.send_group_response(update, context, "❌ Amount must be positive!")
                return
            
            if not user_data:
                await self.send_group_response(update, context, f"❌ User {username} not found in database!")
                return
                
            # Update balance with negative balance handling
            old_balance = user_data.get('balance', 0)
            
            # Handle negative balance properly
            if old_balance < 0:
                # User has debt, deposit should first fill the debt
                debt_amount = abs(old_balance)
                if amount <= debt_amount:
                    # Deposit only partially fills the debt
                    new_balance = old_balance + amount  # Still negative or zero
                    debt_filled = amount
                    remaining_deposit = 0
                else:
                    # Deposit fills all debt and adds to balance
                    new_balance = amount - debt_amount  # Positive balance
                    debt_filled = debt_amount
                    remaining_deposit = amount - debt_amount
            else:
                # No debt, normal addition
                new_balance = old_balance + amount
                debt_filled = 0
                remaining_deposit = amount
            
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
            
            # Prepare response with debt handling info
            user_identifier = username
            if username.startswith('@'):
                user_identifier = username[1:]  # Remove @ if present
            
            if old_balance < 0 and debt_filled > 0:
                response_msg = f"✅ Added ₹{amount} to {user_identifier}\n"
                if remaining_deposit > 0:
                    response_msg += f"💸 Debt Cleared: ₹{debt_filled}\n"
                    response_msg += f"💰 Added to Balance: ₹{remaining_deposit}\n"
                    response_msg += f"📊 Final Balance: ₹{new_balance}"
                else:
                    response_msg += f"💸 Debt Reduced: ₹{debt_filled}\n"
                    if new_balance < 0:
                        response_msg += f"📊 Remaining Debt: ₹{abs(new_balance)}"
                    else:
                        response_msg += f"📊 Final Balance: ₹{new_balance}"
            else:
                response_msg = f"✅ Added ₹{amount} to {user_identifier}\n"
                response_msg += f"💰 Balance: ₹{old_balance} → ₹{new_balance}"
            
            await self.send_group_response(update, context, response_msg)
            
            # Update balance sheet
            await self.update_balance_sheet(context)
            
            # Notify user with debt handling info
            try:
                if old_balance < 0 and debt_filled > 0:
                    if remaining_deposit > 0:
                        notification_text = (
                            f"💰 <b>Deposit: ₹{amount}</b>\n\n"
                            f"💸 <b>Debt Cleared:</b> ₹{debt_filled}\n"
                            f"💰 <b>Added to Balance:</b> ₹{remaining_deposit}\n\n"
                            f"<b>Final Balance:</b> ₹{new_balance}"
                        )
                    else:
                        if new_balance < 0:
                            notification_text = (
                                f"💰 <b>Deposit: ₹{amount}</b>\n\n"
                                f"💸 <b>Debt Reduced:</b> ₹{debt_filled}\n\n"
                                f"<b>Remaining Debt:</b> ₹{abs(new_balance)}"
                            )
                        else:
                            notification_text = (
                                f"💰 <b>Deposit: ₹{amount}</b>\n\n"
                                f"💸 <b>Debt Cleared:</b> ₹{debt_filled}\n\n"
                                f"<b>Final Balance:</b> ₹{new_balance}"
                            )
                else:
                    notification_text = (
                        f"💰 <b>Deposit: ₹{amount}</b>\n\n"
                        f"<b>Updated Balance:</b> ₹{new_balance}"
                    )
                
                await context.bot.send_message(
                    chat_id=user_data['user_id'],
                    text=notification_text,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Could not notify user {user_data['user_id']}: {e}")
                
        except ValueError:
            await self.send_group_response(update, context, "❌ Invalid amount. Please enter a number.")
        except Exception as e:
            logger.error(f"Error in add command: {e}")
            await self.send_group_response(update, context, f"❌ Error processing balance addition: {str(e)}")

    async def withdraw_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /nil command"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        
        # Log message entities for debugging
        logger.info(f"🔍 /nil command received")
        logger.info(f"🔍 Message text: '{update.message.text}'")
        logger.info(f"🔍 Message entities: {update.message.entities}")
        
        if update.message.entities:
            for i, entity in enumerate(update.message.entities):
                logger.info(f"🔍 Entity {i+1}:")
                logger.info(f"   Type: {getattr(entity, 'type', 'unknown')}")
                logger.info(f"   Offset: {getattr(entity, 'offset', 'unknown')}")
                logger.info(f"   Length: {getattr(entity, 'length', 'unknown')}")
                
                # Check if it's a Pyrogram entity
                if hasattr(entity, '__class__'):
                    logger.info(f"   Class: {entity.__class__.__name__}")
                
                # Check for user info
                if hasattr(entity, 'user') and entity.user:
                    logger.info(f"   User ID: {entity.user.id}")
                    logger.info(f"   Username: {entity.user.username or 'None'}")
                    logger.info(f"   First Name: {entity.user.first_name or 'None'}")
        else:
            logger.info(f"🔍 No message entities found")
            
        try:
            if len(context.args) < 2:
                await self.send_group_response(update, context, "Usage: /nil @username amount OR /nil \"First Name\" amount")
                return
            
            # Initialize variables to ensure they're always defined
            username = None
            amount = None
            user_data = None
            
            # Try to extract user directly from message entities first (most reliable)
            user_data = self._extract_user_from_entities(update.message.entities, update.message.text)
            
            if user_data:
                logger.info(f"✅ Found user from entities: {user_data.get('first_name', user_data.get('username', 'Unknown'))}")
                # For entity-based users, use display name or username
                username = user_data.get('display_name') or user_data.get('username') or user_data.get('first_name', 'Unknown')
            else:
                # Fallback to parsing command arguments for names with spaces
                logger.info("🔍 No user found in entities, trying command argument parsing")
                
                # Handle names with spaces: /nil "Gopal M" 500
                # The last argument is always the amount
                username_parts = context.args[:-1]  # Everything except amount
                username = ' '.join(username_parts).replace('@', '')  # Join with spaces and remove @
                
                logger.info(f"🔍 Parsed command - Username: '{username}', Amount: {amount}")
                
                # Find user using the fallback mention resolver
                user_data = await self._resolve_user_mention(username, None)
            
            # Extract amount from command arguments
            amount = int(context.args[-1])  # Last argument is amount
            
            if amount <= 0:
                await self.send_group_response(update, context, "❌ Amount must be positive!")
                return
            
            if not user_data:
                await self.send_group_response(update, context, f"❌ User {username} not found in database!")
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
            
            # Notify user with simple, clean message
            try:
                if new_balance < 0:
                    user_notification = (
                        f"💸 <b>Amount Withdrawn: ₹{amount}</b>\n\n"
                        f"📊 <b>New Balance: -₹{abs(new_balance)}</b>\n\n"
                        f"⚠️ You now have a debt of ₹{abs(new_balance)}"
                    )
                else:
                    user_notification = (
                        f"💸 <b>Amount Withdrawn: ₹{amount}</b>\n\n"
                        f"📊 <b>New Balance: ₹{new_balance}</b>"
                    )
                
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
            logger.error(f"Error in nil command: {e}")
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
                await self.send_group_response(update, context, "ℹ️ **Koi active game nahi chal raha abhi** 🎮")
                return
                
            games_list = "🎮 **CHAL RAHE GAMES** 🎮\n\n"
            
            for game in active_games:
                players = ", ".join([f"@{p['username']}" for p in game['players']])
                total_pot = sum(player['bet_amount'] for player in game['players'])
                time_left = game['expires_at'] - datetime.now()
                minutes_left = max(0, int(time_left.total_seconds() / 60))
                
                games_list += f"🆔 **Game ID:** {game['game_id']}\n"
                games_list += f"👥 **Players:** {players}\n"
                games_list += f"💰 **Total Pot:** ₹{total_pot}\n"
                games_list += f"⏰ **Time Left:** {minutes_left} minutes\n\n"
                
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
            await self.send_group_response(update, context, "✅ **Purane games check kar liye aur expire kar diye!** ⏰")
        except Exception as e:
            logger.error(f"Error in expire_games_command: {e}")
            await self.send_group_response(update, context, "❌ Error expiring games.")

    async def set_commission_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set commission rate for a user (/set command)"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "🚫 **Access Denied!** Only admins can use this command.")
            return
        
        # Log message entities for debugging
        logger.info(f"🔍 /set command received")
        logger.info(f"🔍 Message text: '{update.message.text}'")
        logger.info(f"🔍 Message entities: {update.message.entities}")
        
        if update.message.entities:
            for i, entity in enumerate(update.message.entities):
                logger.info(f"🔍 Entity {i+1}:")
                logger.info(f"   Type: {getattr(entity, 'type', 'unknown')}")
                logger.info(f"   Offset: {getattr(entity, 'offset', 'unknown')}")
                logger.info(f"   Length: {getattr(entity, 'length', 'unknown')}")
                
                # Check if it's a Pyrogram entity
                if hasattr(entity, '__class__'):
                    logger.info(f"   Class: {entity.__class__.__name__}")
                
                # Check for user info
                if hasattr(entity, 'user') and entity.user:
                    logger.info(f"   User ID: {entity.user.id}")
                    logger.info(f"   Username: {entity.user.username or 'None'}")
                    logger.info(f"   First Name: {entity.user.first_name or 'None'}")
        else:
            logger.info(f"🔍 No message entities found")
            
        try:
            if len(context.args) < 2:
                await self.send_group_response(update, context, "Usage: /set @username percentage OR /set \"First Name\" percentage")
                return
            
            # Initialize variables to ensure they're always defined
            username = None
            commission_percentage = None
            user_data = None
            
            # Try to extract user directly from message entities first (most reliable)
            user_data = self._extract_user_from_entities(update.message.entities, update.message.text)
            
            if user_data:
                logger.info(f"✅ Found user from entities: {user_data.get('first_name', user_data.get('username', 'Unknown'))}")
                # For entity-based users, use display name or username
                username = user_data.get('display_name') or user_data.get('username') or user_data.get('first_name', 'Unknown')
            else:
                # Fallback to parsing command arguments for names with spaces
                logger.info("🔍 No user found in entities, trying command argument parsing")
                
                # Handle names with spaces: /set "Gopal M" 10
                # The last argument is always the percentage
                username_parts = context.args[:-1]  # Everything except percentage
                username = ' '.join(username_parts).replace('@', '')  # Join with spaces and remove @
                
                logger.info(f"🔍 Parsed command - Username: '{username}', Commission: {commission_percentage}%")
                
                # Find user using the fallback mention resolver
                user_data = await self._resolve_user_mention(username, None)
            
            # Extract percentage from command arguments
            commission_percentage = float(context.args[-1])  # Last argument is percentage
            
            if commission_percentage < 0 or commission_percentage > 100:
                await self.send_group_response(update, context, "❌ Commission rate must be between 0 and 100 (e.g., 10 for 10%, 100 for 100%)")
                return
                
            # Convert percentage to decimal for storage (10% = 0.1)
            commission_rate = commission_percentage / 100
            
            if not user_data:
                await self.send_group_response(update, context, f"❌ User {username} not found in database!")
                return
                
            # Update commission rate (store as decimal)
            users_collection.update_one(
                {'user_id': user_data['user_id']},
                {'$set': {'commission_rate': commission_rate}}
            )
            
            # Format rate for display
            display_rate = f"{int(commission_percentage)}%"
            
            # Show proper user identifier (no @ for text_mention users)
            user_identifier = username
            if username.startswith('@'):
                user_identifier = username[1:]  # Remove @ if present
            
            await self.send_group_response(update, context, f"✅ Commission rate set to {display_rate} for {user_identifier}")
            
        except ValueError:
            await self.send_group_response(update, context, "❌ Invalid rate. Please enter a number between 0 and 100 (e.g., 10 for 10%).")
        except Exception as e:
            logger.error(f"Error in set command: {e}")
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
                
                # No need to refund players since no bets were deducted at game creation
                # Just notify players that the game expired
                for player in game['players']:
                    user_data = await self._resolve_user_mention(player['username'], None)
                    
                    if user_data:
                        # Notify user about game expiration
                        try:
                            # Generate link to the original game table message
                            table_link = self._generate_message_link(
                                game['chat_id'], 
                                int(game['admin_message_id'])
                            )
                            
                            await context.bot.send_message(
                                chat_id=user_data['user_id'],
                                text=(
                                    f"⌛ <b>Game Expired</b>\n\n"
                                    f"💡 <b>Good news:</b> No money was deducted from your balance!\n"
                                    f"📊 <b>Your Balance:</b> ₹{user_data.get('balance', 0)} (unchanged)\n\n"
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
                f"✅ **Winner select kar liya:** @{winner_username}\n"
                "Processing game results..."
            )
            
        except Exception as e:
            logger.error(f"❌ Error in winner selection: {e}")
            await query.edit_message_text(f"❌ Error processing winner: {str(e)}")

    async def balance_sheet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /listpin command: temporarily disabled"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        await self.send_group_response(update, context, "⏸️ Balance sheet feature is temporarily disabled.")
        return

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
                # Check if it's a completed game in the database
                game_data = games_collection.find_one({'admin_message_id': int(replied_message_id)})
                if not game_data:
                    await self.send_group_response(update, context, "❌ No active or completed game found for this message.")
                    return
                
                if game_data['status'] == 'completed':
                    # Handle cancellation of completed game with refunds
                    logger.info(f"🎮 Cancelling completed game: {game_data['game_id']}")
                    success = await self._cancel_completed_game_with_refunds(game_data, update.effective_user.id)
                    
                    if success:
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
                        
                        await self.send_group_response(update, context, f"✅ **Game cancel kar diya!** {game_data['game_id']} - sabko refund kar diya commission ke saath")
                        logger.info(f"✅ Completed game {game_data['game_id']} cancelled and refunded successfully")
                    else:
                        await self.send_group_response(update, context, "❌ Failed to cancel the completed game. Please try again.")
                else:
                    await self.send_group_response(update, context, "❌ This game is not active or completed. Cannot cancel.")
                return
            
            # Get the game data from active games
            game_data = self.active_games[replied_message_id]
            logger.info(f"🎮 Cancelling active game: {game_data['game_id']}")
            
            # Cancel the active game (no refunds needed since no bets were deducted)
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
                
                await self.send_group_response(update, context, f"✅ **Active game cancel kar diya!** {game_data['game_id']} - sabko bata diya")
                logger.info(f"✅ Active game {game_data['game_id']} cancelled successfully")
            else:
                await self.send_group_response(update, context, "❌ Failed to cancel the active game. Please try again.")
                
        except Exception as e:
            logger.error(f"❌ Error in cancel table command: {e}")
            await self.send_group_response(update, context, f"❌ Error cancelling game: {str(e)}")

    async def _cancel_and_refund_game(self, game_data: Dict, admin_id: int) -> bool:
        """Cancel a game (no refunds needed since no bets were deducted)"""
        try:
            logger.info(f"🔄 Cancelling game {game_data['game_id']} and notifying players")
            
            successful_notifications = []
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
                    
                    # No need to refund since no bets were deducted - just notify
                    logger.info(f"✅ Notifying {username} about game cancellation")
                    successful_notifications.append(username)
                    
                    # Notify player about game cancellation
                    try:
                        # Generate link to the original game table message
                        table_link = self._generate_message_link(
                            game_data['chat_id'], 
                            int(game_data['admin_message_id'])
                        )
                        
                        await self.application.bot.send_message(
                            chat_id=user_data['user_id'],
                            text=(
                                f"🚫 <b>Game Cancelled</b>\n\n"
                                f"💡 <b>Good news:</b> No money was deducted from your balance!\n"
                                f"📊 <b>Your Balance:</b> ₹{user_data.get('balance', 0)} (unchanged)\n\n"
                                f"🔍 <a href='{table_link}'>View Game Table</a>"
                            ),
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                        logger.info(f"✅ Cancellation notification sent to {username}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not notify {username} about cancellation: {e}")
                        
                except Exception as e:
                    logger.error(f"❌ Error notifying {username}: {e}")
                    failed_players.append(username)
            
            if failed_players:
                logger.error(f"❌ Failed to notify players: {failed_players}")
                return False
            
            logger.info(f"✅ Successfully notified all {len(successful_notifications)} players")
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
            content = "#BALANCESHEET GAme RuLes - ✅BET_RULE DEPOSIT=QR/NUMBER ✅ @SOMYA_000 MESSAGE\n"
            content += "=" * 50 + "\n\n"
            
            # Only show actual users from database with their current balances
            for user in users:
                # Use first name (account name) instead of username
                account_name = user.get('first_name', user.get('username', 'Unknown User'))
                balance = user.get('balance', 0)
                
                # Format with appropriate emoji based on balance status
                if balance > 0:
                    content += f"🙏 {account_name} = ₹{balance}\n"
                elif balance < 0:
                    content += f"🙏 {account_name} = -₹{abs(balance)} (Debt)\n"
                else:
                    content += f"🙏 {account_name} = ₹{balance}\n"
            
            content += "\n" + "=" * 50 + "\n"
            
            # Add timestamp
            content += f"\n🕐 Last Updated: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
            
            return content
            
        except Exception as e:
            logger.error(f"❌ Error generating balance sheet: {e}")
            return "#BALANCESHEET - Error generating balance sheet"

    async def update_balance_sheet(self, context: ContextTypes.DEFAULT_TYPE = None):
        """Update the pinned balance sheet message (temporarily disabled)"""
        logger.warning("⚠️ update_balance_sheet is temporarily disabled")
        return

    async def create_new_balance_sheet(self, context: ContextTypes.DEFAULT_TYPE = None):
        """Create and pin a new balance sheet message (temporarily disabled)"""
        logger.warning("⚠️ create_new_balance_sheet is temporarily disabled")
        return

    async def _cancel_completed_game_with_refunds(self, game_data: Dict, admin_id: int) -> bool:
        """Cancel a completed game and refund all players with commission"""
        try:
            logger.info(f"🔄 Cancelling completed game {game_data['game_id']} and refunding players with commission")
            
            successful_refunds = []
            failed_players = []
            
            # Get the commission rate for this game
            commission_rate = game_data.get('commission_rate', 0.05)  # Default 5%
            bet_amount = game_data.get('bet_amount', 0)
            
            # Get winner information if available
            winner_username = game_data.get('winner')
            winner_profit = game_data.get('winner_amount', 0)
            
            # Process all players (including winner)
            for player in game_data['players']:
                username = player['username']
                user_id = player.get('user_id')
                
                try:
                    # Find user in database
                    user_data = None
                    if user_id:
                        user_data = users_collection.find_one({'user_id': int(user_id)})
                    
                    if not user_data:
                        # Try to find by username
                        user_data = users_collection.find_one({'username': username})
                    
                    if not user_data:
                        logger.error(f"❌ Player {username} not found in database")
                        failed_players.append(username)
                        continue
                    
                    # Calculate refund amount based on whether this player was the winner
                    if username == winner_username:
                        # Winner gets full bet refund minus commission, but loses any profit they earned
                        commission_amount = bet_amount * commission_rate
                        refund_amount = bet_amount - commission_amount
                        
                        # If winner received profit, deduct it from their balance
                        if winner_profit > 0:
                            old_balance = user_data.get('balance', 0)
                            # Deduct the profit they earned, then add the refund
                            new_balance = old_balance - winner_profit + refund_amount
                            
                            logger.info(f"💰 Winner {username}: Deducted profit ₹{winner_profit}, refunded ₹{refund_amount} (₹{old_balance} → ₹{new_balance})")
                        else:
                            old_balance = user_data.get('balance', 0)
                            new_balance = old_balance + refund_amount
                            logger.info(f"💰 Winner {username}: Refunded ₹{refund_amount} (₹{old_balance} → ₹{new_balance})")
                    else:
                        # Loser gets full bet refund minus commission
                        commission_amount = bet_amount * commission_rate
                        refund_amount = bet_amount - commission_amount
                        
                        old_balance = user_data.get('balance', 0)
                        new_balance = old_balance + refund_amount
                        logger.info(f"💰 Loser {username}: Refunded ₹{refund_amount} (₹{old_balance} → ₹{new_balance})")
                    
                    # Update user balance
                    users_collection.update_one(
                        {'_id': user_data['_id']},
                        {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                    )
                    
                    # Record refund transaction
                    transaction_type = 'winner_cancellation_refund' if username == winner_username else 'loser_cancellation_refund'
                    transaction_data = {
                        'user_id': user_data['user_id'],
                        'type': transaction_type,
                        'amount': refund_amount,
                        'description': f'Game {game_data["game_id"]} cancelled - refund with {int(commission_rate * 100)}% commission',
                        'timestamp': datetime.now(),
                        'game_id': game_data['game_id'],
                        'old_balance': old_balance,
                        'new_balance': new_balance,
                        'commission_deducted': commission_amount,
                        'was_winner': username == winner_username,
                        'profit_deducted': winner_profit if username == winner_username else 0
                    }
                    transactions_collection.insert_one(transaction_data)
                    
                    successful_refunds.append(username)
                    
                    # Notify player about game cancellation and refund
                    try:
                        # Generate link to the original game table message
                        table_link = self._generate_message_link(
                            game_data['chat_id'], 
                            int(game_data['admin_message_id'])
                        )
                        
                        if username == winner_username:
                            notification_text = (
                                f"🚫 <b>Game Cancelled</b>\n\n"
                                f"💰 <b>Refund Processed:</b> ₹{refund_amount}\n"
                                f"💸 <b>Profit Deducted:</b> ₹{winner_profit}\n"
                                f"💼 <b>Commission Deducted:</b> ₹{commission_amount} ({int(commission_rate * 100)}%)\n"
                                f"📊 <b>Updated Balance:</b> ₹{new_balance}\n\n"
                                f"🔍 <a href='{table_link}'>View Game Table</a>"
                            )
                        else:
                            notification_text = (
                                f"🚫 <b>Game Cancelled</b>\n\n"
                                f"💰 <b>Refund Processed:</b> ₹{refund_amount}\n"
                                f"💼 <b>Commission Deducted:</b> ₹{commission_amount} ({int(commission_rate * 100)}%)\n"
                                f"📊 <b>Updated Balance:</b> ₹{new_balance}\n\n"
                                f"🔍 <a href='{table_link}'>View Game Table</a>"
                            )
                        
                        await self.application.bot.send_message(
                            chat_id=user_data['user_id'],
                            text=notification_text,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                        logger.info(f"✅ Refund notification sent to {username}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not notify {username} about refund: {e}")
                        
                except Exception as e:
                    logger.error(f"❌ Error processing refund for {username}: {e}")
                    failed_players.append(username)
            
            if failed_players:
                logger.error(f"❌ Failed to refund players: {failed_players}")
                return False
            
            logger.info(f"✅ Successfully refunded all {len(successful_refunds)} players")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error in _cancel_completed_game_with_refunds: {e}")
            return False

    async def test_k_format_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Test command to verify k format amount detection"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        
        test_cases = [
            "1k Full",
            "2k Full", 
            "3k Full",
            "10k Full",
            "20k Full",
            "15k Full",
            "100 Full",
            "1000 Full",
            "50000 Full"
        ]
        
        results = []
        for test_case in test_cases:
            # Test the regex pattern
            match = re.search(r"(\d+(?:k|K)?)\s*[Ff]ull", test_case)
            if match:
                amount_str = match.group(1)
                if amount_str.lower().endswith('k'):
                    number_part = int(amount_str[:-1])
                    amount = number_part * 1000
                    results.append(f"✅ {test_case} → {amount_str} → ₹{amount}")
                else:
                    amount = int(amount_str)
                    results.append(f"✅ {test_case} → {amount_str} → ₹{amount}")
            else:
                results.append(f"❌ {test_case} → No match")
        
        test_message = "🧪 **K Format Amount Detection Test**\n\n" + "\n".join(results)
        await self.send_group_response(update, context, test_message)

    async def notify_all_admins_startup(self, context: ContextTypes.DEFAULT_TYPE):
        """Notify all admins when bot starts up"""
        try:
            startup_message = (
                "🚀 **Bot Startup Notification** 🚀\n\n"
                "🎉 **Me aagaya vaaoas me ab marnejaarahau!** 🎉\n\n"
                "🤖 **Ludo Group Manager Bot** is now online and ready!\n"
                "⚡ All systems are running smoothly\n"
                "🎮 Ready to manage your Ludo games\n\n"
                "🕐 **Started at:** " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n"
                "👑 **Total Admins:** " + str(len(self.admin_ids))
            )
            
            for admin_id in self.admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=startup_message,
                        parse_mode="markdown"
                    )
                    logger.info(f"✅ Startup notification sent to admin {admin_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not send startup notification to admin {admin_id}: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Error sending startup notifications: {e}")

    async def notify_all_admins_shutdown(self, context: ContextTypes.DEFAULT_TYPE):
        """Notify all admins when bot shuts down"""
        try:
            shutdown_message = (
                "🛑 **Bot Shutdown Notification** 🛑\n\n"
                "😢 **Me ja raha hun vaaoas se, phir milenge!** 😢\n\n"
                "🤖 **Ludo Group Manager Bot** is going offline\n"
                "⏰ **Shutdown time:** " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
                "💡 Bot will be back soon!\n"
                "🎮 All active games will be preserved\n"
                "📊 Balance sheet will be updated when back online"
            )
            
            for admin_id in self.admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=shutdown_message,
                        parse_mode="markdown"
                    )
                    logger.info(f"✅ Shutdown notification sent to admin {admin_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not send shutdown notification to admin {admin_id}: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Error sending shutdown notifications: {e}")

    async def _setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown"""
        import signal
        
        def signal_handler(signum, frame):
            logger.info(f"🛑 Received signal {signum}, initiating graceful shutdown...")
            asyncio.create_task(self._graceful_shutdown())
        
        # Register signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        logger.info("✅ Signal handlers registered for graceful shutdown")

    async def _graceful_shutdown(self):
        """Perform graceful shutdown with admin notifications"""
        try:
            logger.info("🔄 Starting graceful shutdown process...")
            
            # Notify all admins about shutdown
            if hasattr(self, 'application') and self.application:
                await self.notify_all_admins_shutdown(self.application.context)
            
            # Stop Pyrogram client if running
            if self.pyro_client and self.pyro_client.is_connected:
                await self.pyro_client.stop()
                logger.info("✅ Pyrogram client stopped")
            
            # Close MongoDB connection
            if 'client' in globals():
                client.close()
                logger.info("✅ MongoDB connection closed")
            
            logger.info("✅ Graceful shutdown completed")
            
        except Exception as e:
            logger.error(f"❌ Error during graceful shutdown: {e}")
        finally:
            # Force exit after cleanup
            os._exit(0)

    async def periodic_health_check(self, context: ContextTypes.DEFAULT_TYPE):
        """Send periodic health check notifications to all admins"""
        try:
            current_time = datetime.now()
            uptime_hours = int((current_time - getattr(self, '_start_time', current_time)).total_seconds() / 3600)
            
            health_message = (
                "💚 **Bot Health Check** 💚\n\n"
                "🎯 **Me abhi bhi zinda hun vaaoas me!** 🎯\n\n"
                "🤖 **Ludo Group Manager Bot** is running smoothly\n"
                "⏰ **Uptime:** " + str(uptime_hours) + " hours\n"
                "🎮 **Active Games:** " + str(len(self.active_games)) + "\n"
                "👥 **Total Admins:** " + str(len(self.admin_ids)) + "\n"
                "🕐 **Last Check:** " + current_time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
                "✨ Everything is working perfectly!\n"
                "🚀 Ready to manage your Ludo games"
            )
            
            for admin_id in self.admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=health_message,
                        parse_mode="markdown"
                    )
                    logger.info(f"✅ Health check notification sent to admin {admin_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not send health check to admin {admin_id}: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Error sending health check notifications: {e}")

    async def health_check_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /health command - manual health check"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "🚫 **Access Denied!** Only admins can use this command.")
            return
        
        try:
            current_time = datetime.now()
            uptime_hours = int((current_time - getattr(self, '_start_time', current_time)).total_seconds() / 3600)
            
            health_status = (
                "🏥 **Bot Health Status** 🏥\n\n"
                "🎯 **Me abhi bhi zinda hun vaaoas me!** 🎯\n\n"
                "🤖 **Bot Status:** ✅ Online & Running\n"
                "⏰ **Uptime:** " + str(uptime_hours) + " hours\n"
                "🎮 **Active Games:** " + str(len(self.active_games)) + "\n"
                "👥 **Total Admins:** " + str(len(self.admin_ids)) + "\n"
                "🕐 **Current Time:** " + current_time.strftime("%Y-%m-%d %H:%M:%S") + "\n"
                "🔄 **Last Health Check:** " + current_time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
                "✨ **All Systems:** Operational\n"
                "🚀 **Ready for:** Game Management\n"
                "💚 **Bot is healthy and happy!**"
            )
            
            if update.effective_chat.id == self.group_id:
                await self.send_group_response(update, context, health_status)
            else:
                await update.message.reply_text(health_status, parse_mode="markdown")
                
        except Exception as e:
            logger.error(f"❌ Error in health check command: {e}")
            error_msg = "🚨 **Error checking bot health.** Please try again later."
            if update.effective_chat.id == self.group_id:
                await self.send_group_response(update, context, error_msg)
            else:
                await update.message.reply_text(error_msg, parse_mode="markdown")

    async def clear_all_data_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cleardata command - clear all bot data (ADMIN ONLY)"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "🚫 **Access Denied!** Only admins can use this command.")
            return
        
        try:
            # Clear all collections
            users_deleted = users_collection.delete_many({})
            games_deleted = games_collection.delete_many({})
            transactions_deleted = transactions_collection.delete_many({})
            balance_sheet_deleted = balance_sheet_collection.delete_many({})
            
            # Clear active games from memory
            self.active_games.clear()
            
            # Reset pinned message ID
            self.pinned_balance_msg_id = None
            
            # Clear start time
            if hasattr(self, '_start_time'):
                self._start_time = datetime.now()
            
            clear_message = (
                "🗑️ **Sara Data Clear Kar Diya!** 🗑️\n\n"
                "✅ **Users deleted:** " + str(users_deleted.deleted_count) + "\n"
                "✅ **Games deleted:** " + str(games_deleted.deleted_count) + "\n"
                "✅ **Transactions deleted:** " + str(transactions_deleted.deleted_count) + "\n"
                "✅ **Balance sheets deleted:** " + str(balance_sheet_deleted.deleted_count) + "\n\n"
                "🔄 **Memory cleared:** Active games, pinned messages\n"
                "⏰ **Start time reset:** " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
                "🎯 **Bot fresh start ke liye ready hai!** 🚀"
            )
            
            if update.effective_chat.id == self.group_id:
                await self.send_group_response(update, context, clear_message)
            else:
                await update.message.reply_text(clear_message, parse_mode="markdown")
                
            logger.info(f"✅ All data cleared by admin {update.effective_user.id}")
                
        except Exception as e:
            logger.error(f"❌ Error clearing data: {e}")
            error_msg = "🚨 **Data clear karne me error aaya!** Please try again later."
            if update.effective_chat.id == self.group_id:
                await self.send_group_response(update, context, error_msg)
            else:
                await update.message.reply_text(error_msg, parse_mode="markdown")

    async def clear_users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clearusers command - clear only user data"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "🚫 **Access Denied!** Only admins can use this command.")
            return
        
        try:
            # Clear only users collection
            users_deleted = users_collection.delete_many({})
            
            clear_message = (
                "👥 **Users Data Clear Kar Diya!** 👥\n\n"
                "✅ **Users deleted:** " + str(users_deleted.deleted_count) + "\n"
                "🔄 **All user accounts removed**\n"
                "💰 **Balances reset to 0**\n\n"
                "🎯 **Users ko /start command use karna hoga**"
            )
            
            if update.effective_chat.id == self.group_id:
                await self.send_group_response(update, context, clear_message)
            else:
                await update.message.reply_text(clear_message, parse_mode="markdown")
                
            logger.info(f"✅ User data cleared by admin {update.effective_user.id}")
                
        except Exception as e:
            logger.error(f"❌ Error clearing users: {e}")
            error_msg = "🚨 **Users clear karne me error aaya!** Please try again later."
            if update.effective_chat.id == self.group_id:
                await self.send_group_response(update, context, error_msg)
            else:
                await update.message.reply_text(error_msg, parse_mode="markdown")

    async def clear_games_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cleargames command - clear only game data"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "🚫 **Access Denied!** Only admins can use this command.")
            return
        
        try:
            # Clear only games collection
            games_deleted = games_collection.delete_many({})
            
            # Clear active games from memory
            self.active_games.clear()
            
            clear_message = (
                "🎮 **Games Data Clear Kar Diya!** 🎮\n\n"
                "✅ **Games deleted:** " + str(games_deleted.deleted_count) + "\n"
                "🔄 **Active games memory cleared**\n"
                "⏰ **All game timers reset**\n\n"
                "🎯 **New games create kar sakte ho!**"
            )
            
            if update.effective_chat.id == self.group_id:
                await self.send_group_response(update, context, clear_message)
            else:
                await update.message.reply_text(clear_message, parse_mode="markdown")
                
            logger.info(f"✅ Game data cleared by admin {update.effective_user.id}")
                
        except Exception as e:
            logger.error(f"❌ Error clearing games: {e}")
            error_msg = "🚨 **Games clear karne me error aaya!** Please try again later."
            if update.effective_user.id not in self.admin_ids:
                await self.send_group_response(update, context, error_msg)
            else:
                await update.message.reply_text(error_msg, parse_mode="markdown")

    async def reset_bot_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /resetbot command - complete bot reset (ADMIN ONLY)"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "🚫 **Access Denied!** Only admins can use this command.")
            return
        
        try:
            # Clear all collections
            users_deleted = users_collection.delete_many({})
            games_deleted = games_collection.delete_many({})
            transactions_deleted = transactions_collection.delete_many({})
            balance_sheet_deleted = balance_sheet_collection.delete_many({})
            
            # Clear active games from memory
            self.active_games.clear()
            
            # Reset pinned message ID
            self.pinned_balance_msg_id = None
            
            # Reset start time
            self._start_time = datetime.now()
            
            # Clear any cached data
            if hasattr(self, 'pinned_balance_msg_id'):
                self.pinned_balance_msg_id = None
            
            reset_message = (
                "🔄 **Bot Complete Reset Kar Diya!** 🔄\n\n"
                "🗑️ **Sara data delete kar diya:**\n"
                "✅ **Users:** " + str(users_deleted.deleted_count) + "\n"
                "✅ **Games:** " + str(games_deleted.deleted_count) + "\n"
                "✅ **Transactions:** " + str(transactions_deleted.deleted_count) + "\n"
                "✅ **Balance sheets:** " + str(balance_sheet_deleted.deleted_count) + "\n\n"
                "🔄 **Memory cleared:** Active games, pinned messages\n"
                "⏰ **Start time reset:** " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
                "🎯 **Bot bilkul fresh ho gaya hai!** 🚀\n"
                "💡 **Sab users ko /start command use karna hoga**"
            )
            
            if update.effective_chat.id == self.group_id:
                await self.send_group_response(update, context, reset_message)
            else:
                await update.message.reply_text(reset_message, parse_mode="markdown")
                
            logger.info(f"✅ Bot completely reset by admin {update.effective_user.id}")
                
        except Exception as e:
            logger.error(f"❌ Error resetting bot: {e}")
            error_msg = "🚨 **Bot reset karne me error aaya!** Please try again later."
            if update.effective_chat.id == self.group_id:
                await self.send_group_response(update, context, error_msg)
            else:
                await update.message.reply_text(error_msg, parse_mode="markdown")

async def main():
    """Main entry point"""
    # Configuration - replace with your actual values
    BOT_TOKEN = "8205474950:AAG9aRfiLDC6-I0wwjf4vbNtU-zUTsPfwFI"
    API_ID = 18274091
    API_HASH = "97afe4ab12cb99dab4bed25f768f5bbc"
    GROUP_ID = -1002504305026
    ADMIN_IDS = [5948740136,739290618]
    
    print(f"🚀 Starting Ludo Manager Bot...")
    print(f"🔑 Bot Token: {BOT_TOKEN[:20]}...")
    print(f"📱 API ID: {API_ID}")
    print(f"🔐 API Hash: {API_HASH[:20]}...")
    print(f"👥 Group ID: {GROUP_ID}")
    print(f"👑 Admin IDs: {ADMIN_IDS}")
    
    # Create and start the bot
    bot = LudoManagerBot(BOT_TOKEN, API_ID, API_HASH, GROUP_ID, ADMIN_IDS)
    
    # Set up signal handlers for graceful shutdown
    bot._setup_signal_handlers()
    
    try:
        await bot.start_bot()
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user (KeyboardInterrupt)")
        await bot.notify_all_admins_shutdown(bot.application.context if hasattr(bot, 'application') else None)
    except Exception as e:
        logger.error(f"❌ Critical error: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        # Try to notify admins about the error
        try:
            await bot.notify_all_admins_shutdown(bot.application.context if hasattr(bot, 'application') else None)
        except:
            pass
    finally:
        # Ensure cleanup happens
        try:
            if hasattr(bot, 'pyro_client') and bot.pyro_client and bot.pyro_client.is_connected:
                await bot.pyro_client.stop()
                logger.info("✅ Pyrogram client stopped")
        except:
            pass
        
        try:
            if 'client' in globals():
                client.close()
                logger.info("✅ MongoDB connection closed")
        except:
            pass
        
        logger.info("✅ Bot shutdown completed")

if __name__ == "__main__":
    try:
        logger.info("Starting application...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
