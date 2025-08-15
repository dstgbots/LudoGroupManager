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
from pyrogram.types import Message
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
    
    logger.info("✅ Connected to MongoDB successfully")
except (ConnectionFailure, ImportError) as e:
    logger.error(f"❌ MongoDB connection failed: {e}")
    logger.warning("⚠️ Running in limited mode without database persistence")

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
        
        # Check if Pyrogram is available
        self.pyrogram_available = True
        try:
            import pyrogram
        except ImportError:
            self.pyrogram_available = False
            logger.warning("⚠️ Pyrogram not installed. Edited message handling will be limited.")

    def is_configured_group(self, chat_id: int) -> bool:
        """Check if the message is from the configured group"""
        return str(chat_id) == str(self.group_id)

    async def start_bot(self):
        """Start the main bot application"""
        try:
            logger.info("🚀 Starting Ludo Manager Bot...")
            
            # Create the Application and pass it your bot's token
            application = Application.builder().token(self.bot_token).build()
            
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
            ]
            
            for pattern in patterns:
                match = re.search(pattern, message_text)
                if match:
                    return match.group(1)
            
            # Try line-by-line approach
            lines = message_text.split('\n')
            for line in lines:
                if '✅' in line:
                    # Extract username with or without @
                    username_match = re.search(r'@?([a-zA-Z0-9_]+)', line)
                    if username_match:
                        return username_match.group(1)
            
            logger.warning("❌ Could not extract winner from message: " + message_text)
            return None
        except Exception as e:
            logger.error(f"❌ Error in winner extraction: {e}")
            return None
    
    def _extract_game_data_from_message(self, message_text: str, admin_user_id: int, message_id: int, chat_id: int) -> Optional[Dict]:
        """Extract game data from message text using simplified line-by-line processing"""
        try:
            logger.info(f"📄 Processing game table message...")
            logger.info(f"📝 Message content: {message_text}")
            
            lines = message_text.strip().split("\n")
            usernames = []
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
                            usernames.append(username)
                            logger.info(f"👥 Player found: {username}")
    
            if not usernames or not amount:
                logger.warning("❌ Invalid table format - missing usernames or amount")
                return None
    
            if len(usernames) < 2:
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
                'players': [{'username': username, 'bet_amount': amount} for username in usernames],
                'total_amount': amount * len(usernames),
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
            
            # Extract game data
            game_data = self._extract_game_data_from_message(
                update.message.text,
                update.effective_user.id,
                update.message.message_id,
                update.effective_chat.id
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
                # CRITICAL FIX: Case-insensitive database lookup
                username = winner['username']
                
                # Try to find user with case-insensitive matching
                user_data = users_collection.find_one({
                    '$or': [
                        {'username': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}},
                        {'username': {'$regex': f'^@{re.escape(username)}$', '$options': 'i'}}
                    ]
                })
                
                if not user_data:
                    logger.warning(f"⚠️ Winner {username} not found in database")
                    continue
                    
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
                except Exception as e:
                    logger.error(f"❌ Could not notify winner {user_data['user_id']}: {e}")
            
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
            
            # CRITICAL FIX: Use self.application.bot instead of context
            # Notify group
            try:
                group_message = (
                    f"🎉 *GAME COMPLETED!*\n\n"
                    f"🏆 *Winner:* @{winners[0]['username']}\n"
                    f"💰 *Winnings:* ₹{winner_amount}\n"
                    f"💼 *Commission:* ₹{commission_amount}\n"
                    f"🆔 *Game ID:* {game_data['game_id']}"
                )
                
                await self.application.bot.send_message(
                    chat_id=int(self.group_id),
                    text=group_message,
                    parse_mode="MarkdownV2"
                )
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
        application.add_handler(CommandHandler("balance", self.balance_command))
        application.add_handler(CommandHandler("addbalance", self.addbalance_command))
        application.add_handler(CommandHandler("withdraw", self.withdraw_command))
        application.add_handler(CommandHandler("activegames", self.active_games_command))
        application.add_handler(CommandHandler("expiregames", self.expire_games_command))
        application.add_handler(CommandHandler("setcommission", self.set_commission_command))
        
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
                "/start - Create your account\n"
                "/balance - Check your balance\n"
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
            "📊 **ADMIN COMMANDS:**\n"
            "/activegames - Show all currently running games\n"
            "/addbalance @username amount - Add balance to user\n"
            "/withdraw @username amount - Withdraw from user\n"
            "/setcommission @username rate - Set custom commission rate\n"
            "/expiregames - Manually expire old games"
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
            # Get user data
            user_data = users_collection.find_one({'user_id': user.id})
            
            if user_data:
                balance = user_data.get('balance', 0)
                balance_message = f"💰 Your balance: ₹{balance}"
                
                if is_group:
                    await self.send_group_response(update, context, balance_message)
                else:
                    await update.message.reply_text(balance_message)
            else:
                balance_message = "❌ Account not found. Please use /start to create your account."
                if is_group:
                    await self.send_group_response(update, context, balance_message)
                else:
                    await update.message.reply_text(balance_message)
                    
        except Exception as e:
            logger.error(f"❌ Error in balance command: {e}")
            await self.send_group_response(update, context, "❌ Error retrieving balance.")

    async def addbalance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addbalance command"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
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
                
            # Find user
            user_data = users_collection.find_one({'username': username})
            
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
                user_balance_display = f"₹{new_balance}"
                await context.bot.send_message(
                    chat_id=user_data['user_id'],
                    text=(
                        f"💰 Balance Added!\n"
                        f"₹{amount} has been added to your account by admin.\n"
                        f"New balance: {user_balance_display}"
                    )
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
                
            # Find user
            user_data = users_collection.find_one({'username': username})
            
            if not user_data:
                await self.send_group_response(update, context, f"❌ User @{username} not found in database!")
                return
                
            # Update balance
            old_balance = user_data.get('balance', 0)
            new_balance = old_balance - amount
            
            users_collection.update_one(
                {'user_id': user_data['user_id']},
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
            
            # Prepare response
            display_name = user_data.get('username', user_data.get('first_name', 'Unknown User'))
            response_msg = f"✅ Withdrew ₹{amount} from {display_name}"
            response_msg += f"\n💰 Balance: ₹{old_balance} → ₹{new_balance}"
            
            if new_balance < 0:
                response_msg += "\n⚠️ User now has negative balance!"
                
            await self.send_group_response(update, context, response_msg)
            
            # Update balance sheet
            await self.update_balance_sheet(context)
            
            # Notify user
            try:
                user_balance_display = f"₹{new_balance}" if new_balance >= 0 else f"-₹{abs(new_balance)} (debt)"
                await context.bot.send_message(
                    chat_id=user_data['user_id'],
                    text=(
                        f"💸 Withdrawal Notice\n"
                        f"₹{amount} has been withdrawn from your account by admin.\n"
                        f"💰 New balance: {user_balance_display}\n"
                        f"Admin: {update.effective_user.first_name}"
                    )
                )
            except Exception as e:
                logger.warning(f"Could not notify user {user_data['user_id']}: {e}")
                
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
                await self.send_group_response(update, context, "Usage: /setcommission @username rate")
                return
                
            username = context.args[0].replace('@', '')
            commission_rate = float(context.args[1])
            
            if commission_rate < 0 or commission_rate > 1:
                await self.send_group_response(update, context, "❌ Commission rate must be between 0 and 1 (e.g., 0.1 for 10%)")
                return
                
            # Find user
            user_data = users_collection.find_one({'username': username})
            
            if not user_data:
                await self.send_group_response(update, context, f"❌ User @{username} not found in database!")
                return
                
            # Update commission rate
            users_collection.update_one(
                {'user_id': user_data['user_id']},
                {'$set': {'commission_rate': commission_rate}}
            )
            
            # Format rate for display
            display_rate = f"{int(commission_rate * 100)}%"
            
            await self.send_group_response(update, context, f"✅ Commission rate set to {display_rate} for @{username}")
            
        except ValueError:
            await self.send_group_response(update, context, "❌ Invalid rate. Please enter a number between 0 and 1.")
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
                    user_data = users_collection.find_one({'username': player['username']})
                    
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
                            await context.bot.send_message(
                                chat_id=user_data['user_id'],
                                text=(
                                    f"⌛ Your game exceeded the 1-hour limit and has been automatically cancelled.\n"
                                    f"₹{refund_amount} has been refunded to your account.\n"
                                    f"New balance: ₹{new_balance}"
                                )
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
                
                # Notify group
                try:
                    await context.bot.send_message(
                        chat_id=int(self.group_id),
                        text=(
                            f"⌛ Game {game['game_id']} has expired and all players refunded.\n"
                            f"Total refunded: ₹{game['total_amount']}"
                        )
                    )
                except Exception as e:
                    logger.error(f"Could not send expiration message to group: {e}")
            
            logger.info(f"✅ Expired {len(expired_games)} games")
            
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

    async def update_balance_sheet(self, context: ContextTypes.DEFAULT_TYPE):
        """Update the balance sheet with latest transactions"""
        try:
            # Calculate total revenue
            total_commissions = sum(
                t['amount'] 
                for t in transactions_collection.find({'type': 'win'})
            )
            
            # Calculate total games
            total_games = games_collection.count_documents({})
            active_games = games_collection.count_documents({'status': 'active'})
            
            # Calculate total players
            total_players = users_collection.count_documents({})
            
            # Update balance sheet
            balance_sheet_collection.update_one(
                {'_id': 'main_sheet'},
                {
                    '$set': {
                        'total_commissions': total_commissions,
                        'total_games': total_games,
                        'active_games': active_games,
                        'total_players': total_players,
                        'last_updated': datetime.now()
                    }
                },
                upsert=True
            )
            
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

    async def send_group_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        """Send response in group with auto-deletion of both command and response"""
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
            
            # Delete the bot's response after 15 seconds
            async def delete_bot_response():
                try:
                    await asyncio.sleep(15)
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

async def main():
    """Main entry point"""
    # Configuration - replace with your actual values
    BOT_TOKEN = "5664706056:AAGweTBRqnaS1oQVEWkgxXl1WL9wUO_zuiA"
    API_ID = 18274091
    API_HASH = "97afe4ab12cb99dab4bed25f768f5bbc"
    GROUP_ID = -1002849354155
    ADMIN_IDS = [2109516065]
    
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
