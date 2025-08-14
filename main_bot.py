#!/usr/bin/env python3
"""
Main Bot File for Ludo Bot Manager
Uses organized feature modules for better maintainability
"""

import os
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# Import feature modules
from features import (
    DatabaseManager,
    PyrogramManager,
    register_pyro_table_tracker,
    UserManager,
    BalanceSheetManager
)

# Import Telegram bot components
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, TypeHandler
)

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
        """Initialize the bot with all feature managers"""
        # Load configuration
        self.bot_token = os.getenv('BOT_TOKEN')
        self.mongo_uri = os.getenv('MONGO_URI')
        self.group_id = os.getenv('GROUP_ID')
        self.admin_ids = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]
        
        # Pyrogram configuration
        self.api_id = os.getenv('API_ID')
        self.api_hash = os.getenv('API_HASH')
        
        # Validate required configuration
        if not all([self.bot_token, self.mongo_uri, self.group_id, self.admin_ids]):
            raise ValueError("Missing required environment variables")
        
        # Initialize database manager
        self.database = DatabaseManager(self.mongo_uri)
        
        # Initialize feature managers
        self.user_manager = UserManager(self.database, self)
        # GameManager removed in favor of Pyrogram table tracker
        self.balance_sheet_manager = BalanceSheetManager(self.database, self)
        
        # Initialize Pyrogram manager if credentials are available
        self.pyro_manager = None
        if self.api_id and self.api_hash:
            self.pyro_manager = PyrogramManager(
                self.api_id, 
                self.api_hash, 
                self.group_id, 
                self.admin_ids
            )
            # Set dependencies
            self.pyro_manager.set_dependencies(self.database, self)
            # Also register the minimal tracker directly on the low-level app if available
        
        # Bot application
        self.application = None
        
        logger.info("✅ LudoBotManager initialized successfully")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        user_id = user.id
        username = user.username or "Unknown"
        first_name = user.first_name or "Unknown"
        last_name = user.last_name
        
        # Get or create user
        user_data = self.user_manager.get_or_create_user(user_id, username, first_name, last_name)
        
        if user_data:
            balance = user_data.get('balance', 0)
            welcome_message = (
                f"🎉 **Welcome to Ludo Bot Manager!**\n\n"
                f"👤 **User:** @{username}\n"
                f"💰 **Balance:** ₹{balance}\n\n"
                f"Use /help to see available commands."
            )
        else:
            welcome_message = "❌ Error creating user account. Please contact admin."
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    
    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balance command"""
        user_id = update.effective_user.id
        
        # Get user balance
        balance = self.user_manager.get_user_balance(user_id)
        
        # Get recent transactions
        transactions = self.user_manager.get_user_transactions(user_id, limit=5)
        
        message = f"💰 **Your Balance:** ₹{balance}\n\n"
        
        if transactions:
            message += "**Recent Transactions:**\n"
            for tx in transactions:
                tx_type = tx['type'].title()
                tx_amount = tx['amount']
                tx_time = tx['timestamp'].strftime('%m-%d %H:%M')
                
                if tx_amount > 0:
                    message += f"✅ {tx_type}: +₹{tx_amount} ({tx_time})\n"
                else:
                    message += f"❌ {tx_type}: ₹{tx_amount} ({tx_time})\n"
        else:
            message += "No recent transactions."
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = (
            "🤖 **Ludo Bot Manager - Help**\n\n"
            "**User Commands:**\n"
            "/start - Start the bot\n"
            "/balance - Check your balance\n"
            "/help - Show this help message\n\n"
            
            "**Admin Commands:**\n"
            "/addbalance <user_id> <amount> - Add balance to user\n"
            "/withdraw <amount> - Withdraw from your balance\n"
            "/balancesheet - Show balance sheet\n"
            "/stats - Show bot statistics\n"
            "/activegames - Show active games\n"
            "/expiregames - Expire old games\n\n"
            
            "**Game Management:**\n"
            "Admin can send game tables directly in the group.\n"
            "Bot will automatically detect and process them.\n"
            "Admin will receive winner selection via DM."
        )
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def balance_sheet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balancesheet command (admin only)"""
        user_id = update.effective_user.id
        
        if str(user_id) not in [str(x) for x in self.admin_ids]:
            await update.message.reply_text("❌ Admin access required.")
            return
        
        # Create balance sheet keyboard
        keyboard = self.balance_sheet_manager.create_balance_sheet_keyboard()
        
        await update.message.reply_text(
            "📊 **Balance Sheet Options**\nSelect an option:",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command (admin only)"""
        user_id = update.effective_user.id
        
        if str(user_id) not in [str(x) for x in self.admin_ids]:
            await update.message.reply_text("❌ Admin access required.")
            return
        
        # Get overall statistics
        stats = self.balance_sheet_manager.get_overall_statistics(days=30)
        
        await update.message.reply_text(stats, parse_mode='Markdown')
    
    async def active_games_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /activegames command (admin only)"""
        user_id = update.effective_user.id
        
        if str(user_id) not in [str(x) for x in self.admin_ids]:
            await update.message.reply_text("❌ Admin access required.")
            return
        
        # Get active games
        active_games = self.game_manager.get_active_games()
        
        # No in-memory active games list with the minimal tracker
        message = "🎮 Active games listing is not available in minimal tracker."
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def expire_games_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /expiregames command (admin only)"""
        user_id = update.effective_user.id
        
        if str(user_id) not in [str(x) for x in self.admin_ids]:
            await update.message.reply_text("❌ Admin access required.")
            return
        
        # Expire old games
        # Not supported in minimal tracker
        message = "⏰ Expire games is not available in minimal tracker."
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def add_balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addbalance command (admin only)"""
        user_id = update.effective_user.id
        
        if str(user_id) not in [str(x) for x in self.admin_ids]:
            await update.message.reply_text("❌ Admin access required.")
            return
        
        # Parse command arguments
        args = context.args
        if len(args) != 2:
            await update.message.reply_text("❌ Usage: /addbalance <user_id> <amount>")
            return
        
        try:
            target_user_id = int(args[0])
            amount = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID or amount.")
            return
        
        # Add balance
        success = self.user_manager.add_balance(target_user_id, amount, user_id, "Admin addition")
        
        if success:
            await update.message.reply_text(f"✅ Added ₹{amount} to user {target_user_id}")
        else:
            await update.message.reply_text("❌ Failed to add balance.")
    
    async def withdraw_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /withdraw command"""
        user_id = update.effective_user.id
        
        # Parse command arguments
        args = context.args
        if len(args) != 1:
            await update.message.reply_text("❌ Usage: /withdraw <amount>")
            return
        
        try:
            amount = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid amount.")
            return
        
        # Withdraw balance
        success = self.user_manager.withdraw_balance(user_id, amount, "User withdrawal")
        
        if success:
            await update.message.reply_text(f"✅ Withdrew ₹{amount} from your balance.")
        else:
            await update.message.reply_text("❌ Failed to withdraw. Check your balance.")
    
    async def handle_balance_sheet_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle balance sheet callback queries"""
        query = update.callback_query
        await query.answer()
        
        # Get response from balance sheet manager
        response = self.balance_sheet_manager.handle_balance_sheet_callback(query.data)
        
        await query.edit_message_text(response, parse_mode='Markdown')
    
    async def handle_winner_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle winner selection from admin DM"""
        query = update.callback_query
        await query.answer()
        
        # Parse callback data: winner_gameid_username
        data = query.data.split('_')
        if len(data) != 3 or data[0] != 'winner':
            await query.edit_message_text("❌ Invalid winner selection data.")
            return
        
        game_id = data[1]
        winner_username = data[2]
        
        # Minimal tracker handles winner via edit in Pyrogram; DM/crediting happens there
        await query.edit_message_text(
            f"🏆 **Winner Selected!**\n\n"
            f"**Game:** {game_id}\n"
            f"**Winner:** {winner_username}\n\n"
            f"Result will be processed automatically."
        )
    
    async def handle_all_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all text messages"""
        # Minimal tracker handles message logic in Pyrogram listeners
        pass
    
    async def handle_edited_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle edited messages (fallback for manual editing)"""
        if not update.edited_message:
            return
        
        message = update.edited_message
        message_text = message.text
        
        # Check if this is a game table message with winner
        if "✅" in message_text and ("Full" in message_text or "full" in message_text):
            # Find the corresponding game
            game_data = self.database.get_game_by_message_id(message.message_id, message.chat.id)
            
            if game_data:
                # Extract winner
                winner_username = self.game_manager.extract_winner_from_edited_message(message_text)
                
                if winner_username:
                    # Process game result
                    success = self.game_manager.process_game_result(game_data['game_id'], winner_username)
                    
                    if success:
                        await message.reply_text(f"🏆 Winner detected: {winner_username}")
                    else:
                        await message.reply_text("❌ Failed to process game result.")
    
    async def expire_old_games(self, context: ContextTypes.DEFAULT_TYPE):
        """Expire old games (scheduled job)"""
        # Not applicable with minimal tracker
        return
    
    async def periodic_balance_sheet_update(self, context: ContextTypes.DEFAULT_TYPE):
        """Update pinned balance sheet (scheduled job)"""
        try:
            if self.balance_sheet_manager.pinned_balance_msg_id:
                self.balance_sheet_manager.update_pinned_balance_sheet(self.group_id)
        except Exception as e:
            logger.error(f"❌ Error updating balance sheet: {e}")
    
    async def start_pyrogram_client(self):
        """Start Pyrogram client if available"""
        if self.pyro_manager:
            try:
                await self.pyro_manager.start_client()
            except Exception as e:
                logger.error(f"❌ Failed to start Pyrogram client: {e}")
    
    def run(self):
        """Run the bot"""
        try:
            # Create application
            self.application = Application.builder().token(self.bot_token).build()
            
            # Add handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("balance", self.balance_command))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("balancesheet", self.balance_sheet_command))
            self.application.add_handler(CommandHandler("stats", self.stats_command))
            self.application.add_handler(CommandHandler("activegames", self.active_games_command))
            self.application.add_handler(CommandHandler("expiregames", self.expire_games_command))
            self.application.add_handler(CommandHandler("addbalance", self.add_balance_command))
            self.application.add_handler(CommandHandler("withdraw", self.withdraw_command))
            
            # Callback query handlers
            self.application.add_handler(CallbackQueryHandler(self.handle_balance_sheet_callback, pattern=r"^balance_"))
            self.application.add_handler(CallbackQueryHandler(self.handle_winner_selection, pattern=r"^winner_"))
            
            # Message handlers
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_all_messages))
            
            # Edited message handler
            async def edited_message_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if update.edited_message:
                    await self.handle_edited_messages(update, context)
            
            self.application.add_handler(TypeHandler(Update, edited_message_wrapper))
            
            # Set up job queue
            job_queue = self.application.job_queue
            
            if job_queue:
                # Schedule game expiration check every 5 minutes
                # Disabled for minimal tracker
                
                # Schedule balance sheet update every 5 minutes
                job_queue.run_repeating(
                    callback=self.periodic_balance_sheet_update,
                    interval=300,  # 5 minutes
                    first=120,     # Start after 2 minutes
                    name="balance_sheet_update"
                )
            
            print("🤖 Ludo Bot Manager is starting...")
            print(f"✅ Bot Token: {self.bot_token[:10]}...")
            print(f"✅ Group ID: {self.group_id}")
            print(f"✅ Admin IDs: {len(self.admin_ids)} admins configured")
            
            if self.pyro_manager:
                print("🚀 Pyrogram client will be started when bot begins polling...")
                print("✅ Pyrogram handlers configured and ready")
                # If the low-level client is available, attach the minimal tracker now
                try:
                    if getattr(self.pyro_manager, 'pyro_client', None) is not None:
                        register_pyro_table_tracker(
                            self.pyro_manager.pyro_client,
                            int(self.group_id),
                            self.admin_ids,
                            database=self.database,
                            balance_sheet_manager=self.balance_sheet_manager,
                        )
                except Exception as e:
                    logger.warning(f"Failed to register minimal tracker: {e}")
            
            print("Bot is running! Press Ctrl+C to stop.")
            
            # Start the bot
            self.application.run_polling(
                allowed_updates=["message", "edited_message", "callback_query"],
                drop_pending_updates=True
            )
            
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            print(f"❌ Failed to start bot: {e}")

if __name__ == "__main__":
    bot_manager = LudoBotManager()
    bot_manager.run()
