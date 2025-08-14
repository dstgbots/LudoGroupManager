import os
import re
import asyncio
import time
from datetime import datetime, timedelta
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from pymongo import MongoClient
from dotenv import load_dotenv
import logging
import calendar
from collections import defaultdict
import html

# Add pyrogram support for editing admin messages
try:
    from pyrogram import Client
    from pyrogram import filters as pyrogram_filters
    PYROGRAM_AVAILABLE = True
except ImportError:
    PYROGRAM_AVAILABLE = False
    print("⚠️  Pyrogram not available. Install with: pip install pyrogram")

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class LudoBotManager:
    def __init__(self):
        self.bot_token = os.getenv('BOT_TOKEN')
        self.mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        self.database_name = os.getenv('DATABASE_NAME', 'ludo_bot')
        self.group_id = os.getenv('GROUP_ID')  # Your Ludo group chat ID
        
        # Validate GROUP_ID format
        if self.group_id:
            try:
                group_id_int = int(self.group_id)
                if group_id_int > 0:
                    logger.warning(f"⚠️  GROUP_ID ({self.group_id}) is positive. For supergroups, it should be negative (starting with -100)")
                logger.info(f"✅ GROUP_ID configured: {self.group_id}")
            except ValueError:
                logger.error(f"❌ Invalid GROUP_ID format: {self.group_id}. Should be a number.")
                raise Exception(f"Invalid GROUP_ID format: {self.group_id}")
        else:
            logger.error("❌ GROUP_ID not found in environment variables")
            raise Exception("GROUP_ID not found in environment variables")
        
        # Initialize MongoDB with error handling
        try:
            self.client = MongoClient(self.mongo_uri, serverSelectionTimeoutMS=5000)
            # Test connection
            self.client.server_info()
            self.db = self.client[self.database_name]
            self.users_collection = self.db.users
            self.games_collection = self.db.games
            self.transactions_collection = self.db.transactions
            logger.info("✅ MongoDB connection established successfully")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            raise Exception(f"Failed to connect to MongoDB: {e}")
        
        # Admin user IDs (add your admin user IDs here)
        admin_ids_str = os.getenv('ADMIN_IDS', '')
        self.admin_ids = []
        if admin_ids_str:
            try:
                self.admin_ids = list(map(int, admin_ids_str.split(',')))
            except ValueError:
                logger.error("❌ Invalid ADMIN_IDS format. Should be comma-separated numbers.")
        
        # Active games storage
        self.active_games = {}
        
        # Balance sheet message tracking
        self.balance_sheet_collection = self.db.balance_sheet
        self.pinned_balance_msg_id = None
        self._load_pinned_message_id()
        
        # Initialize Pyrogram client for handling edited messages and admin message editing
        self.pyro_client = None
        if PYROGRAM_AVAILABLE:
            try:
                api_id = os.getenv('API_ID', '18274091')
                api_hash = os.getenv('API_HASH', '97afe4ab12cb99dab4bed25f768f5bbc')
                
                # Validate API credentials
                if not api_id or not api_hash:
                    logger.warning("⚠️ API_ID or API_HASH not found in environment variables")
                    return
                
                try:
                    api_id_int = int(api_id)
                except ValueError:
                    logger.error(f"❌ Invalid API_ID format: {api_id}")
                    return
                
                logger.info(f"🔍 Pyrogram API credentials found: API_ID={api_id}")
                self.pyro_client = Client(
                    "ludo_bot_pyrogram",
                    api_id=api_id_int,
                    api_hash=api_hash,
                    no_updates=False  # We want to receive updates for edited messages
                )
                
                # Set up Pyrogram handlers for edited messages
                self._setup_pyrogram_handlers()
                
                logger.info("✅ Pyrogram client initialized for edited message handling and admin message editing")
                
            except Exception as e:
                logger.error(f"❌ Failed to initialize Pyrogram client: {e}")
                self.pyro_client = None
        else:
            logger.warning("⚠️ Pyrogram not available - edited message handling will be disabled")
    
    async def cleanup(self):
        """Cleanup resources when bot shuts down"""
        try:
            if self.pyro_client and self.pyro_client.is_connected:
                await self.pyro_client.stop()
                logger.info("✅ Pyrogram client stopped successfully")
        except Exception as e:
            logger.error(f"❌ Error stopping Pyrogram client: {e}")
        
        try:
            if self.client:
                self.client.close()
                logger.info("✅ MongoDB connection closed")
        except Exception as e:
            logger.error(f"❌ Error closing MongoDB connection: {e}")
    
    def _load_pinned_message_id(self):
        """Load the pinned balance sheet message ID from database"""
        try:
            pinned_data = self.balance_sheet_collection.find_one({'type': 'pinned_balance_sheet'})
            if pinned_data:
                self.pinned_balance_msg_id = pinned_data.get('message_id')
                logger.info(f"📌 Loaded pinned balance sheet message ID: {self.pinned_balance_msg_id}")
        except Exception as e:
            logger.error(f"Error loading pinned message ID: {e}")
    
    def _setup_pyrogram_handlers(self):
        """Set up Pyrogram handlers for edited messages and other updates"""
        if not self.pyro_client:
            return
            
        try:
            # Handler for edited messages in the configured group
            async def handle_pyrogram_edited_message(client, message):
                """Handle edited messages via Pyrogram - using test.py approach"""
                try:
                    logger.info(f"🔍 Pyrogram: Received edited message {message.id} in chat {message.chat.id}")
                    
                    # Check if this message has a winner (✅ mark)
                    winner = self.extract_winner_from_edited_message(message.text)
                    if winner and message.id in self.active_games:
                        game_data = self.active_games.pop(message.id)
                        logger.info(f"🏆 Winner: {winner} for game: {game_data}")
                        
                        # Send winner announcement to group
                        await client.send_message(
                            chat_id=message.chat.id,
                            text=f"🎉 Winner Found: @{winner}\n💰 Prize: ₹{game_data['amount']}"
                        )
                    else:
                        logger.info(f"📝 Pyrogram: No winner found or game not tracked")
                        
                except Exception as e:
                    logger.error(f"❌ Pyrogram: Error handling edited message: {e}")
            
            # Handler for new messages in the configured group (to detect game tables)
            async def handle_pyrogram_new_message(client, message):
                """Handle new messages via Pyrogram - using test.py approach"""
                try:
                    logger.info(f"🔍 Pyrogram: Received new message {message.id} in chat {message.chat.id}")
                    
                    # Check if this is a game table message from admin
                    if message.from_user.id in self.admin_ids:
                        game_data = self._extract_game_data_from_message(message.text, message.from_user.id, message.id, message.chat.id)
                        if game_data:
                            self.active_games[message.id] = game_data
                            logger.info(f"🎮 Game created: {game_data}")
                        
                except Exception as e:
                    logger.error(f"❌ Pyrogram: Error handling new message: {e}")
            
            # Add handlers using Pyrogram 1.x syntax
            from pyrogram.handlers import MessageHandler
            
            # Add edited message handler - in Pyrogram 1.x, edited messages are handled through MessageHandler
            self.pyro_client.add_handler(
                MessageHandler(
                    handle_pyrogram_edited_message,
                    pyrogram_filters.chat(int(self.group_id)) & pyrogram_filters.text & pyrogram_filters.edited
                )
            )
            
            # Add new message handler
            self.pyro_client.add_handler(
                MessageHandler(
                    handle_pyrogram_new_message,
                    pyrogram_filters.chat(int(self.group_id)) & pyrogram_filters.text & ~pyrogram_filters.edited
                )
            )
            
            logger.info("✅ Pyrogram handlers set up successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to set up Pyrogram handlers: {e}")
    
    async def _start_pyrogram_client(self):
        """Start the Pyrogram client and run it"""
        try:
            logger.info("🚀 Starting Pyrogram client...")
            await self.pyro_client.start()
            logger.info("✅ Pyrogram client started successfully")
            
            # Keep the client running - use a simple loop instead of idle()
            while True:
                try:
                    await asyncio.sleep(1)
                    if not self.pyro_client.is_connected:
                        logger.warning("⚠️ Pyrogram client disconnected, attempting to reconnect...")
                        await self.pyro_client.start()
                except Exception as e:
                    logger.error(f"❌ Pyrogram client error: {e}")
                    await asyncio.sleep(5)  # Wait before retrying
            
        except Exception as e:
            logger.error(f"❌ Failed to start Pyrogram client: {e}")
            # Set client to None so other parts of the code know it's not available
            self.pyro_client = None
    
    async def _process_pyrogram_edited_message(self, message):
        """Process edited messages received via Pyrogram"""
        if not self.pyro_client or not self.pyro_client.is_connected:
            logger.warning("⚠️ Pyrogram client not available for processing edited message")
            return
            
        try:
            logger.info(f"🔍 Processing Pyrogram edited message: {message.id}")
            
            # Check if this message contains a winner (✅ mark)
            if "✅" in message.text:
                logger.info("🏆 Pyrogram: Winner detected in edited message")
                
                # Find the corresponding game by message ID
                game_data = self.games_collection.find_one({
                    'admin_message_id': message.id,
                    'chat_id': message.chat.id
                })
                
                if game_data:
                    logger.info(f"🎮 Pyrogram: Found game {game_data['game_id']} for edited message")
                    
                    # Extract winner from the edited message
                    winner_username = self._extract_winner_from_edited_message(message.text)
                    
                    if winner_username:
                        logger.info(f"🏆 Pyrogram: Winner username extracted: {winner_username}")
                        
                        # Process the game result
                        await self._process_game_result_from_pyrogram(game_data, winner_username, message)
                    else:
                        logger.warning("⚠️ Pyrogram: Could not extract winner username from edited message")
                else:
                    logger.warning("⚠️ Pyrogram: No game found for edited message")
                    
        except Exception as e:
            logger.error(f"❌ Pyrogram: Error processing edited message: {e}")
    
    async def _process_pyrogram_new_game_table(self, message):
        """Process new game table messages received via Pyrogram"""
        if not self.pyro_client or not self.pyro_client.is_connected:
            logger.warning("⚠️ Pyrogram client not available for processing new game table")
            return
            
        try:
            logger.info(f"🔍 Processing Pyrogram new game table: {message.id}")
            
            # Extract game data from the message
            game_data = self._extract_game_data_from_message(message.text, message.from_user.id, message.id, message.chat.id)
            
            if game_data:
                logger.info(f"🎮 Pyrogram: Game data extracted successfully: {game_data['game_id']}")
                
                # Save game to database
                self.games_collection.insert_one(game_data)
                self.active_games[game_data['game_id']] = game_data
                
                # Send winner selection message to admin's DM
                await self._send_winner_selection_to_admin(game_data, message.from_user.id)
                
                # Send confirmation to group
                await self._send_group_confirmation(message.chat.id)
                
            else:
                logger.warning("⚠️ Pyrogram: Could not extract game data from message")
                
        except Exception as e:
            logger.error(f"❌ Pyrogram: Error processing new game table: {e}")
    
    def extract_winner_from_edited_message(self, message_text):
        """Extract winner username from edited message text - using test.py method"""
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
    
    def _extract_game_data_from_message(self, message_text, admin_user_id, message_id, chat_id):
        """Extract game data from message text using simplified line-by-line processing"""
        try:
            lines = message_text.strip().split("\n")
            usernames = []
            amount = None

            for line in lines:
                if "full" in line.lower():
                    match = re.search(r"(\d+)\s*[Ff]ull", line)
                    if match:
                        amount = int(match.group(1))
                else:
                    # Extract username with or without @
                    match = re.search(r"@?(\w+)", line)
                    if match:
                        username = match.group(1)
                        # Filter out common non-username words
                        if len(username) > 2 and not username.lower() in ['full', 'table', 'game']:
                            usernames.append(username)

            if not usernames or not amount:
                logger.warning("❌ Invalid table format - missing usernames or amount")
                return None

            if len(usernames) < 2:
                logger.warning("❌ Need at least 2 players for a game")
                return None

            # Create game data
            game_id = f"game_{int(time.time())}_{message_id}"
            game_data = {
                'game_id': game_id,
                'admin_user_id': admin_user_id,
                'admin_message_id': message_id,
                'chat_id': chat_id,
                'bet_amount': amount,
                'players': [{'username': username, 'bet_amount': amount} for username in usernames],
                'total_amount': amount * len(usernames),
                'status': 'active',
                'created_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(hours=1)
            }
            return game_data
        except Exception as e:
            logger.error(f"❌ Error extracting game data: {e}")
            return None
    
    # Removed old winner selection method - using test.py approach instead
    
    async def _send_group_confirmation(self, chat_id):
        """Send confirmation message to group"""
        if not self.pyro_client or not self.pyro_client.is_connected:
            logger.warning("⚠️ Pyrogram client not available for sending group confirmation")
            return
            
        try:
            await self.pyro_client.send_message(
                chat_id=chat_id,
                text="🎮 Game table processed! Admin will select winner via DM."
            )
            logger.info(f"✅ Group confirmation sent to chat {chat_id}")
            
        except Exception as e:
            logger.error(f"❌ Error sending group confirmation: {e}")
    
    async def _process_game_result_from_pyrogram(self, game_data, winner_username, message):
        """Process game result from Pyrogram edited message"""
        if not self.pyro_client or not self.pyro_client.is_connected:
            logger.warning("⚠️ Pyrogram client not available for processing game result")
            return
            
        try:
            logger.info(f"🎮 Processing game result for {game_data['game_id']}, winner: {winner_username}")
            
            # Find winner player data
            winner_player = None
            for player in game_data['players']:
                if player['username'] == winner_username:
                    winner_player = player
                    break
            
            if not winner_player:
                logger.error(f"❌ Winner player not found: {winner_username}")
                return
            
            # Calculate winnings
            total_amount = game_data['total_amount']
            winner_amount = total_amount * 0.8  # 80% to winner
            admin_fee = total_amount * 0.2      # 20% admin fee
            
            # Update winner's balance
            winner_user = self.users_collection.find_one({'username': winner_username})
            if winner_user:
                new_balance = winner_user['balance'] + winner_amount
                self.users_collection.update_one(
                    {'username': winner_username},
                    {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                )
                
                # Record transaction
                transaction_data = {
                    'user_id': winner_user['user_id'],
                    'type': 'win',
                    'amount': winner_amount,
                    'description': f'Game {game_data["game_id"]} - Winner',
                    'timestamp': datetime.now(),
                    'game_id': game_data['game_id']
                }
                self.transactions_collection.insert_one(transaction_data)
                
                # Notify winner
                await self.pyro_client.send_message(
                    chat_id=winner_user['user_id'],
                    text=f"🎉 **Congratulations! You won!**\n\n"
                         f"**Game:** {game_data['game_id']}\n"
                         f"**Winnings:** ₹{winner_amount}\n"
                         f"**New Balance:** ₹{new_balance}"
                )
            
            # Update game status
            self.games_collection.update_one(
                {'game_id': game_data['game_id']},
                {'$set': {
                    'status': 'completed',
                    'winner': winner_username,
                    'winner_amount': winner_amount,
                    'admin_fee': admin_fee,
                    'completed_at': datetime.now()
                }}
            )
            
            # Remove from active games
            if game_data['game_id'] in self.active_games:
                del self.active_games[game_data['game_id']]
            
            logger.info(f"✅ Game result processed successfully for {game_data['game_id']}")
            
        except Exception as e:
            logger.error(f"❌ Error processing game result: {e}")
    
    def is_configured_group(self, chat_id: int) -> bool:
        """Check if the given chat_id matches the configured group ID"""
        try:
            configured_group_id = int(self.group_id) if self.group_id else None
            return chat_id == configured_group_id
        except (ValueError, TypeError):
            logger.error(f"Invalid GROUP_ID format: {self.group_id}")
            return False
    
    async def expire_old_games(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Check and expire games that have been running for more than 1 hour"""
        try:
            current_time = datetime.now()
            expired_games = self.games_collection.find({
                'status': 'active',
                'expires_at': {'$lt': current_time}
            })
            
            for game_data in expired_games:
                logger.info(f"Expiring game {game_data['game_id']} - exceeded 1 hour limit")
                
                # Refund all players
                for player in game_data['players']:
                    user_data = self.users_collection.find_one({'user_id': player['user_id']})
                    if user_data:
                        refund_amount = player['bet_amount']
                        new_balance = user_data['balance'] + refund_amount
                        
                        self.users_collection.update_one(
                            {'user_id': player['user_id']},
                            {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                        )
                        
                        # Record refund transaction
                        transaction_data = {
                            'user_id': player['user_id'],
                            'type': 'refund',
                            'amount': refund_amount,
                            'description': f'Game {game_data["game_id"]} expired after 1 hour',
                            'timestamp': datetime.now(),
                            'game_id': game_data['game_id']
                        }
                        self.transactions_collection.insert_one(transaction_data)
                        
                        # Notify player
                        try:
                            await context.bot.send_message(
                                chat_id=player['user_id'],
                                text=f"🕐 Game Expired!\n\nYour game exceeded the 1-hour limit and has been automatically cancelled.\n₹{refund_amount} has been refunded to your account.\nNew balance: ₹{new_balance}"
                            )
                        except:
                            pass
                
                # Update game status
                self.games_collection.update_one(
                    {'game_id': game_data['game_id']},
                    {
                        '$set': {
                            'status': 'expired',
                            'expired_at': current_time
                        }
                    }
                )
                
                # Remove from active games
                if game_data['game_id'] in self.active_games:
                    del self.active_games[game_data['game_id']]
                
                # Update balance sheet after refunds
                await self.update_balance_sheet(context)
                
                # Notify group
                try:
                    await context.bot.send_message(
                        chat_id=int(self.group_id),
                        text=f"⏰ Game Expired: {game_data['game_id']}\nExceeded 1-hour limit. All players refunded."
                    )
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Error expiring games: {e}")
    
    async def send_auto_delete_message(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, delete_after: int = 5) -> None:
        """Send a message that will be auto-deleted after specified seconds"""
        try:
            message = await context.bot.send_message(chat_id=chat_id, text=text)
            
            # Schedule deletion after specified seconds
            async def delete_message():
                await asyncio.sleep(delete_after)
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
                except Exception as e:
                    logger.warning(f"Could not delete message: {e}")
            
            # Create task for deletion (fire and forget)
            asyncio.create_task(delete_message())
            
        except Exception as e:
            logger.error(f"Error sending auto-delete message: {e}")
    
    async def send_group_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        """Send response in group with auto-deletion of both command and response, or direct reply if not in group"""
        if self.is_configured_group(update.effective_chat.id):
            # In group - send with auto-deletion and delete user command too
            await self.send_auto_delete_message(context, update.effective_chat.id, text)
            
            # Also delete the user's command message after 5 seconds
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
            
            # Create task for user command deletion (fire and forget)
            asyncio.create_task(delete_user_command())
        else:
            # Private chat - send normally
            await update.message.reply_text(text)
        
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
                'balance': 0,
                'commission_rate': 5,  # Default 5% commission
                'created_at': datetime.now()
            }
            
            self.users_collection.update_one(
                {'user_id': user.id},
                {'$setOnInsert': user_data, '$set': {'last_updated': datetime.now()}},
                upsert=True
            )
            
            welcome_message = f"""
🎮 Welcome to Ludo Group Manager Bot!

Hello {user.first_name}! I'm here to help manage your Ludo games and track your balance.

Available Commands:
/balance - Check your current balance
/help - Show this help message

Good luck with your games! 🎲
            """
            
            if is_group:
                await self.send_group_response(update, context, welcome_message)
            else:
                await update.message.reply_text(welcome_message)
            
        except Exception as e:
            logger.error(f"Error in start_command: {e}")
            error_msg = "❌ Sorry, there was an error setting up your account. Please try again later."
            if is_group:
                await self.send_group_response(update, context, error_msg)
            else:
                await update.message.reply_text(error_msg)
    
    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balance command"""
        user_id = update.effective_user.id
        is_group = self.is_configured_group(update.effective_chat.id)
        
        # In group, only admins can use balance command
        if is_group and user_id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use commands in the group. Please message me privately to check balance.")
            return
        
        user_data = self.users_collection.find_one({'user_id': user_id})
        if user_data:
            balance = user_data.get('balance', 0)
            commission_rate = user_data.get('commission_rate', 5)
            
            balance_message = f"""
💰 Your Account Balance

Current Balance: ₹{balance}
Commission Rate: {commission_rate}%

Use /help for more commands.
            """
        else:
            balance_message = "❌ Account not found. Please use /start to create your account."
        
        if is_group:
            await self.send_group_response(update, context, balance_message)
        else:
            await update.message.reply_text(balance_message)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        is_admin = update.effective_user.id in self.admin_ids
        is_group = self.is_configured_group(update.effective_chat.id)
        
        if is_group and not is_admin:
            # Non-admin in group gets limited help
            help_message = """
🎮 Ludo Group Manager Bot

Use /start in private chat to set up your account.
Only admins can use commands in the group.
            """
        else:
            # Full help for admins or private chats
            help_message = """
🎮 Ludo Group Manager Bot Help

User Commands:
/start - Initialize your account
/balance - Check your current balance
/help - Show this help message

Admin Commands (Group only):
📝 **NEW GAME PROCESS:**
• Send table directly with 'Full' keyword
• Bot automatically detects and processes
• Bot sends winner selection buttons to your DM
• Click winner button OR manually edit table to add ✅ for winners
• Bot automatically processes results

📝 **MANUAL EDITING (if buttons don't work):**
• Edit your table message in the group
• Add ✅ after the winner's username
• Example: @player1 ✅
• Bot will detect the edit and process results

Example table format:
@player1
@player2
400 Full

/activegames - Show all currently running games
/expiregames - Manually expire old games (1+ hours)
/cancel - Cancel the last game (reply to game table)
/setcommission @user rate - Set commission rate for user
/addbalance @user amount - Add balance to user (supports mentions, fills negative balance first)
/withdraw @user amount - Withdraw from user (supports mentions, can create negative balance)
/balancesheet - Create/update pinned balance sheet
/stats - Professional analytics dashboard with calendar selection

💰 Negative Balance Support:
- Users can play games even with insufficient balance
- Withdrawals can exceed balance, creating debt
- Adding balance automatically fills debt first

How it works:
1. Admins confirm payments: "3000 received @username"
2. Admins send game tables: "@player1 @player2 400 Full"
3. Bot automatically processes tables and deducts bets
4. Admin edits table to add ✅ for winners
5. Bot automatically processes results and distributes winnings
6. Winners get balance after commission deduction
7. Multiple games can run simultaneously for up to 1 hour each
8. Games auto-expire after 1 hour with full refunds
9. Balance sheet automatically updates after each transaction and every 5 minutes

⚠️ Note: In group chat, only admins can use commands. Game tables are sent directly by admins.
Most bot responses are auto-deleted after 5 seconds (except game messages).

Good luck! 🎲
            """
        
        if is_group:
            await self.send_group_response(update, context, help_message)
        else:
            await update.message.reply_text(help_message)
    
    async def process_payment_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process payment confirmation messages from admins - using 'Recived From' pattern"""
        if not self.is_configured_group(update.effective_chat.id):
            return
            
        # Only admins can confirm payments
        if update.effective_user.id not in self.admin_ids:
            return
        
        message_text = update.message.text
        
        # Pattern to match payment messages: "amount Recived From @username ✅"
        payment_pattern = r'(\d+(?:\.\d+)?)\s+Recived\s+From\s+(?:@(\w+)|.*?)\s*✅'
        match = re.search(payment_pattern, message_text, re.IGNORECASE)
        
        if match:
            amount = float(match.group(1))
            username = match.group(2)
            
            # Try to get user from mention entities first (preferred)
            user_info = None
            if update.message.entities:
                user_info = self._extract_user_from_entities(update.message)
            
            # Fallback to username lookup
            if not user_info and username:
                user_data = self.users_collection.find_one({'username': username})
                if user_data:
                    user_info = {
                        'user_id': user_data['user_id'],
                        'username': user_data.get('username', username)
                    }
            
            if user_info:
                # Add balance to user
                user_data = self.users_collection.find_one({'user_id': user_info['user_id']})
                if not user_data:
                    # Create new user if doesn't exist
                    user_data = {
                        'user_id': user_info['user_id'],
                        'username': user_info['username'],
                        'balance': 0,
                        'created_at': datetime.now()
                    }
                    self.users_collection.insert_one(user_data)
                
                old_balance = user_data.get('balance', 0)
                new_balance = old_balance + amount
                
                self.users_collection.update_one(
                    {'user_id': user_info['user_id']},
                    {
                        '$set': {
                            'balance': new_balance,
                            'username': user_info['username'],
                            'last_updated': datetime.now()
                        }
                    }
                )
                
                # Record transaction
                transaction_data = {
                    'user_id': user_info['user_id'],
                    'type': 'deposit',
                    'amount': amount,
                    'description': f'Payment confirmed by admin - Recived From',
                    'timestamp': datetime.now(),
                    'admin_id': update.effective_user.id
                }
                self.transactions_collection.insert_one(transaction_data)
                
                # Send confirmation message (as reply to admin message)
                username_display = f"@{user_info['username']}" if user_info['username'] else f"User {user_info['user_id']}"
                confirmation_msg = f"✅ {amount} added successfully to {username_display}"
                await update.message.reply_text(confirmation_msg)
                
                logger.info(f"Balance updated: +{amount} to {user_info['user_id']} by admin {update.effective_user.id}")
            else:
                await update.message.reply_text("❌ Cannot resolve user. Please use a clickable mention or ask the user to /start the bot.")
    
    def _extract_user_from_entities(self, message):
        """Extract user info from message entities (prefers text_mention with user_id)"""
        for entity in message.entities or []:
            if entity.type == "text_mention" and entity.user:
                return {
                    "user_id": entity.user.id,
                    "username": entity.user.username or f"user_{entity.user.id}"
                }
            if entity.type == "mention":
                mention_text = message.text[entity.offset:entity.offset + entity.length]
                username = mention_text.lstrip('@')
                user_doc = self.users_collection.find_one({"username": username})
                if user_doc:
                    return {
                        "user_id": user_doc["user_id"],
                        "username": user_doc.get("username") or f"user_{user_doc['user_id']}"
                    }
        return None
    
    async def detect_and_process_game_table(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Detect and store game table - using test.py approach (just store, don't process)"""
        if not self.is_configured_group(update.effective_chat.id):
            return
            
        # Only admins can create game tables
        if update.effective_user.id not in self.admin_ids:
            return
        
        message_text = update.message.text
        
        # Use the exact test.py method
        game_data = self._extract_game_data_from_message(message_text, update.effective_user.id, update.message.message_id, update.effective_chat.id)
        if game_data:
            # Store game using message ID as key (like test.py)
            self.active_games[update.message.message_id] = game_data
            logger.info(f"🎮 Game created: {game_data}")
            # Note: No balance deduction, no notifications - just store and wait for edit
    
    async def game_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /game command with help text for game table format"""
        help_message = (
            "🎮 **Game Table Format:**\n\n"
            "Send a message with player usernames and amount:\n"
            "```\n"
            "@player1\n"
            "@player2\n"
            "@player3\n"
            "100 Full\n"
            "```\n\n"
            "• Each player on a new line\n"
            "• Add amount followed by 'Full'\n"
            "• Bot processes results automatically\n\n"
            "Example table format:\n"
            "@player1\n@player2\n400 Full")
        
        is_group = self.is_configured_group(update.effective_chat.id)
        if is_group:
            await self.send_group_response(update, context, help_message)
        else:
            await update.message.reply_text(help_message, parse_mode=ParseMode.MARKDOWN)
        return
        
        for username in username_matches:
            user_data = self.users_collection.find_one({'username': username})
            if user_data:
                # Deduct bet amount from user balance (allow negative balances)
                old_balance = user_data.get('balance', 0)
                new_balance = old_balance - bet_amount
                
                self.users_collection.update_one(
                    {'username': username},
                    {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                )
                
                # Record transaction
                transaction_data = {
                    'user_id': user_data['user_id'],
                    'type': 'bet',
                    'amount': -bet_amount,
                    'description': f'Bet placed in game {game_id}',
                    'timestamp': datetime.now(),
                    'game_id': game_id
                }
                self.transactions_collection.insert_one(transaction_data)
                
                game_data['players'].append({
                    'user_id': user_data['user_id'],
                    'username': username,
                    'bet_amount': bet_amount,
                    'commission_rate': user_data.get('commission_rate', 5)
                })
                
                total_pot += bet_amount
                valid_players += 1
                
                # Notify user privately
                try:
                    if new_balance >= 0:
                        balance_display = f"₹{new_balance}"
                    else:
                        balance_display = f"-₹{abs(new_balance)} (debt)"
                    
                    await context.bot.send_message(
                        chat_id=user_data['user_id'],
                        text=f"🎮 Game Started!\n\nYou've joined a game with ₹{bet_amount} bet.\nNew balance: {balance_display}\n\nBest of luck! 🎲"
                    )
                except:
                    pass
            else:
                logger.warning(f"❌ User @{username} not found in database")
        
        if valid_players >= 2:
            # Store game data
            logger.info(f"🔍 Storing game data in database...")
            result = self.games_collection.insert_one(game_data)
            logger.info(f"🔍 Game stored with ID: {result.inserted_id}")
            self.active_games[game_id] = game_data
            logger.info(f"🔍 Game added to active_games: {game_id}")
            
            # Send winner selection message to ADMIN'S DM (not in group)
            players_list = "\n".join([f"@{player['username']}" for player in game_data['players']])
            winner_selection_msg = f"🎮 Winner Selection for {game_id}\n\n🎲 Game ID: {game_id}\n\n{players_list}\n\n{bet_amount} Full\n\n👇 Click to declare winner:"
            
            # Create winner selection buttons
            keyboard = []
            for player in game_data['players']:
                callback_data = f"winner_{game_id}_{player['username']}"
                logger.info(f"🔍 Creating button for {player['username']} with callback: {callback_data}")
                button = InlineKeyboardButton(
                    text=f"{player['username']} wins",
                    callback_data=callback_data
                )
                keyboard.append([button])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send winner selection message to ADMIN'S DM (not in group)
            try:
                admin_user_id = update.effective_user.id
                winner_msg = await context.bot.send_message(
                    chat_id=admin_user_id,  # Send to admin's DM
                    text=winner_selection_msg,
                    reply_markup=reply_markup
                )
                
                # Store the winner selection message ID
                self.games_collection.update_one(
                    {'game_id': game_id},
                    {'$set': {'winner_selection_msg_id': winner_msg.message_id}}
                )
                
                logger.info(f"✅ Winner selection message sent to admin DM for game: {game_id}")
                
                # Send a simple confirmation in group (just to acknowledge the table was processed)
                group_confirmation = f"🎮 Game table processed! Admin will select winner via DM."
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=group_confirmation
                )
                
            except Exception as e:
                logger.error(f"❌ Could not send winner selection message to admin DM: {e}")
                # Fallback: send error message in group
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Could not process game table. Please try again."
                )
            
            # Update balance sheet after game creation
            await self.update_balance_sheet(context)
        else:
            logger.error(f"❌ Not enough valid players for game: {valid_players}")
            # Send error message in group only if there's an error
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Could not process game table - not enough valid players found."
                )
            except Exception as e:
                logger.error(f"❌ Could not send error message: {e}")
    
    async def game_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /game command to start new games - DISABLED"""
        # This command is now disabled - admins send tables directly
        await self.send_group_response(update, context, 
            "❌ The /game command is no longer used.\n\n"
            "📝 **New Process:**\n"
            "• Admin sends table directly with 'Full' keyword\n"
            "• Bot automatically detects and processes the table\n"
            "• Admin edits message to add ✅ tick marks for winners\n"
            "• Bot processes results automatically\n\n"
            "Example table format:\n"
            "@player1\n@player2\n400 Full")
        return
    
    async def process_game_result(self, update: Update, context: ContextTypes.DEFAULT_TYPE, is_edit: bool = False):
        """Process game results when admin adds checkmark emoji to ANY message"""
        logger.info(f"🎮 GAME RESULT PROCESSING - is_edit: {is_edit}")
        logger.info(f"🎮 Message type: {'EDITED' if is_edit else 'NEW'}")
        
        if not self.is_configured_group(update.effective_chat.id):
            logger.info("❌ Not in configured group")
            return
            
        # Only admins can declare game results
        if update.effective_user.id not in self.admin_ids:
            logger.info("❌ Not an admin")
            return
        
        # Check if this is a manually edited message that might contain game results
        if is_edit:
            logger.info("🔍 Processing manually edited message for game results...")
            # This could be an admin manually editing a table to add ✅ marks
            # Try manual detection first
            if update.edited_message:
                manual_game_data, manual_winners = await self.check_manual_table_edit(
                    update.edited_message.text,
                    update.edited_message.message_id,
                    update.edited_message.chat.id
                )
                if manual_game_data and manual_winners:
                    logger.info("✅ Manual detection successful! Processing game result...")
                    await self.process_game_result_from_winner(manual_game_data, manual_winners, context)
                    return
        
        # Get message text from either original or edited message
        if is_edit and update.edited_message:
            message_text = update.edited_message.text
            message_id = update.edited_message.message_id
            logger.info(f"📝 Processing EDITED message text: '{message_text}'")
            logger.info(f"📝 Raw message length: {len(message_text)}")
            logger.info(f"📝 Message contains ✅: {'✅' in message_text}")
            logger.info(f"📝 Message contains @: {'@' in message_text}")
            # Log each line separately for debugging
            lines = message_text.split('\n')
            for i, line in enumerate(lines):
                logger.info(f"📝 Line {i+1}: '{line}' (length: {len(line)})")
        else:
            message_text = update.message.text
            message_id = update.message.message_id
            logger.info(f"📝 Processing NEW message text: '{message_text}'")
        
        # Look for checkmark emoji (✅) next to usernames in ANY message
        # Updated patterns to handle the actual format: @Username ✅
        winner_pattern = r'@([a-zA-Z0-9_]+)\s*✅'
        logger.info(f"🔍 Searching for pattern: {winner_pattern}")
        winner_matches = re.findall(winner_pattern, message_text, re.IGNORECASE)
        
        logger.info(f"🏆 Found winners: {winner_matches}")
        logger.info(f"📊 Total winners found: {len(winner_matches)}")
        
        # Also try alternative patterns in case there are formatting issues
        alt_patterns = [
            r'@([a-zA-Z0-9_]+)\s*✅',  # Username with underscore + checkmark
            r'@([a-zA-Z0-9_]+).*?✅',  # Username followed by anything then checkmark
            r'✅.*?@([a-zA-Z0-9_]+)',  # Checkmark before username
            r'@([a-zA-Z0-9_]+)\s+✅', # Username with required space before checkmark
            r'@([a-zA-Z0-9_]+)✅',     # Username directly followed by checkmark (no space)
            # Handle different checkmark variations
            r'@([a-zA-Z0-9_]+)\s*[✓✔✅☑️]',  # Username with various checkmark symbols
            r'@([a-zA-Z0-9_]+)[✓✔✅☑️]',     # Username directly followed by checkmark symbols
        ]
        
        for i, pattern in enumerate(alt_patterns):
            alt_matches = re.findall(pattern, message_text, re.IGNORECASE)
            logger.info(f"🔍 Pattern {i+1} '{pattern}': {alt_matches}")
            if alt_matches and not winner_matches:
                winner_matches = alt_matches
                logger.info(f"✅ Using alternative pattern {i+1} results")
        
        # If still no winners found, try a more flexible approach
        if not winner_matches:
            logger.info("🔍 No winners found with standard patterns, trying flexible search...")
            # Look for any line that contains @username followed by ✅ anywhere on the same line
            lines = message_text.split('\n')
            for line in lines:
                line = line.strip()
                if '✅' in line and '@' in line:
                    # Extract username from line containing checkmark
                    username_match = re.search(r'@([a-zA-Z0-9_]+)', line)
                    if username_match:
                        username = username_match.group(1)
                        if username not in winner_matches:
                            winner_matches.append(username)
                            logger.info(f"✅ Found winner with flexible search: {username}")
            
            # If still no winners, try the most flexible approach - search the entire message
            if not winner_matches:
                logger.info("🔍 Trying most flexible search across entire message...")
                # Search for any @username that appears before a ✅ anywhere in the message
                all_usernames = re.findall(r'@([a-zA-Z0-9_]+)', message_text)
                checkmark_pos = message_text.find('✅')
                if checkmark_pos > 0 and all_usernames:
                    # Find usernames that appear before the checkmark
                    for username in all_usernames:
                        username_pos = message_text.find(f'@{username}')
                        if username_pos < checkmark_pos:
                            if username not in winner_matches:
                                winner_matches.append(username)
                                logger.info(f"✅ Found winner with position-based search: {username}")
        
        logger.info(f"🎯 Final winner matches: {winner_matches}")
        
        if winner_matches:
            # First, try to find the game by message ID (most reliable)
            game_data = self.games_collection.find_one({
                'message_id': message_id,
                'status': 'active'
            })
            
            if not game_data:
                # If not found by message ID, check all active games to find which game these winners belong to
                active_games = list(self.games_collection.find({'status': 'active'}))
                logger.info(f"🔍 Checking {len(active_games)} active games for winners")
                
                for game in active_games:
                    # Check if any of the winners are players in this game
                    game_winners = []
                    
                    for winner_name in winner_matches:
                        # Find winner in this game's players
                        for player in game['players']:
                            if player['username'].lower() == winner_name.lower():
                                game_winners.append(player)
                                break
                    
                    # If we found winners for this game, use it
                    if game_winners:
                        game_data = game
                        logger.info(f"✅ Found matching game: {game['game_id']}")
                        break
            
            if game_data:
                logger.info(f"🎮 Processing game result for game {game_data['game_id']} with winners: {[w['username'] for w in winner_matches]}")
                
                # Find the actual winner players from the game data
                game_winners = []
                for winner_name in winner_matches:
                    for player in game_data['players']:
                        if player['username'].lower() == winner_name.lower():
                            game_winners.append(player)
                            break
                
                if not game_winners:
                    logger.error(f"❌ No matching winners found in game {game_data['game_id']}")
                    return
                
                # Calculate total pot from all players
                total_pot = sum(player['bet_amount'] for player in game_data['players'])
                
                # Distribute winnings among winners
                winnings_per_winner = total_pot // len(game_winners)
                
                for winner in game_winners:
                    commission_rate = winner['commission_rate']
                    commission_amount = (winnings_per_winner * commission_rate) // 100
                    final_winnings = winnings_per_winner - commission_amount
                    
                    # Add winnings to winner's balance
                    user_data = self.users_collection.find_one({'user_id': winner['user_id']})
                    new_balance = user_data['balance'] + final_winnings
                    
                    self.users_collection.update_one(
                        {'user_id': winner['user_id']},
                        {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                    )
                    
                    # Record winning transaction
                    transaction_data = {
                        'user_id': winner['user_id'],
                        'type': 'win',
                        'amount': final_winnings,
                        'description': f'Won game {game_data["game_id"]} (Commission: ₹{commission_amount})',
                        'timestamp': datetime.now(),
                        'game_id': game_data['game_id']
                    }
                    self.transactions_collection.insert_one(transaction_data)
                    
                    # Notify winner
                    try:
                        group_message_link = f"https://t.me/c/{str(self.group_id)[4:]}/{message_id}"
                        await context.bot.send_message(
                            chat_id=winner['user_id'],
                            text=f"🎉 You won!\n\n💰 Prize: ₹{final_winnings} (after {commission_rate}% commission)\n📊 New balance: ₹{new_balance}\n\n🔗 Game: {group_message_link}"
                        )
                    except:
                        pass
                
                # Notify losers
                for player in game_data['players']:
                    if player not in game_winners:
                        try:
                            await context.bot.send_message(
                                chat_id=player['user_id'],
                                text=f"😔 Better luck next time!\n\nYou lost ₹{player['bet_amount']} in this match.\nHope you win the next one! 🎲"
                            )
                        except:
                            pass
                
                # Update game status
                self.games_collection.update_one(
                    {'game_id': game_data['game_id']},
                    {
                        '$set': {
                            'status': 'completed',
                            'winners': [w['username'] for w in game_winners],
                            'completed_at': datetime.now()
                        }
                    }
                )
                
                # Remove from active games
                if game_data['game_id'] in self.active_games:
                    del self.active_games[game_data['game_id']]
                
                # Update balance sheet after game completion
                await self.update_balance_sheet(context)
                
                logger.info(f"✅ Game {game_data['game_id']} completed successfully")
            else:
                logger.info("❌ No active game found for these winners")
        else:
            logger.info("No winners found in message")
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel a game and refund players"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        
        if not update.message.reply_to_message:
            await self.send_group_response(update, context, "❌ Please reply to a game table message to cancel it.")
            return
        
        original_message_id = update.message.reply_to_message.message_id
        game_data = self.games_collection.find_one({'message_id': original_message_id, 'status': 'active'})
        
        if game_data:
            # Refund all players
            for player in game_data['players']:
                user_data = self.users_collection.find_one({'user_id': player['user_id']})
                refund_amount = player['bet_amount']
                new_balance = user_data['balance'] + refund_amount
                
                self.users_collection.update_one(
                    {'user_id': player['user_id']},
                    {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                )
                
                # Record refund transaction
                transaction_data = {
                    'user_id': player['user_id'],
                    'type': 'refund',
                    'amount': refund_amount,
                    'description': f'Game {game_data["game_id"]} cancelled by admin',
                    'timestamp': datetime.now(),
                    'game_id': game_data['game_id']
                }
                self.transactions_collection.insert_one(transaction_data)
                
                # Notify player
                try:
                    await context.bot.send_message(
                        chat_id=player['user_id'],
                        text=f"🔄 Game Cancelled!\n\n₹{refund_amount} has been refunded to your account.\nNew balance: ₹{new_balance}"
                    )
                except:
                    pass
            
            # Update game status
            self.games_collection.update_one(
                {'game_id': game_data['game_id']},
                {
                    '$set': {
                        'status': 'cancelled',
                        'cancelled_at': datetime.now(),
                        'cancelled_by': update.effective_user.id
                    }
                }
            )
            
            # Remove from active games
            if game_data['game_id'] in self.active_games:
                del self.active_games[game_data['game_id']]
            
            # Update balance sheet after refunds
            await self.update_balance_sheet(context)
            
            await self.send_group_response(update, context, "✅ Game cancelled and all players refunded!")
        else:
            await self.send_group_response(update, context, "❌ No active game found for this message.")
    
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
            
            if commission_rate < 0 or commission_rate > 50:
                await self.send_group_response(update, context, "❌ Commission rate must be between 0% and 50%")
                return
            
            result = self.users_collection.update_one(
                {'username': username},
                {'$set': {'commission_rate': commission_rate, 'last_updated': datetime.now()}}
            )
            
            if result.matched_count > 0:
                await self.send_group_response(update, context, f"✅ Commission rate set to {commission_rate}% for @{username}")
            else:
                await self.send_group_response(update, context, f"❌ User @{username} not found")
                
        except ValueError:
            await self.send_group_response(update, context, "❌ Invalid commission rate. Please enter a number.")
        except Exception as e:
            await self.send_group_response(update, context, f"❌ Error: {str(e)}")
    
    async def add_balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually add balance to a user - supports negative balance filling and mentions"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        
        try:
            if len(context.args) != 2:
                await self.send_group_response(update, context, 
                    "Usage: /addbalance @username amount or mention user and amount\n"
                    "Examples:\n"
                    "/addbalance @john 500\n"
                    "/addbalance @Gopal M 1000")
                return
            
            user_identifier = context.args[0].replace('@', '')
            amount = int(context.args[1])
            
            if amount <= 0:
                await self.send_group_response(update, context, "❌ Amount must be positive!")
                return
            
            # Check for mentions in the message first (supports users without username)
            user_data = None
            mentioned_user_id = None
            
            if update.message.entities:
                for entity in update.message.entities:
                    if entity.type == "text_mention":
                        # User mentioned without username
                        mentioned_user_id = entity.user.id
                        logger.info(f"📧 Found text mention for user ID: {mentioned_user_id}")
                        break
                    elif entity.type == "mention":
                        # User mentioned with username (@username)
                        # Extract username from the mention in the text
                        start = entity.offset
                        length = entity.length
                        mentioned_username = update.message.text[start:start+length].replace('@', '')
                        logger.info(f"📧 Found username mention: {mentioned_username}")
                        user_data = self.users_collection.find_one({'username': mentioned_username})
                        break
            
            # If we found a mentioned user ID, look them up
            if mentioned_user_id:
                user_data = self.users_collection.find_one({'user_id': mentioned_user_id})
                if not user_data:
                    await self.send_group_response(update, context, 
                        f"❌ Mentioned user not found in database! They need to use /start first.")
                    return
            
            # If no mention found, try to find by username from command args
            if not user_data:
                user_data = self.users_collection.find_one({'username': user_identifier})
            
            # If still no user found, try to find by user_id if it's numeric
            if not user_data and user_identifier.isdigit():
                user_data = self.users_collection.find_one({'user_id': int(user_identifier)})
            
            if user_data:
                old_balance = user_data.get('balance', 0)
                
                # Smart balance calculation: fill negative balance first
                if old_balance < 0:
                    # User has negative balance (debt)
                    debt_amount = abs(old_balance)
                    if amount >= debt_amount:
                        # Amount covers the debt and more
                        new_balance = amount - debt_amount
                        filled_debt = debt_amount
                        remaining_added = amount - debt_amount
                    else:
                        # Amount partially covers the debt
                        new_balance = old_balance + amount
                        filled_debt = amount
                        remaining_added = 0
                    
                    # Get display name (username or first name)
                    display_name = user_data.get('username', user_data.get('first_name', 'Unknown User'))
                    
                    response_msg = f"✅ Added ₹{amount} to {display_name}'s account\n"
                    response_msg += f"💸 Debt cleared: ₹{filled_debt}\n"
                    if remaining_added > 0:
                        response_msg += f"💰 New positive balance: ₹{new_balance}\n"
                    else:
                        response_msg += f"💰 Remaining debt: ₹{abs(new_balance)}\n"
                    response_msg += f"📊 Balance: {old_balance} → {new_balance}"
                else:
                    # User has positive balance, simply add
                    new_balance = old_balance + amount
                    display_name = user_data.get('username', user_data.get('first_name', 'Unknown User'))
                    response_msg = f"✅ Added ₹{amount} to {display_name}'s account\n"
                    response_msg += f"💰 Balance: ₹{old_balance} → ₹{new_balance}"
                
                self.users_collection.update_one(
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
                self.transactions_collection.insert_one(transaction_data)
                
                await self.send_group_response(update, context, response_msg)
                
                # Update balance sheet after manual balance addition
                await self.update_balance_sheet(context)
                
                # Notify user
                try:
                    if new_balance >= 0:
                        user_balance_display = f"₹{new_balance}"
                    else:
                        user_balance_display = f"-₹{abs(new_balance)} (debt)"
                    
                    await context.bot.send_message(
                        chat_id=user_data['user_id'],
                        text=f"💰 Balance Added!\n\n₹{amount} has been added to your account by admin.\nNew balance: {user_balance_display}"
                    )
                except:
                    pass
            else:
                await self.send_group_response(update, context, f"❌ User {user_identifier} not found in database! They need to use /start first.")
                
        except ValueError:
            await self.send_group_response(update, context, "❌ Invalid amount. Please enter a number.")
        except Exception as e:
            await self.send_group_response(update, context, f"❌ Error: {str(e)}")
    
    async def withdraw_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /withdraw command (admin only) - supports negative balances"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        
        try:
            if len(context.args) != 2:
                await self.send_group_response(update, context, 
                    "❌ Usage: /withdraw @username amount, mention user, or userid amount\n"
                    "Examples:\n"
                    "/withdraw @john 500\n"
                    "/withdraw @Gopal M 300 (mention)\n"
                    "/withdraw 123456789 300")
                return
            
            target_identifier = context.args[0]
            amount = int(context.args[1])
            
            if amount <= 0:
                await self.send_group_response(update, context, "❌ Amount must be positive!")
                return
            
            # Check for mentions in the message first (supports users without username)
            user_data = None
            mentioned_user_id = None
            identifier_display = target_identifier
            
            if update.message.entities:
                for entity in update.message.entities:
                    if entity.type == "text_mention":
                        # User mentioned without username
                        mentioned_user_id = entity.user.id
                        logger.info(f"📧 Found text mention for user ID: {mentioned_user_id}")
                        break
                    elif entity.type == "mention":
                        # User mentioned with username (@username)
                        start = entity.offset
                        length = entity.length
                        mentioned_username = update.message.text[start:start+length].replace('@', '')
                        logger.info(f"📧 Found username mention: {mentioned_username}")
                        user_data = self.users_collection.find_one({'username': mentioned_username})
                        identifier_display = f"@{mentioned_username}"
                        break
            
            # If we found a mentioned user ID, look them up
            if mentioned_user_id:
                user_data = self.users_collection.find_one({'user_id': mentioned_user_id})
                identifier_display = f"mentioned user"
            
            # If no mention found, check if it's a user ID (all digits) or username
            if not user_data:
                if target_identifier.isdigit():
                    # It's a user ID
                    user_id = int(target_identifier)
                    user_data = self.users_collection.find_one({'user_id': user_id})
                    identifier_display = f"ID:{user_id}"
                else:
                    # It's a username (remove @ if present)
                    username = target_identifier.replace('@', '')
                    user_data = self.users_collection.find_one({'username': username})
                    identifier_display = f"@{username}"
            
            if not user_data:
                await self.send_group_response(update, context, f"❌ User {identifier_display} not found in database!")
                return
            
            old_balance = user_data.get('balance', 0)
            new_balance = old_balance - amount
            
            # Update balance (can go negative)
            self.users_collection.update_one(
                {'user_id': user_data['user_id']},
                {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
            )
            
            # Record transaction
            transaction_data = {
                'user_id': user_data['user_id'],
                'type': 'admin_withdraw',
                'amount': amount,
                'description': f'Withdrawal by admin {update.effective_user.first_name}',
                'timestamp': datetime.now(),
                'admin_id': update.effective_user.id,
                'old_balance': old_balance,
                'new_balance': new_balance
            }
            self.transactions_collection.insert_one(transaction_data)
            
            # Prepare response message
            if new_balance >= 0:
                balance_display = f"₹{new_balance}"
            else:
                balance_display = f"-₹{abs(new_balance)}"
            
            # Get display name (username or first name)
            display_name = user_data.get('username', user_data.get('first_name', 'Unknown User'))
            
            response_msg = f"✅ Withdrew ₹{amount} from {display_name}\n"
            response_msg += f"💰 Balance: ₹{old_balance} → {balance_display}"
            
            if new_balance < 0:
                response_msg += f"\n⚠️ User now has negative balance!"
            
            await self.send_group_response(update, context, response_msg)
            
            # Send notification to user
            try:
                if new_balance >= 0:
                    user_balance_display = f"₹{new_balance}"
                else:
                    user_balance_display = f"-₹{abs(new_balance)} (debt)"
                
                await context.bot.send_message(
                    chat_id=user_data['user_id'],
                    text=f"💸 Withdrawal Notice\n\n"
                         f"₹{amount} has been withdrawn from your account by admin.\n"
                         f"💰 New balance: {user_balance_display}\n\n"
                         f"Admin: {update.effective_user.first_name}"
                )
            except Exception as e:
                logger.warning(f"Could not notify user {user_data['user_id']} about withdrawal: {e}")
            
            # Update balance sheet
            await self.update_balance_sheet(context)
            
        except ValueError:
            await self.send_group_response(update, context, "❌ Invalid amount! Please enter a valid number.")
        except Exception as e:
            logger.error(f"Error in withdraw command: {e}")
            await self.send_group_response(update, context, f"❌ Error processing withdrawal: {str(e)}")
    
    async def active_games_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all active games for admins"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can view active games.")
            return
        
        try:
            active_games = list(self.games_collection.find({'status': 'active'}))
            
            if not active_games:
                await self.send_group_response(update, context, "🎮 No active games currently running.")
                return
            
            games_list = "🎮 Active Games:\n\n"
            for game in active_games:
                players = ", ".join([f"@{player['username']}" for player in game['players']])
                total_pot = sum(player['bet_amount'] for player in game['players'])
                time_left = game['expires_at'] - datetime.now()
                minutes_left = max(0, int(time_left.total_seconds() / 60))
                
                games_list += f"🎲 Game ID: {game['game_id']}\n"
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
    
    async def handle_all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all text messages and route them appropriately"""
        if not update.message or not update.message.text:
            return
        
        # In group chat, only process messages from admins
        if self.is_configured_group(update.effective_chat.id):
            if update.effective_user.id not in self.admin_ids:
                return  # Ignore non-admin messages in group
        
        # Process payment messages
        await self.process_payment_message(update, context)
        
        # Process game tables (new functionality)
        await self.detect_and_process_game_table(update, context)
    
    async def handle_edited_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle edited messages (mainly for game results)"""
        logger.info(f"🔄 EDIT HANDLER CALLED - Update type: {type(update)}")
        logger.info(f"🔄 Update object keys: {update.__dict__.keys()}")
        logger.info(f"🔄 Has edited_message: {hasattr(update, 'edited_message')}")
        
        if not update.edited_message:
            logger.info("❌ No edited_message in update")
            return
        
        if not update.edited_message.text:
            logger.info("❌ No text in edited_message")
            return
        
        logger.info(f"✅ Edited message received from user {update.effective_user.id}")
        logger.info(f"📝 Message text: '{update.edited_message.text}'")
        logger.info(f"🏠 Chat ID: {update.effective_chat.id}")
        logger.info(f"🔑 Is configured group: {self.is_configured_group(update.effective_chat.id)}")
        logger.info(f"👑 Is admin: {update.effective_user.id in self.admin_ids}")
        
        # In group chat, only process edited messages from admins
        if self.is_configured_group(update.effective_chat.id):
            if update.effective_user.id not in self.admin_ids:
                logger.info("❌ Edited message ignored - not from admin")
                return  # Ignore non-admin edited messages in group
        
        logger.info("🎯 Processing edited message for game results...")
        # Only process game results for edited messages
        await self.process_game_result(update, context, is_edit=True)
    
    async def generate_balance_sheet_content(self) -> str:
        """Generate the balance sheet content with all users and their balances"""
        try:
            # Get all users and sort alphabetically by name
            users = list(self.users_collection.find({}, {
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
            from datetime import datetime
            content += f"\n🕐 Last Updated: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
            
            return content
            
        except Exception as e:
            logger.error(f"Error generating balance sheet: {e}")
            return "#BALANCESHEET - Error generating balance sheet"
    
    async def update_balance_sheet(self, context: ContextTypes.DEFAULT_TYPE):
        """Update the pinned balance sheet message"""
        try:
            content = await self.generate_balance_sheet_content()
            
            if self.pinned_balance_msg_id:
                # Try to update existing pinned message
                try:
                    await context.bot.edit_message_text(
                        chat_id=int(self.group_id),
                        message_id=self.pinned_balance_msg_id,
                        text=content,
                        disable_web_page_preview=True
                    )
                    logger.info("✅ Balance sheet updated successfully")
                    return
                except Exception as e:
                    logger.warning(f"Could not update existing balance sheet: {e}")
                    # If update fails, create new one
                    self.pinned_balance_msg_id = None
            
            # Create new pinned balance sheet
            await self.create_new_balance_sheet(context, content)
            
        except Exception as e:
            logger.error(f"Error updating balance sheet: {e}")
    
    async def create_new_balance_sheet(self, context: ContextTypes.DEFAULT_TYPE, content: str = None):
        """Create a new balance sheet and pin it"""
        try:
            if not content:
                content = await self.generate_balance_sheet_content()
            
            logger.info(f"📝 Creating balance sheet with content length: {len(content)}")
            
            # Send the balance sheet message without parsing to avoid entity errors
            message = await context.bot.send_message(
                chat_id=int(self.group_id),
                text=content,
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ Balance sheet message sent with ID: {message.message_id}")
            
            # Pin the message
            try:
                await context.bot.pin_chat_message(
                    chat_id=int(self.group_id),
                    message_id=message.message_id,
                    disable_notification=True
                )
                logger.info("📌 Balance sheet pinned successfully")
                
                # Store the message ID
                self.pinned_balance_msg_id = message.message_id
                self.balance_sheet_collection.update_one(
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
                self.balance_sheet_collection.update_one(
                    {'type': 'pinned_balance_sheet'},
                    {'$set': {'message_id': message.message_id, 'updated_at': datetime.now()}},
                    upsert=True
                )
            
            logger.info(f"✅ New balance sheet created with ID: {message.message_id}")
            
        except Exception as e:
            logger.error(f"❌ Error creating balance sheet: {e}")
            logger.error(f"🔍 Group ID: {self.group_id}")
            logger.error(f"🤖 Bot token exists: {bool(self.bot_token)}")
            raise e
    
    async def balance_sheet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balancesheet command to create or update balance sheet"""
        # Only admins can use this command
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can use this command.")
            return
        
        # Only works in group
        if not self.is_configured_group(update.effective_chat.id):
            await update.message.reply_text("❌ This command only works in the configured group.")
            return
        
        try:
            logger.info(f"💬 Balance sheet command received from user {update.effective_user.id}")
            logger.info(f"🏠 In group: {update.effective_chat.id}")
            logger.info(f"🔑 Group configured: {self.group_id}")
            
            # Check bot permissions first
            try:
                bot_member = await context.bot.get_chat_member(
                    chat_id=int(self.group_id),
                    user_id=context.bot.id
                )
                logger.info(f"🤖 Bot status in group: {bot_member.status}")
                logger.info(f"📌 Bot can pin messages: {getattr(bot_member, 'can_pin_messages', False)}")
            except Exception as perm_error:
                logger.warning(f"Could not check bot permissions: {perm_error}")
            
            # Check if balance sheet already exists and update it
            if self.pinned_balance_msg_id:
                logger.info(f"📌 Updating existing balance sheet: {self.pinned_balance_msg_id}")
                await self.update_balance_sheet(context)
                await self.send_group_response(update, context, "✅ Balance sheet updated!")
            else:
                logger.info("📌 Creating new balance sheet")
                await self.create_new_balance_sheet(context)
                await self.send_group_response(update, context, "✅ Balance sheet created and pinned!")
        except Exception as e:
            logger.error(f"❌ Error in balance sheet command: {e}")
            import traceback
            logger.error(f"🔍 Full traceback: {traceback.format_exc()}")
            await self.send_group_response(update, context, f"❌ Error creating balance sheet: {str(e)}")
    
    async def periodic_balance_sheet_update(self, context: ContextTypes.DEFAULT_TYPE):
        """Periodic update of balance sheet every 5 minutes"""
        try:
            if self.pinned_balance_msg_id:
                logger.info("🔄 Running periodic balance sheet update...")
                await self.update_balance_sheet(context)
                logger.info("✅ Periodic balance sheet update completed")
            else:
                logger.info("📌 No pinned balance sheet found for periodic update")
        except Exception as e:
            logger.error(f"Error in periodic balance sheet update: {e}")
    
    async def handle_winner_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle winner selection from inline keyboard buttons and edit admin's table"""
        query = update.callback_query
        await query.answer()  # Acknowledge the button click
        
        logger.info(f"🎯 Winner selection callback received: {query.data}")
        logger.info(f"👤 From user: {query.from_user.id}")
        logger.info(f"👑 Is admin: {query.from_user.id in self.admin_ids}")
        
        # Only admins can select winners  
        if query.from_user.id not in self.admin_ids:
            await query.answer("❌ Only admins can declare winners!")
            return
        
        # Parse callback data: "winner_{game_id}_{username}"
        try:
            parts = query.data.split('_')
            logger.info(f"🔍 Callback data parts: {parts}")
            
            if len(parts) < 3 or parts[0] != 'winner':
                raise ValueError("Invalid callback format")
            
            # game_id is parts[1], username is parts[2] (and beyond if username has underscores)
            game_id = parts[1]  # "game_97"
            winner_username = "_".join(parts[2:])  # "CR_000" (handles usernames with underscores)
            
            logger.info(f"🎮 Processing winner selection for game: {game_id}, winner: {winner_username}")
        except (ValueError, IndexError) as e:
            logger.error(f"❌ Invalid callback data format: {query.data}, error: {e}")
            return
        
        # Find the active game
        logger.info(f"🔍 Looking for game with ID: {game_id}")
        logger.info(f"🔍 Searching in database with query: {{'game_id': '{game_id}', 'status': 'active'}}")
        
        # Also check active_games dict
        if game_id in self.active_games:
            logger.info(f"🔍 Game found in active_games: {self.active_games[game_id]}")
        else:
            logger.info(f"🔍 Game NOT found in active_games")
        
        game_data = self.games_collection.find_one({'game_id': game_id, 'status': 'active'})
        
        if not game_data:
            logger.error(f"❌ Game {game_id} not found or already completed")
            # Let's also check what games exist in the database
            all_games = list(self.games_collection.find({'status': 'active'}))
            logger.info(f"🔍 All active games in database: {[g.get('game_id') for g in all_games]}")
            return
        
        logger.info(f"🔍 Found game data: {game_data}")
        logger.info(f"🔍 Game data keys: {list(game_data.keys())}")
        logger.info(f"🔍 Admin message ID: {game_data.get('admin_message_id')}")
        logger.info(f"🔍 Chat ID: {game_data.get('chat_id')}")
        
        # Find the winner in the game's players
        winner_player = None
        for player in game_data['players']:
            if player['username'].lower() == winner_username.lower():
                winner_player = player
                break
        
        if not winner_player:
            logger.error(f"❌ Player @{winner_username} not found in game {game_id}")
            return
        
        logger.info(f"🏆 Declaring winner: {winner_username} for game {game_id}")
        logger.info(f"🏆 Winner player data: {winner_player}")
        
        # Try to edit the admin's original table message first
        logger.info("🔧 About to call edit_admin_table_with_winner...")
        edit_success = await self.edit_admin_table_with_winner(game_data, winner_username, context)
        logger.info(f"🔧 edit_admin_table_with_winner completed with success: {edit_success}")
        
        # If Pyrogram editing failed, try manual detection as fallback
        if not edit_success:
            logger.info("🔄 Pyrogram editing failed, trying manual detection fallback...")
            # Try to manually detect the winner from the edited table
            await self.manual_winner_detection_fallback(game_data, winner_username, context)
            
            # Also send a message to the admin explaining they need to manually edit the table
            try:
                manual_edit_msg = (
                    f"🔄 Pyrogram editing failed!\n\n"
                    f"📝 **Please manually edit your table message in the group:**\n"
                    f"• Add ✅ after the winner's username\n"
                    f"• Example: @{winner_username} ✅\n\n"
                    f"🎮 The bot will automatically detect the edit and process the game result!"
                )
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=manual_edit_msg
                )
                logger.info("✅ Sent manual edit instructions to admin")
            except Exception as e:
                logger.error(f"❌ Could not send manual edit instructions: {e}")
        
        # Process the game result (this will handle balance updates, notifications, etc.)
        await self.process_game_result_from_winner(game_data, [winner_player], context)
        
        # Send confirmation ONLY to admin's DM (not in group)
        try:
            confirmation_msg = f"✅ Winner declared: @{winner_username}\n\n📝 Your table has been updated with ✅ mark.\n🎮 Game results processed successfully!"
            await context.bot.send_message(
                chat_id=query.from_user.id,  # Send to admin's DM
                text=confirmation_msg
            )
        except Exception as e:
            logger.error(f"❌ Could not send confirmation to admin DM: {e}")
    
    async def edit_admin_table_with_winner(self, game_data: dict, winner_username: str, context: ContextTypes.DEFAULT_TYPE):
        """Edit the admin's original table message to add ✅ after the winner's username"""
        try:
            if not self.pyro_client:
                logger.warning("⚠️ Pyrogram client not available - cannot edit admin table")
                return
            
            # Check if Pyrogram client is running
            logger.info(f"🔍 Pyrogram client status: {self.pyro_client.is_connected}")
            if not self.pyro_client.is_connected:
                logger.warning("⚠️ Pyrogram client not connected - trying to start it")
                try:
                    await self.pyro_client.start()
                    logger.info("✅ Pyrogram client started successfully")
                    # Wait a moment for connection to stabilize
                    import asyncio
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"❌ Failed to start Pyrogram client: {e}")
                    return
            
            # Get the admin's original table message
            admin_message_id = game_data.get('admin_message_id')
            chat_id = game_data.get('chat_id')
            
            logger.info(f"🔍 Game data keys: {list(game_data.keys())}")
            logger.info(f"🔍 Admin message ID: {admin_message_id}")
            logger.info(f"🔍 Chat ID: {chat_id} (type: {type(chat_id)})")
            logger.info(f"🔍 Game ID: {game_data.get('game_id')}")
            
            # Convert chat_id to int if it's a string
            if isinstance(chat_id, str):
                try:
                    chat_id = int(chat_id)
                    logger.info(f"🔍 Converted chat_id to int: {chat_id}")
                except ValueError:
                    logger.error(f"❌ Could not convert chat_id '{chat_id}' to int")
                    return
            
            if not admin_message_id or not chat_id:
                logger.error("❌ Missing admin message ID or chat ID")
                logger.error(f"❌ admin_message_id: {admin_message_id}, chat_id: {chat_id}")
                return
            
            logger.info("🔧 Editing admin's table message with winner...")
            
            # Build the edited table with ✅ after winner
            edited_lines = []
            for player in game_data['players']:
                if player['username'].lower() == winner_username.lower():
                    edited_lines.append(f"@{player['username']} ✅")
                else:
                    edited_lines.append(f"@{player['username']}")
            
            # Add the bet amount and Full keyword
            edited_lines.append(f"\n{game_data['bet_amount']} Full")
            
            edited_text = "\n\n".join(edited_lines)
            
            logger.info(f"🔍 Edited text to send: '{edited_text}'")
            logger.info(f"🔍 Chat ID: {chat_id}, Message ID: {admin_message_id}")
            
            # Use pyrogram to edit the admin's message
            try:
                logger.info(f"🔧 Attempting to edit message with Pyrogram...")
                logger.info(f"🔧 Pyrogram client info: {self.pyro_client}")
                logger.info(f"🔧 Chat ID type: {type(chat_id)}, Message ID type: {type(admin_message_id)}")
                logger.info(f"🔧 Text length: {len(edited_text)}")
                
                # Test if we can access the message first
                try:
                    test_message = await self.pyro_client.get_messages(chat_id, admin_message_id)
                    logger.info(f"🔧 Test message access successful: {test_message.text[:50] if test_message.text else 'No text'}...")
                except Exception as test_e:
                    logger.error(f"❌ Cannot access message with Pyrogram: {test_e}")
                    return False
                
                await self.pyro_client.edit_message_text(
                    chat_id=chat_id,
                    message_id=admin_message_id,
                    text=edited_text
                )
                logger.info(f"✅ Successfully edited admin's table for game {game_data['game_id']}")
                return True
            except Exception as pyro_error:
                logger.error(f"❌ Pyrogram edit failed: {pyro_error}")
                # Try to get more details about the error
                if "CHAT_NOT_FOUND" in str(pyro_error):
                    logger.error("❌ Chat not found - check if chat_id is correct")
                elif "MESSAGE_NOT_FOUND" in str(pyro_error):
                    logger.error("❌ Message not found - check if message_id is correct")
                elif "FORBIDDEN" in str(pyro_error):
                    logger.error("❌ Forbidden - check if Pyrogram session has permission to edit this message")
                return False
            
            # NO GROUP MESSAGES - only edit the admin's table silently
            
        except Exception as e:
            logger.error(f"❌ Error editing admin table: {e}")
            # Even on error, don't send messages in the group - just log the error
            return False
    
    async def manual_winner_detection_fallback(self, game_data: dict, winner_username: str, context: ContextTypes.DEFAULT_TYPE):
        """Fallback method to manually detect winners when Pyrogram editing fails"""
        try:
            logger.info("🔄 Manual winner detection fallback activated...")
            
            # Get the current message from the group to see if it was edited
            try:
                # Try to get the current message content from the group
                chat_id = game_data.get('chat_id')
                admin_message_id = game_data.get('admin_message_id')
                
                if not chat_id or not admin_message_id:
                    logger.error("❌ Missing chat_id or admin_message_id for manual detection")
                    return
                
                # Convert chat_id to int if needed
                if isinstance(chat_id, str):
                    chat_id = int(chat_id)
                
                # Get the current message from the group
                current_message = await context.bot.get_chat(chat_id)
                if current_message:
                    logger.info(f"🔍 Current chat info: {current_message.title if hasattr(current_message, 'title') else 'Unknown'}")
                
                # Try to get the specific message
                try:
                    message = await context.bot.get_chat_history(chat_id, limit=100)
                    # Look for the specific message
                    target_message = None
                    for msg in message:
                        if msg.message_id == admin_message_id:
                            target_message = msg
                            break
                    
                    if target_message:
                        logger.info(f"🔍 Found target message: {target_message.text[:100]}...")
                        # Check if it contains the winner
                        if f"@{winner_username} ✅" in target_message.text:
                            logger.info("✅ Winner detected in edited message!")
                            return True
                        else:
                            logger.info("❌ Winner not found in edited message")
                    else:
                        logger.info("❌ Target message not found in chat history")
                        
                except Exception as e:
                    logger.error(f"❌ Error getting message history: {e}")
                
            except Exception as e:
                logger.error(f"❌ Error in manual detection: {e}")
            
            # If we can't detect the winner automatically, just log it
            logger.info(f"🔄 Manual detection completed for winner: {winner_username}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error in manual winner detection fallback: {e}")
            return False
    
    async def check_manual_table_edit(self, message_text: str, message_id: int, chat_id: int) -> tuple:
        """Check if a manually edited message contains a game table with winners"""
        try:
            logger.info("🔍 Checking manually edited message for game table with winners...")
            logger.info(f"🔍 Message ID: {message_id}, Chat ID: {chat_id}")
            logger.info(f"🔍 Message preview: {message_text[:200]}...")
            
            # First, check if this message contains the "Full" keyword (indicating it's a game table)
            if not re.search(r'\b(?:Full|full)\b', message_text):
                logger.info("❌ Message doesn't contain 'Full' keyword - not a game table")
                return None, []
            
            # Check if it contains ✅ marks (indicating winners) - try multiple patterns
            winner_patterns = [
                r'@([a-zA-Z0-9_]+)\s*✅',  # Username + space + checkmark
                r'@([a-zA-Z0-9_]+)✅',     # Username + checkmark (no space)
                r'@([a-zA-Z0-9_]+).*?✅', # Username + anything + checkmark
                r'✅.*?@([a-zA-Z0-9_]+)', # Checkmark + anything + username
            ]
            
            winner_matches = []
            for pattern in winner_patterns:
                matches = re.findall(pattern, message_text, re.IGNORECASE)
                if matches:
                    winner_matches.extend(matches)
                    logger.info(f"✅ Pattern '{pattern}' found winners: {matches}")
            
            # Remove duplicates while preserving order
            winner_matches = list(dict.fromkeys(winner_matches))
            
            if not winner_matches:
                logger.info("❌ No winners found in edited message")
                return None, []
            
            logger.info(f"✅ Found winners in manually edited message: {winner_matches}")
            
            # Try to find the corresponding game
            # First check by message ID
            game_data = self.games_collection.find_one({
                'admin_message_id': message_id,
                'status': 'active'
            })
            
            if not game_data:
                logger.info("🔍 Game not found by message ID, checking by player overlap...")
                # If not found by message ID, check all active games
                active_games = list(self.games_collection.find({'status': 'active'}))
                logger.info(f"🔍 Checking {len(active_games)} active games for manually edited table")
                
                for game in active_games:
                    logger.info(f"🔍 Checking game: {game.get('game_id')}")
                    # Check if this game's players match the usernames in the message
                    message_usernames = re.findall(r'@([a-zA-Z0-9_]+)', message_text)
                    game_usernames = [p['username'] for p in game['players']]
                    
                    logger.info(f"🔍 Message usernames: {message_usernames}")
                    logger.info(f"🔍 Game usernames: {game_usernames}")
                    
                    # Check if there's a significant overlap
                    overlap = set(message_usernames) & set(game_usernames)
                    logger.info(f"🔍 Overlap: {overlap}")
                    
                    if len(overlap) >= 2:  # At least 2 players match
                        game_data = game
                        logger.info(f"✅ Found matching game by player overlap: {game['game_id']}")
                        break
            
            if game_data:
                # Find the actual winner players from the game data
                winners = []
                for winner_name in winner_matches:
                    for player in game_data['players']:
                        if player['username'].lower() == winner_name.lower():
                            winners.append(player)
                            logger.info(f"✅ Matched winner: {winner_name} -> {player['username']}")
                            break
                
                logger.info(f"✅ Found {len(winners)} winners for game {game_data['game_id']}")
                return game_data, winners
            
            logger.info("❌ No matching game found for manually edited table")
            return None, []
            
        except Exception as e:
            logger.error(f"❌ Error checking manual table edit: {e}")
            return None, []
    
    async def process_game_result_from_winner(self, game_data: dict, winners: list, context: ContextTypes.DEFAULT_TYPE):
        """Process game results when winner is selected via button"""
        try:
            # Calculate total pot from all players
            total_pot = sum(player['bet_amount'] for player in game_data['players'])
            
            # Distribute winnings among winners
            winnings_per_winner = total_pot // len(winners)
            
            for winner in winners:
                commission_rate = winner['commission_rate']
                commission_amount = (winnings_per_winner * commission_rate) // 100
                final_winnings = winnings_per_winner - commission_amount
                
                # Add winnings to winner's balance
                user_data = self.users_collection.find_one({'user_id': winner['user_id']})
                new_balance = user_data['balance'] + final_winnings
                
                self.users_collection.update_one(
                    {'user_id': winner['user_id']},
                    {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
                )
                
                # Record winning transaction
                transaction_data = {
                    'user_id': winner['user_id'],
                    'type': 'win',
                    'amount': final_winnings,
                    'description': f'Won game {game_data["game_id"]} (Commission: ₹{commission_amount})',
                    'timestamp': datetime.now(),
                    'game_id': game_data['game_id']
                }
                self.transactions_collection.insert_one(transaction_data)
                
                # Notify winner
                try:
                    await context.bot.send_message(
                        chat_id=winner['user_id'],
                        text=f"🎉 You won!\n\n💰 Prize: ₹{final_winnings} (after {commission_rate}% commission)\n📊 New balance: ₹{new_balance}\n\nCongratulations! 🎊"
                    )
                except:
                    pass
            
            # Notify losers
            for player in game_data['players']:
                if player not in winners:
                    try:
                        await context.bot.send_message(
                            chat_id=player['user_id'],
                            text=f"😔 Better luck next time!\n\nYou lost ₹{player['bet_amount']} in this match.\nHope you win the next one! 🎲"
                        )
                    except:
                        pass
            
            # Update game status
            self.games_collection.update_one(
                {'game_id': game_data['game_id']},
                {
                    '$set': {
                        'status': 'completed',
                        'winners': [w['username'] for w in winners],
                        'completed_at': datetime.now()
                    }
                }
            )
            
            # Remove from active games
            if game_data['game_id'] in self.active_games:
                del self.active_games[game_data['game_id']]
            
            # Update balance sheet after game completion
            await self.update_balance_sheet(context)
            
            logger.info(f"✅ Game {game_data['game_id']} completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Error processing game result: {e}")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command with professional analytics interface"""
        if update.effective_user.id not in self.admin_ids:
            await self.send_group_response(update, context, "❌ Only admins can view statistics.")
            return
        
        # Create main stats menu
        keyboard = [
            [InlineKeyboardButton("📅 Today's Stats", callback_data="stats_today")],
            [InlineKeyboardButton("📅 Yesterday's Stats", callback_data="stats_yesterday")],
            [InlineKeyboardButton("📆 This Week", callback_data="stats_this_week")],
            [InlineKeyboardButton("📆 This Month", callback_data="stats_this_month")],
            [InlineKeyboardButton("🗓️ Custom Date Range", callback_data="stats_custom_calendar")],
            [InlineKeyboardButton("📊 All Time Stats", callback_data="stats_all_time")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        stats_msg = """
📊 **PROFESSIONAL ANALYTICS DASHBOARD**
═══════════════════════════════════════

Select a time period to view detailed statistics:

📈 **Available Reports:**
• Commission earnings breakdown
• Total matches played
• Individual match profits
• Player activity analysis
• Revenue trends
• Performance metrics

Choose a time period below:
        """
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=stats_msg,
            reply_markup=reply_markup
        )
    
    async def handle_stats_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle statistics callback queries"""
        query = update.callback_query
        await query.answer()
        
        try:
            if query.data == "stats_today":
                await self.show_period_stats(query, "today")
            elif query.data == "stats_yesterday":
                await self.show_period_stats(query, "yesterday")
            elif query.data == "stats_this_week":
                await self.show_period_stats(query, "this_week")
            elif query.data == "stats_this_month":
                await self.show_period_stats(query, "this_month")
            elif query.data == "stats_all_time":
                await self.show_period_stats(query, "all_time")
            elif query.data == "stats_custom_calendar":
                await self.show_calendar(query)
            elif query.data.startswith("cal_"):
                await self.handle_calendar_callback(query)
            elif query.data.startswith("time_"):
                await self.handle_time_callback(query)
            elif query.data == "stats_back_main":
                await self.show_stats_main_menu(query)
        except Exception as e:
            logger.error(f"Error in stats callback: {e}")
            await query.edit_message_text("❌ Error processing request. Please try again.")
    
    async def show_period_stats(self, query, period):
        """Show statistics for a specific period"""
        # Calculate date ranges
        now = datetime.now()
        
        if period == "today":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now
            title = "📅 TODAY'S STATISTICS"
        elif period == "yesterday":
            yesterday = now - timedelta(days=1)
            start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            title = "📅 YESTERDAY'S STATISTICS"
        elif period == "this_week":
            # Start of current week (Monday)
            days_since_monday = now.weekday()
            start_date = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now
            title = "📆 THIS WEEK'S STATISTICS"
        elif period == "this_month":
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end_date = now
            title = "📆 THIS MONTH'S STATISTICS"
        elif period == "all_time":
            start_date = datetime(2020, 1, 1)  # Far back date
            end_date = now
            title = "📊 ALL TIME STATISTICS"
        
        stats_data = await self.calculate_comprehensive_stats(start_date, end_date)
        formatted_stats = self.format_professional_stats(stats_data, title, start_date, end_date)
        
        # Back button
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="stats_back_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=formatted_stats,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
    
    async def show_calendar(self, query):
        """Show calendar interface for custom date selection"""
        now = datetime.now()
        keyboard = []
        
        # Year and month selection
        keyboard.append([
            InlineKeyboardButton("◀️", callback_data=f"cal_prev_month_{now.year}_{now.month}"),
            InlineKeyboardButton(f"{calendar.month_name[now.month]} {now.year}", callback_data="cal_ignore"),
            InlineKeyboardButton("▶️", callback_data=f"cal_next_month_{now.year}_{now.month}")
        ])
        
        # Day headers
        keyboard.append([InlineKeyboardButton(day, callback_data="cal_ignore") for day in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]])
        
        # Calendar days
        cal = calendar.monthcalendar(now.year, now.month)
        for week in cal:
            week_buttons = []
            for day in week:
                if day == 0:
                    week_buttons.append(InlineKeyboardButton(" ", callback_data="cal_ignore"))
                else:
                    week_buttons.append(InlineKeyboardButton(str(day), callback_data=f"cal_select_{now.year}_{now.month}_{day}"))
            keyboard.append(week_buttons)
        
        # Quick options
        keyboard.append([
            InlineKeyboardButton("📅 Today", callback_data="cal_quick_today"),
            InlineKeyboardButton("📅 Yesterday", callback_data="cal_quick_yesterday")
        ])
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="stats_back_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = """
📅 **CUSTOM DATE SELECTION**
═══════════════════════════

Select a start date for your custom report:

👆 Click on any day to select it
◀️ ▶️ Navigate between months
        """
        
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    
    async def handle_calendar_callback(self, query):
        """Handle calendar navigation and date selection"""
        data_parts = query.data.split("_")
        
        if data_parts[1] == "prev" and data_parts[2] == "month":
            year, month = int(data_parts[3]), int(data_parts[4])
            if month == 1:
                month, year = 12, year - 1
            else:
                month -= 1
            await self.show_month_calendar(query, year, month)
            
        elif data_parts[1] == "next" and data_parts[2] == "month":
            year, month = int(data_parts[3]), int(data_parts[4])
            if month == 12:
                month, year = 1, year + 1
            else:
                month += 1
            await self.show_month_calendar(query, year, month)
            
        elif data_parts[1] == "select":
            year, month, day = int(data_parts[2]), int(data_parts[3]), int(data_parts[4])
            selected_date = datetime(year, month, day)
            await self.show_time_selection(query, selected_date, "start")
            
        elif data_parts[1] == "quick":
            if data_parts[2] == "today":
                await self.show_period_stats(query, "today")
            elif data_parts[2] == "yesterday":
                await self.show_period_stats(query, "yesterday")
    
    async def show_month_calendar(self, query, year, month):
        """Show calendar for a specific month"""
        keyboard = []
        
        # Year and month selection
        keyboard.append([
            InlineKeyboardButton("◀️", callback_data=f"cal_prev_month_{year}_{month}"),
            InlineKeyboardButton(f"{calendar.month_name[month]} {year}", callback_data="cal_ignore"),
            InlineKeyboardButton("▶️", callback_data=f"cal_next_month_{year}_{month}")
        ])
        
        # Day headers
        keyboard.append([InlineKeyboardButton(day, callback_data="cal_ignore") for day in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]])
        
        # Calendar days
        cal = calendar.monthcalendar(year, month)
        for week in cal:
            week_buttons = []
            for day in week:
                if day == 0:
                    week_buttons.append(InlineKeyboardButton(" ", callback_data="cal_ignore"))
                else:
                    week_buttons.append(InlineKeyboardButton(str(day), callback_data=f"cal_select_{year}_{month}_{day}"))
            keyboard.append(week_buttons)
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="stats_back_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = f"""
📅 **CUSTOM DATE SELECTION**
═══════════════════════════

**{calendar.month_name[month]} {year}**

Select a date to view statistics:
        """
        
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    
    async def show_time_selection(self, query, selected_date, time_type):
        """Show time selection interface"""
        keyboard = []
        
        # Time selection buttons
        times = [
            ("🌅 00:00", "00:00"), ("🌅 06:00", "06:00"), ("🌞 12:00", "12:00"), ("🌆 18:00", "18:00"),
            ("🌙 01:00", "01:00"), ("🌅 07:00", "07:00"), ("🌞 13:00", "13:00"), ("🌆 19:00", "19:00"),
            ("🌙 02:00", "02:00"), ("🌅 08:00", "08:00"), ("🌞 14:00", "14:00"), ("🌆 20:00", "20:00"),
            ("🌙 03:00", "03:00"), ("🌅 09:00", "09:00"), ("🌞 15:00", "15:00"), ("🌆 21:00", "21:00"),
            ("🌙 04:00", "04:00"), ("🌅 10:00", "10:00"), ("🌞 16:00", "16:00"), ("🌆 22:00", "22:00"),
            ("🌙 05:00", "05:00"), ("🌅 11:00", "11:00"), ("🌞 17:00", "17:00"), ("🌙 23:00", "23:00")
        ]
        
        # Create 4x6 grid
        for i in range(0, len(times), 4):
            row = []
            for j in range(4):
                if i + j < len(times):
                    display, time_str = times[i + j]
                    row.append(InlineKeyboardButton(
                        display, 
                        callback_data=f"time_select_{selected_date.strftime('%Y_%m_%d')}_{time_str}_{time_type}"
                    ))
            if row:
                keyboard.append(row)
        
        # Quick options
        keyboard.append([
            InlineKeyboardButton("🌅 Start of Day (00:00)", callback_data=f"time_select_{selected_date.strftime('%Y_%m_%d')}_00:00_{time_type}"),
            InlineKeyboardButton("🌙 End of Day (23:59)", callback_data=f"time_select_{selected_date.strftime('%Y_%m_%d')}_23:59_{time_type}")
        ])
        
        keyboard.append([InlineKeyboardButton("🔙 Back to Calendar", callback_data="stats_custom_calendar")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = f"""
🕐 **TIME SELECTION**
═══════════════════════════

**Selected Date:** {selected_date.strftime('%B %d, %Y')}
**Selecting:** {time_type.title()} time

Choose the {time_type} time for your report:
        """
        
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    
    async def handle_time_callback(self, query):
        """Handle time selection callbacks"""
        # For now, just show today's stats as an example
        # In a full implementation, you would store the selected date/time and ask for end date
        await self.show_period_stats(query, "today")
    
    async def show_stats_main_menu(self, query):
        """Show the main stats menu"""
        keyboard = [
            [InlineKeyboardButton("📅 Today's Stats", callback_data="stats_today")],
            [InlineKeyboardButton("📅 Yesterday's Stats", callback_data="stats_yesterday")],
            [InlineKeyboardButton("📆 This Week", callback_data="stats_this_week")],
            [InlineKeyboardButton("📆 This Month", callback_data="stats_this_month")],
            [InlineKeyboardButton("🗓️ Custom Date Range", callback_data="stats_custom_calendar")],
            [InlineKeyboardButton("📊 All Time Stats", callback_data="stats_all_time")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        stats_msg = """
📊 **PROFESSIONAL ANALYTICS DASHBOARD**
═══════════════════════════════════════

Select a time period to view detailed statistics:

📈 **Available Reports:**
• Commission earnings breakdown
• Total matches played
• Individual match profits
• Player activity analysis
• Revenue trends
• Performance metrics

Choose a time period below:
        """
        
        await query.edit_message_text(text=stats_msg, reply_markup=reply_markup)
    
    async def calculate_comprehensive_stats(self, start_date, end_date):
        """Calculate comprehensive statistics for the given date range"""
        try:
            # Get all completed games in the date range
            completed_games = list(self.games_collection.find({
                'status': 'completed',
                'completed_at': {
                    '$gte': start_date,
                    '$lte': end_date
                }
            }))
            
            # Get all transactions in the date range
            transactions = list(self.transactions_collection.find({
                'timestamp': {
                    '$gte': start_date,
                    '$lte': end_date
                }
            }))
            
            # Calculate statistics
            stats = {
                'total_games': len(completed_games),
                'total_commission': 0,
                'total_pot_value': 0,
                'total_bets': 0,
                'games_per_hour': {},
                'top_players': defaultdict(int),
                'commission_per_game': [],
                'hourly_earnings': defaultdict(float),
                'daily_earnings': defaultdict(float),
                'game_details': []
            }
            
            # Process each completed game
            for game in completed_games:
                game_pot = sum(player['bet_amount'] for player in game.get('players', []))
                stats['total_pot_value'] += game_pot
                stats['total_bets'] += len(game.get('players', []))
                
                # Calculate commission for this game
                game_commission = 0
                for player in game.get('players', []):
                    if player['username'] in game.get('winners', []):
                        commission_rate = player.get('commission_rate', 5)
                        player_winnings = game_pot  # Simplified - in real scenario, divide by winners
                        commission = (player_winnings * commission_rate) / 100
                        game_commission += commission
                        
                        # Track top players
                        stats['top_players'][player['username']] += 1
                
                stats['total_commission'] += game_commission
                stats['commission_per_game'].append(game_commission)
                
                # Hourly and daily breakdown
                if 'completed_at' in game:
                    completed_time = game['completed_at']
                    hour_key = completed_time.strftime('%H:00')
                    day_key = completed_time.strftime('%Y-%m-%d')
                    
                    stats['hourly_earnings'][hour_key] += game_commission
                    stats['daily_earnings'][day_key] += game_commission
                    stats['games_per_hour'][hour_key] = stats['games_per_hour'].get(hour_key, 0) + 1
                
                # Game details for breakdown
                stats['game_details'].append({
                    'game_id': game.get('game_id', 'Unknown'),
                    'pot_value': game_pot,
                    'commission': game_commission,
                    'players': len(game.get('players', [])),
                    'winners': game.get('winners', []),
                    'completed_at': game.get('completed_at')
                })
            
            # Process transactions for additional insights
            payment_transactions = [t for t in transactions if t.get('type') == 'payment_confirmation']
            manual_adds = [t for t in transactions if t.get('type') == 'manual_add']
            withdrawals = [t for t in transactions if t.get('type') == 'admin_withdraw']
            
            stats['total_payments'] = sum(t.get('amount', 0) for t in payment_transactions)
            stats['total_manual_adds'] = sum(t.get('amount', 0) for t in manual_adds)
            stats['total_withdrawals'] = sum(t.get('amount', 0) for t in withdrawals)
            stats['payment_count'] = len(payment_transactions)
            stats['manual_add_count'] = len(manual_adds)
            stats['withdrawal_count'] = len(withdrawals)
            
            return stats
            
        except Exception as e:
            logger.error(f"Error calculating stats: {e}")
            return {}
    
    def format_professional_stats(self, stats, title, start_date, end_date):
        """Format statistics in a professional manner"""
        if not stats:
            return "❌ Error calculating statistics. Please try again."
        
        # Date range formatting
        if start_date.date() == end_date.date():
            date_range = start_date.strftime('%B %d, %Y')
        else:
            date_range = f"{start_date.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')}"
        
        # Format statistics
        report = f"""
{title}
{'═' * len(title)}

📅 **Period:** {date_range}
🕐 **Generated:** {datetime.now().strftime('%B %d, %Y at %I:%M %p')}

💰 **FINANCIAL OVERVIEW**
┌─────────────────────────────────┐
│ Total Commission Earned: ₹{stats.get('total_commission', 0):.2f}
│ Total Games Played: {stats.get('total_games', 0)}
│ Total Pot Value: ₹{stats.get('total_pot_value', 0):.2f}
│ Average Commission/Game: ₹{(stats.get('total_commission', 0) / max(stats.get('total_games', 1), 1)):.2f}
└─────────────────────────────────┘

🎮 **GAME ANALYTICS**
┌─────────────────────────────────┐
│ Total Bets Placed: {stats.get('total_bets', 0)}
│ Average Players/Game: {(stats.get('total_bets', 0) / max(stats.get('total_games', 1), 1)):.1f}
│ Games Completed: {stats.get('total_games', 0)}
└─────────────────────────────────┘

💳 **TRANSACTION SUMMARY**
┌─────────────────────────────────┐
│ Total Payments: ₹{stats.get('total_payments', 0):.2f} ({stats.get('payment_count', 0)} txns)
│ Manual Additions: ₹{stats.get('total_manual_adds', 0):.2f} ({stats.get('manual_add_count', 0)} txns)
│ Withdrawals: ₹{stats.get('total_withdrawals', 0):.2f} ({stats.get('withdrawal_count', 0)} txns)
└─────────────────────────────────┘
"""
        
        # Top players section
        if stats.get('top_players'):
            report += "\n🏆 **TOP ACTIVE PLAYERS**\n"
            sorted_players = sorted(stats['top_players'].items(), key=lambda x: x[1], reverse=True)[:5]
            for i, (player, games) in enumerate(sorted_players, 1):
                report += f"│ {i}. @{player} - {games} games\n"
        
        # Hourly breakdown if available
        if stats.get('hourly_earnings'):
            report += "\n⏰ **HOURLY EARNINGS BREAKDOWN**\n"
            sorted_hours = sorted(stats['hourly_earnings'].items())
            for hour, earnings in sorted_hours[:8]:  # Show top 8 hours
                games_count = stats.get('games_per_hour', {}).get(hour, 0)
                if earnings > 0:
                    report += f"│ {hour} - ₹{earnings:.2f} ({games_count} games)\n"
        
        # Recent game details
        if stats.get('game_details'):
            report += "\n🎯 **RECENT GAME BREAKDOWN**\n"
            recent_games = sorted(stats['game_details'], key=lambda x: x.get('completed_at', datetime.min), reverse=True)[:5]
            for game in recent_games:
                completed_time = game.get('completed_at', datetime.now())
                winners_str = ", ".join([f"@{w}" for w in game.get('winners', [])])
                report += f"│ {game.get('game_id', 'Unknown')} - ₹{game.get('commission', 0):.2f} commission\n"
                report += f"│   Winner(s): {winners_str}\n"
                report += f"│   Completed: {completed_time.strftime('%m/%d %I:%M %p')}\n"
                report += "│\n"
        
        report += f"\n📊 **Performance Rating:** {'🔥 Excellent' if stats.get('total_commission', 0) > 1000 else '📈 Growing' if stats.get('total_commission', 0) > 500 else '🌱 Building'}"
        
        return report
    
    def run(self):
        """Start the bot"""
        # Validate configuration
        if not self.bot_token:
            print("❌ BOT_TOKEN not found in environment variables!")
            print("Please create a .env file with your bot token or run setup_env.py")
            return
        
        if not self.group_id:
            print("❌ GROUP_ID not found in environment variables!")
            print("Please add your group chat ID to the .env file or run setup_env.py")
            return
        
        if not self.admin_ids:
            print("❌ ADMIN_IDS not found in environment variables!")
            print("Please add admin user IDs to the .env file or run setup_env.py")
            return
        
        try:
            # Create application
            application = Application.builder().token(self.bot_token).build()
            
            # Add handlers
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("balance", self.balance_command))
            application.add_handler(CommandHandler("help", self.help_command))
            application.add_handler(CommandHandler("game", self.game_command))
            application.add_handler(CommandHandler("activegames", self.active_games_command))
            application.add_handler(CommandHandler("expiregames", self.expire_games_command))
            application.add_handler(CommandHandler("cancel", self.cancel_command))
            application.add_handler(CommandHandler("setcommission", self.set_commission_command))
            application.add_handler(CommandHandler("addbalance", self.add_balance_command))
            application.add_handler(CommandHandler("withdraw", self.withdraw_command))
            application.add_handler(CommandHandler("balancesheet", self.balance_sheet_command))
            application.add_handler(CommandHandler("stats", self.stats_command))
            
            # Callback query handler for inline keyboard buttons (keeping for stats)
            application.add_handler(CallbackQueryHandler(self.handle_stats_callback, pattern=r"^(stats_|cal_|time_)"))
            logger.info("✅ Callback query handlers added")
            
            # Callback query handler for winner selection (from admin DM)
            application.add_handler(CallbackQueryHandler(self.handle_winner_selection, pattern=r"^winner_"))
            logger.info("✅ Winner selection handler added for admin DM")
            
            # Message handler for all text messages
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_all_messages))
            
            # Handler for edited messages (to detect game results when message is edited)
            # Using a custom handler for edited messages
            async def edited_message_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if update.edited_message:
                    await self.handle_edited_messages(update, context)
            
            # Add handler for all updates to catch edited messages
            from telegram.ext import TypeHandler
            application.add_handler(TypeHandler(Update, edited_message_wrapper))
            logger.info("✅ Edited message handler added")
            
            # Set up job queue for periodic tasks (if available)
            job_queue = application.job_queue
            
            if job_queue:
                # Schedule game expiration check every 5 minutes
                job_queue.run_repeating(
                    callback=self.expire_old_games,
                    interval=300,  # 5 minutes
                    first=60,      # Start after 1 minute
                    name="expire_games"
                )
                print("✅ Game expiration monitor started (checks every 5 minutes)")
                
                # Schedule balance sheet update every 5 minutes
                job_queue.run_repeating(
                    callback=self.periodic_balance_sheet_update,
                    interval=300,  # 5 minutes
                    first=120,     # Start after 2 minutes
                    name="balance_sheet_update"
                )
                print("✅ Balance sheet auto-update started (updates every 5 minutes)")
            else:
                print("⚠️  JobQueue not available. Game expiration and balance sheet monitoring disabled.")
                print("   Install with: pip install python-telegram-bot[job-queue]")
            
            print("🤖 Ludo Bot Manager is starting...")
            print(f"✅ Bot Token: {self.bot_token[:10]}...")
            print(f"✅ Group ID: {self.group_id}")
            print(f"✅ Admin IDs: {len(self.admin_ids)} admins configured")
            
            # Start Pyrogram client if available
            if self.pyro_client:
                print("🚀 Pyrogram client will be started when bot begins polling...")
                print("✅ Pyrogram handlers configured and ready")
            
            print("Bot is running! Press Ctrl+C to stop.")
            
            # Start the bot with explicit update types
            logger.info("🚀 Starting bot with polling...")
            logger.info("📋 Allowed updates: message, edited_message, callback_query")
            application.run_polling(
                allowed_updates=["message", "edited_message", "callback_query"],
                drop_pending_updates=True
            )
            
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            print(f"❌ Failed to start bot: {e}")

if __name__ == "__main__":
    bot_manager = LudoBotManager()
    bot_manager.run()
