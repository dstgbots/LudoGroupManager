#!/usr/bin/env python3
"""
Pyrogram client module for Ludo Bot Manager
Handles all Pyrogram operations including message handling, editing, and client management
"""

import logging
import asyncio
import re
from datetime import datetime
from pyrogram import Client
from pyrogram import filters as pyrogram_filters
from pyrogram.handlers import MessageHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

class PyrogramManager:
    def __init__(self, api_id, api_hash, group_id, admin_ids):
        """Initialize Pyrogram client and handlers"""
        self.api_id = api_id
        self.api_hash = api_hash
        self.group_id = group_id
        self.admin_ids = admin_ids
        self.pyro_client = None
        self.database = None
        self.telegram_bot = None
        
        # Initialize Pyrogram client
        self._init_pyrogram_client()
    
    def _init_pyrogram_client(self):
        """Initialize Pyrogram client with API credentials"""
        try:
            logger.info(f"🔍 Pyrogram API credentials found: API_ID={self.api_id}")
            self.pyro_client = Client(
                "ludo_bot_pyrogram",
                api_id=int(self.api_id),
                api_hash=self.api_hash,
                no_updates=False  # We want to receive updates for edited messages
            )
            
            # Set up Pyrogram handlers for edited messages
            self._setup_pyrogram_handlers()
            
            logger.info("✅ Pyrogram client initialized for edited message handling and admin message editing")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Pyrogram client: {e}")
            self.pyro_client = None
    
    def _setup_pyrogram_handlers(self):
        """Set up Pyrogram handlers for edited messages and other updates"""
        if not self.pyro_client:
            return
            
        try:
            # Handler for edited messages in the configured group
            async def handle_pyrogram_edited_message(client, message):
                """Handle edited messages via Pyrogram"""
                try:
                    logger.info(f"🔍 Pyrogram: Received edited message {message.id} in chat {message.chat.id}")
                    
                    # Check if this is a game table message
                    if ("Full" in message.text or "full" in message.text):
                        logger.info(f"🎮 Pyrogram: Detected edited game table message: {message.text[:100]}...")
                        
                        # Process the edited message for game results
                        await self._process_pyrogram_edited_message(message)
                    else:
                        logger.info(f"📝 Pyrogram: Edited message is not a game table")
                        
                except Exception as e:
                    logger.error(f"❌ Pyrogram: Error handling edited message: {e}")
            
            # Handler for new messages in the configured group (to detect game tables)
            async def handle_pyrogram_new_message(client, message):
                """Handle new messages via Pyrogram"""
                try:
                    logger.info(f"🔍 Pyrogram: Received new message {message.id} in chat {message.chat.id}")
                    
                    # Check if this is a game table message from admin
                    if (("Full" in message.text or "full" in message.text) and
                        message.from_user.id in self.admin_ids):
                        
                        logger.info(f"🎮 Pyrogram: Detected new game table from admin: {message.text[:100]}...")
                        
                        # Process the new game table
                        await self._process_pyrogram_new_game_table(message)
                        
                except Exception as e:
                    logger.error(f"❌ Pyrogram: Error handling new message: {e}")
            
            # Add handlers using Pyrogram 1.x syntax
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
    
    async def start_client(self):
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
    
    async def stop_client(self):
        """Stop the Pyrogram client"""
        try:
            if self.pyro_client and self.pyro_client.is_connected:
                await self.pyro_client.stop()
                logger.info("✅ Pyrogram client stopped successfully")
        except Exception as e:
            logger.error(f"❌ Error stopping Pyrogram client: {e}")
    
    def set_dependencies(self, database, telegram_bot):
        """Set database and telegram bot dependencies"""
        self.database = database
        self.telegram_bot = telegram_bot
    
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
                game_data = self.database.get_game_by_message_id(message.id, message.chat.id)
                
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
                self.database.create_game(game_data)
                
                # Send winner selection message to admin's DM
                await self._send_winner_selection_to_admin(game_data, message.from_user.id)
                
                # Send confirmation to group
                await self._send_group_confirmation(message.chat.id)
                
            else:
                logger.warning("⚠️ Pyrogram: Could not extract game data from message")
                
        except Exception as e:
            logger.error(f"❌ Pyrogram: Error processing new game table: {e}")
    
    def _extract_winner_from_edited_message(self, message_text):
        """Extract winner username from edited message text"""
        try:
            # Look for username followed by ✅
            # Pattern: @username ✅ or username ✅
            patterns = [
                r'@(\w+)\s*✅',  # @username ✅
                r'(\w+)\s*✅',   # username ✅
                r'✅\s*@(\w+)',  # ✅ @username
                r'✅\s*(\w+)'    # ✅ username
            ]
            
            for pattern in patterns:
                match = re.search(pattern, message_text, re.IGNORECASE)
                if match:
                    username = match.group(1)
                    logger.info(f"🏆 Winner username extracted: {username}")
                    return username
            
            logger.warning("⚠️ No winner pattern found in edited message")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error extracting winner: {e}")
            return None
    
    def _extract_game_data_from_message(self, message_text, admin_user_id, message_id, chat_id):
        """Extract game data from message text"""
        try:
            # Parse the message to extract usernames and amount
            lines = message_text.strip().split('\n')
            
            usernames = []
            amount = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Check if line contains "Full" keyword
                if "Full" in line or "full" in line:
                    # Extract amount from this line
                    # Pattern: amount Full (e.g., "400 Full")
                    amount_match = re.search(r'(\d+)\s*[Ff]ull', line)
                    if amount_match:
                        amount = int(amount_match.group(1))
                        logger.info(f"💰 Amount extracted: {amount}")
                else:
                    # Check if line contains a username
                    # Pattern: @username or username
                    username_match = re.search(r'@?(\w+)', line)
                    if username_match:
                        username = username_match.group(1)
                        if username not in usernames:
                            usernames.append(username)
                            logger.info(f"👤 Username extracted: {username}")
            
            if not usernames or not amount:
                logger.warning("⚠️ Could not extract usernames or amount from message")
                return None
            
            # Create game data
            game_id = f"game_{int(datetime.now().timestamp())}"
            game_data = {
                'game_id': game_id,
                'admin_user_id': admin_user_id,
                'admin_message_id': message_id,
                'chat_id': chat_id,
                'bet_amount': amount,  # Add this field for compatibility
                'players': [
                    {'username': username, 'bet_amount': amount}
                    for username in usernames
                ],
                'total_amount': amount * len(usernames),
                'status': 'active',
                'created_at': datetime.now()
            }
            
            logger.info(f"🎮 Game data created: {game_id} with {len(usernames)} players, amount: {amount}")
            return game_data
            
        except Exception as e:
            logger.error(f"❌ Error extracting game data: {e}")
            return None
    
    async def _send_winner_selection_to_admin(self, game_data, admin_user_id):
        """Send winner selection message to admin's DM"""
        if not self.pyro_client or not self.pyro_client.is_connected:
            logger.warning("⚠️ Pyrogram client not available for sending winner selection")
            return
            
        try:
            # Create inline keyboard for winner selection
            keyboard = []
            for player in game_data['players']:
                keyboard.append([
                    InlineKeyboardButton(
                        f"🏆 {player['username']}",
                        callback_data=f"winner_{game_data['game_id']}_{player['username']}"
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send message to admin's DM
            await self.pyro_client.send_message(
                chat_id=admin_user_id,
                text=f"🎮 **Game Table Processed!**\n\n"
                     f"**Players:** {', '.join([p['username'] for p in game_data['players']])}\n"
                     f"**Amount:** ₹{game_data['total_amount']}\n\n"
                     f"**Select the winner:**",
                reply_markup=reply_markup,
                parse_mode="markdown"
            )
            
            logger.info(f"✅ Winner selection sent to admin {admin_user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error sending winner selection to admin: {e}")
    
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
            winner_user = self.database.get_user_by_username(winner_username)
            if winner_user:
                new_balance = winner_user['balance'] + winner_amount
                self.database.update_user_balance(winner_user['user_id'], new_balance)
                
                # Record transaction
                transaction_data = {
                    'user_id': winner_user['user_id'],
                    'type': 'win',
                    'amount': winner_amount,
                    'description': f'Game {game_data["game_id"]} - Winner',
                    'timestamp': datetime.now(),
                    'game_id': game_data['game_id']
                }
                self.database.create_transaction(transaction_data)
                
                # Notify winner
                await self.pyro_client.send_message(
                    chat_id=winner_user['user_id'],
                    text=f"🎉 **Congratulations! You won!**\n\n"
                         f"**Game:** {game_data['game_id']}\n"
                         f"**Winnings:** ₹{winner_amount}\n"
                         f"**New Balance:** ₹{new_balance}"
                )
            
            # Update game status
            self.database.update_game_status(
                game_data['game_id'], 
                'completed', 
                winner_username, 
                winner_amount, 
                admin_fee
            )
            
            logger.info(f"✅ Game result processed successfully for {game_data['game_id']}")
            
        except Exception as e:
            logger.error(f"❌ Error processing game result: {e}")
    
    def is_available(self):
        """Check if Pyrogram client is available and connected"""
        return self.pyro_client is not None and self.pyro_client.is_connected
