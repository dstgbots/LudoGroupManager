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
        
        # Balance sheet management
        self.pinned_balance_msg_id = None
        self._load_pinned_message_id()
        
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
            return f"Message ID: {message_id}"

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
                # Deduct bet amounts from all players' balances BEFORE storing the game
                success = await self._deduct_player_bets(game_data)
                
                if success:
                    # Store game with STRING ID for consistency (CRITICAL FIX)
                    self.active_games[str(update.message.message_id)] = game_data
                    
                    # Also store in database
                    games_collection.insert_one(game_data)
                    
                    logger.info(f"🎮 Game created and stored with message ID: {update.message.message_id}")
                    logger.info(f"🔍 Current active games count: {len(self.active_games)}")
                    
                    # Send confirmation to group - DISABLED: No group notification needed
                    # await self._send_group_confirmation(context, update.effective_chat.id)
                    
                    # Send winner selection message to admin's DM
                    await self._send_winner_selection_to_admin(
                        game_data, 
                        update.effective_user.id
                    )
                else:
                    logger.error("❌ Failed to deduct bet amounts - game not created")
            else:
                logger.warning("❌ Failed to extract game data from message")
    
    async def _deduct_player_bets(self, game_data: Dict) -> bool:
        """Deduct bet amounts from all players' balances when game is created"""
        try:
            logger.info(f"💳 Deducting bet amounts for game {game_data['game_id']}")
            
            successful_deductions = []
            failed_players = []
            
            for i, player in enumerate(game_data['players']):
                username = player['username']
                bet_amount = player['bet_amount']
                
                try:
                    # Find user with case-insensitive matching
                    user_data = users_collection.find_one({
                        '$or': [
                            {'username': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}},
                            {'username': {'$regex': f'^@{re.escape(username)}$', '$options': 'i'}}
                        ]
                    })
                    
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
                                f"<b>Game ID:</b> {game_data['game_id']}\n"
                                f"<b>Bet Amount:</b> ₹{bet_amount}\n"
                                f"<b>Old Balance:</b> ₹{old_balance}\n"
                                f"<b>New Balance:</b> ₹{new_balance}\n\n"
                                f"📋 <a href='{table_link}'>View Game Table</a>\n\n"
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
                user_data = users_collection.find_one({
                    '$or': [
                        {'username': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}},
                        {'username': {'$regex': f'^@{re.escape(username)}$', '$options': 'i'}}
                    ]
                })
                
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
            
            # Calculate total pot and individual bet amount
            total_pot = game_data['total_amount']
            bet_amount = game_data['bet_amount']  # Individual bet amount per player
            
            logger.info(f"💰 Total Pot: ₹{total_pot}")
            logger.info(f"🎯 Individual Bet Amount: ₹{bet_amount}")
            
            # Update winner's balance with single commission system
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
                
                # Get user's custom commission rate (default to 0 if not set)
                user_commission_rate = user_data.get('commission_rate', 0)
                
                # Calculate commission from opponent's bet amount (not total pot)
                # Winner gets: their own bet + opponent's bet - commission from opponent's bet
                opponent_bet_amount = bet_amount * (len(game_data['players']) - 1)  # Total bet from other players
                commission_amount = int(opponent_bet_amount * user_commission_rate)
                
                # Calculate final winnings: own bet + (opponent bet - commission)
                final_winner_amount = bet_amount + (opponent_bet_amount - commission_amount)
                
                # Calculate new balance
                old_balance = user_data.get('balance', 0)
                new_balance = old_balance + final_winner_amount
                
                logger.info(f"👤 Winner: {username}")
                logger.info(f"💼 User Commission Rate: {int(user_commission_rate * 100)}%")
                logger.info(f"🎯 Own Bet: ₹{bet_amount}")
                logger.info(f"👥 Opponent Bet Total: ₹{opponent_bet_amount}")
                logger.info(f"💸 Commission: ₹{commission_amount}")
                logger.info(f"🎉 Final Winnings: ₹{final_winner_amount}")
                logger.info(f"💰 Balance: ₹{old_balance} → ₹{new_balance}")
                
                # Update user balance
                users_collection.update_one(
                    {'_id': user_data['_id']},
                    {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                )
                
                # Record winning transaction
                transaction_data = {
                    'user_id': user_data['user_id'],
                    'type': 'win',
                    'amount': final_winner_amount,
                    'description': f'Won game {game_data["game_id"]} (Commission: ₹{commission_amount} from opponent bet)',
                    'timestamp': datetime.now(),
                    'game_id': game_data['game_id'],
                    'own_bet': bet_amount,
                    'opponent_bet': opponent_bet_amount,
                    'commission': commission_amount,
                    'total_commission': commission_amount
                }
                transactions_collection.insert_one(transaction_data)
                
                # Notify winner
                try:
                    # Generate link to the original game table message
                    table_link = self._generate_message_link(
                        game_data['chat_id'], 
                        int(game_data['admin_message_id'])
                    )
                    
                    # Prepare commission breakdown message
                    commission_message = ""
                    if commission_amount > 0:
                        commission_message = f"\n💸 <b>Commission Deducted:</b> ₹{commission_amount} ({int(user_commission_rate * 100)}% from opponent bet)"
                    
                    await self.application.bot.send_message(
                        chat_id=user_data['user_id'],
                        text=(
                            f"🎉 <b>Congratulations! You won!</b>\n\n"
                            f"<b>Game:</b> {game_data['game_id']}\n"
                            f"<b>Your Bet:</b> ₹{bet_amount}\n"
                            f"<b>Opponent Bet Total:</b> ₹{opponent_bet_amount}\n"
                            f"<b>Final Winnings:</b> ₹{final_winner_amount}\n"
                            f"<b>New Balance:</b> ₹{new_balance}{commission_message}\n\n"
                            f"📋 <a href='{table_link}'>View Game Table</a>"
                        ),
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                    logger.info(f"✅ Winner notification sent to {user_data['user_id']}")
                except Exception as e:
                    logger.error(f"❌ Could not notify winner {user_data['user_id']}: {e}")
            
            # Notify losers
            winner_usernames = [w['username'] for w in winners]
            for player in game_data['players']:
                if player['username'] not in winner_usernames:
                    # This player lost
                    try:
                        # Find user data for loser
                        loser_data = users_collection.find_one({
                            '$or': [
                                {'username': {'$regex': f'^{re.escape(player["username"])}$', '$options': 'i'}},
                                {'username': {'$regex': f'^@{re.escape(player["username"])}$', '$options': 'i'}}
                            ]
                        })
                        
                        if loser_data:
                            current_balance = loser_data.get('balance', 0)
                            
                            # Generate link to the original game table message
                            table_link = self._generate_message_link(
                                game_data['chat_id'], 
                                int(game_data['admin_message_id'])
                            )
                            
                            await self.application.bot.send_message(
                                chat_id=loser_data['user_id'],
                                text=(
                                    f"😔 <b>Game Result</b>\n\n"
                                    f"Unfortunately, you didn't win this time.\n\n"
                                    f"<b>Game:</b> {game_data['game_id']}\n"
                                    f"<b>Bet Amount:</b> ₹{player['bet_amount']}\n"
                                    f"<b>Winner:</b> @{winners[0]['username']}\n"
                                    f"<b>Your Balance:</b> ₹{current_balance}\n\n"
                                    f"📋 <a href='{table_link}'>View Game Table</a>\n\n"
                                    f"Better luck next time! 🍀"
                                ),
                                parse_mode="HTML",
                                disable_web_page_preview=True
                            )
                            logger.info(f"✅ Loser notification sent to {loser_data['user_id']}")
                        else:
                            logger.warning(f"⚠️ Loser {player['username']} not found in database")
                    except Exception as e:
                        logger.error(f"❌ Could not notify loser {player['username']}: {e}")
            
            # Calculate total commission earned (only user commission)
            total_commission_earned = 0
            for winner in winners:
                username = winner['username']
                user_data = users_collection.find_one({
                    '$or': [
                        {'username': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}},
                        {'username': {'$regex': f'^@{re.escape(username)}$', '$options': 'i'}}
                    ]
                })
                if user_data:
                    user_commission_rate = user_data.get('commission_rate', 0)
                    opponent_bet_amount = bet_amount * (len(game_data['players']) - 1)
                    user_commission = int(opponent_bet_amount * user_commission_rate)
                    total_commission_earned += user_commission
            
            # Update game status
            games_collection.update_one(
                {'game_id': game_data['game_id']},
                {
                    '$set': {
                        'status': 'completed',
                        'winner': winners[0]['username'],
                        'winner_amount': final_winner_amount,
                        'admin_fee': total_commission_earned,
                        'commission': total_commission_earned,
                        'completed_at': datetime.now()
                    }
                }
            )
            
            # Notify group - DISABLED: No group notification needed
            # try:
            #     group_message = (
            #         f"🎉 <b>GAME COMPLETED!</b>\n\n"
            #         f"🏆 <b>Winner:</b> @{winners[0]['username']}\n"
            #         f"💰 <b>Winnings:</b> ₹{winner_amount}\n"
            #         f"💼 <b>Commission:</b> ₹{commission_amount}\n"
            #         f"🆔 <b>Game ID:</b> {game_data['game_id']}"
            #     )
            #     
            #     await self.application.bot.send_message(
            #         chat_id=int(self.group_id),
            #         text=group_message,
            #         parse_mode="HTML"
            #     )
            #     logger.info("✅ Game completion notification sent to group")
            # except Exception as e:
            #     logger.error(f"❌ Could not send completion message to group: {e}")
            
            logger.info("ℹ️ Group notifications disabled - only DM notifications sent")
            
            # Update balance sheet after game completion
            try:
                await self.update_balance_sheet(None)
                logger.info("✅ Balance sheet updated after game completion")
            except Exception as e:
                logger.error(f"❌ Error updating balance sheet after game completion: {e}")
            
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
                await self.send_group_response(update, context, "Usage: /setcommission @username percentage (e.g., /setcommission @user 10 for 10%)")
                return
                
            username = context.args[0].replace('@', '')
            commission_percentage = float(context.args[1])
            
            if commission_percentage < 0 or commission_percentage > 100:
                await self.send_group_response(update, context, "❌ Commission rate must be between 0 and 100 (e.g., 10 for 10%, 100 for 100%)")
                return
                
            # Convert percentage to decimal for storage (10% = 0.1)
            commission_rate = commission_percentage / 100
                
            # Find user
            user_data = users_collection.find_one({'username': username})
            
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
                            # Generate link to the original game table message
                            table_link = self._generate_message_link(
                                game['chat_id'], 
                                int(game['admin_message_id'])
                            )
                            
                            await context.bot.send_message(
                                chat_id=user_data['user_id'],
                                text=(
                                    f"⌛ <b>Game Expired & Refunded</b>\n\n"
                                    f"Your game exceeded the 1-hour limit and has been automatically cancelled.\n\n"
                                    f"<b>Refund Amount:</b> ₹{refund_amount}\n"
                                    f"<b>New Balance:</b> ₹{new_balance}\n\n"
                                    f"📋 <a href='{table_link}'>View Game Table</a>"
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
        """Handle /balancesheet command to create/update balance sheet"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        
        try:
            logger.info(f"📊 Balance sheet command received from admin {update.effective_user.id}")
            
            # Create or update the balance sheet
            await self.create_new_balance_sheet(context)
            
            # Send confirmation message
            await self.send_group_response(update, context, "✅ Balance sheet updated and pinned successfully!")
            
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
                    # Find user with case-insensitive matching
                    user_data = users_collection.find_one({
                        '$or': [
                            {'username': {'$regex': f'^{re.escape(username)}$', '$options': 'i'}},
                            {'username': {'$regex': f'^@{re.escape(username)}$', '$options': 'i'}}
                        ]
                    })
                    
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
                                f"Your game has been cancelled by an admin.\n\n"
                                f"<b>Game:</b> {game_data['game_id']}\n"
                                f"<b>Refund Amount:</b> ₹{bet_amount}\n"
                                f"<b>New Balance:</b> ₹{new_balance}\n\n"
                                f"📋 <a href='{table_link}'>View Game Table</a>"
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
            
            # Top 5 users by balance
            top_users = list(users_collection.find(
                {'balance': {'$gt': 0}},
                {'username': 1, 'first_name': 1, 'balance': 1}
            ).sort('balance', -1).limit(5))
            
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
                
                "🏆 **TOP 5 USERS BY BALANCE:**\n"
            )
            
            if top_users:
                for i, user in enumerate(top_users, 1):
                    name = user.get('first_name', user.get('username', 'Unknown'))
                    balance = user.get('balance', 0)
                    stats_message += f"{i}. {name}: ₹{balance}\n"
            else:
                stats_message += "No users with positive balance\n"
            
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
                
                # Format with triangle emoji: 🔺account_name = balance
                content += f"🔺{account_name} = {balance}\n"
            
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
