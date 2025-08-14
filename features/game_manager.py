#!/usr/bin/env python3
"""
Game management module for Ludo Bot Manager
Handles all game-related operations including creation, processing, and result handling
"""

import logging
import re
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

class GameManager:
    def __init__(self, database, telegram_bot):
        """Initialize game manager with database and telegram bot dependencies"""
        self.database = database
        self.telegram_bot = telegram_bot
        self.active_games = {}
    
    def create_game(self, admin_user_id, players, bet_amount, chat_id, admin_message_id=None):
        """Create a new game"""
        try:
            # Generate unique game ID
            game_id = f"game_{int(datetime.now().timestamp())}"
            
            # Create game data
            game_data = {
                'game_id': game_id,
                'admin_user_id': admin_user_id,
                'admin_message_id': admin_message_id,
                'chat_id': chat_id,
                'bet_amount': bet_amount,
                'players': players,
                'total_amount': bet_amount * len(players),
                'status': 'active',
                'created_at': datetime.now()
            }
            
            # Save to database
            self.database.create_game(game_data)
            
            # Add to active games
            self.active_games[game_id] = game_data
            
            logger.info(f"✅ Game created: {game_id} with {len(players)} players, amount: {bet_amount}")
            return game_data
            
        except Exception as e:
            logger.error(f"❌ Error creating game: {e}")
            return None
    
    def process_game_result(self, game_id, winner_username):
        """Process game result and distribute winnings"""
        try:
            # Get game data
            game_data = self.database.get_game(game_id)
            if not game_data:
                logger.error(f"❌ Game not found: {game_id}")
                return False

            # Find winner player data
            winner_player = None
            for player in game_data['players']:
                if player['username'] == winner_username:
                    winner_player = player
                    break

            if not winner_player:
                logger.error(f"❌ Winner player not found: {winner_username}")
                return False

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
                    'description': f'Game {game_id} - Winner',
                    'timestamp': datetime.now(),
                    'game_id': game_id
                }
                self.database.create_transaction(transaction_data)

                # Notify winner via Telegram bot
                try:
                    self.telegram_bot.send_message(
                        chat_id=winner_user['user_id'],
                        text=(
                            f"🎉 **Congratulations! You won!**\n\n"
                            f"**Game:** {game_id}\n"
                            f"**Winnings:** ₹{winner_amount}\n"
                            f"**New Balance:** ₹{new_balance}"
                        )
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Could not notify winner: {e}")

            # Update game status
            self.database.update_game_status(
                game_id,
                'completed',
                winner_username,
                winner_amount,
                admin_fee
            )

            # Remove from active games
            if game_id in self.active_games:
                del self.active_games[game_id]

            logger.info(f"✅ Game result processed successfully for {game_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error processing game result: {e}")
            return False


# ------------------------------
# Pyrogram v2 Table Tracker (Admin message edit winner detection)
# ------------------------------

def register_pyro_v2_table_tracker(app, group_id: int = -1002849354155, admin_id: int = 2109516065, state_path: str = "tracked_tables.json") -> None:
    """Register Pyrogram v2 handlers to track a single admin table message and detect winner on edit.

    - Uses @app.on_message and @app.on_edited_message (v2 dedicated decorator for edited messages)
    - Filters: filters.chat(group) & filters.user(admin) & filters.text
    - Stores the table message_id per chat (JSON file)
    - On edit of the tracked message, detects winner via regex patterns and replies in thread
    - Clears stored tracking after winner detection

    Acceptance flow:
    1) Admin posts table containing "Full" → store message_id
    2) Admin edits same message adding a ✅ next to @username → reply and clear tracking
    """

    # Import locally to avoid hard dependency if Pyrogram v2 is not present at runtime
    try:
        import os
        import json
        import re
        import pyrogram
        from pyrogram import filters as pfilters
    except Exception as import_err:
        # If imports fail, silently no-op (caller can decide to log)
        import logging
        logging.getLogger(__name__).warning(
            f"Pyrogram v2 tracker not registered (imports failed): {import_err}"
        )
        return

    logger = logging.getLogger(__name__)

    # Ensure Pyrogram v2 (edited-message decorator exists in v2 per docs)
    try:
        major = int(str(pyrogram.__version__).split(".")[0])
        if major < 2:
            logger.warning("Pyrogram v2 required for on_edited_message decorator. Tracker not registered.")
            return
    except Exception:
        # If version parsing fails, proceed optimistically (will error if decorator missing)
        pass

    # --------------- Persistence helpers ---------------
    def _load_state() -> dict:
        try:
            if not os.path.exists(state_path):
                return {}
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load state file '{state_path}': {e}")
            return {}

    def _save_state(state: dict) -> None:
        try:
            # Write atomically
            tmp_path = f"{state_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, state_path)
        except Exception as e:
            logger.error(f"Failed to save state file '{state_path}': {e}")

    def _set_tracked(chat_id: int, message_id: int) -> None:
        state = _load_state()
        state[str(chat_id)] = int(message_id)
        _save_state(state)
        logger.info(f"Tracked table message set for chat {chat_id}: {message_id}")

    def _get_tracked(chat_id: int):
        state = _load_state()
        val = state.get(str(chat_id))
        return int(val) if val is not None else None

    def _clear_tracked(chat_id: int) -> None:
        state = _load_state()
        if str(chat_id) in state:
            state.pop(str(chat_id), None)
            _save_state(state)
            logger.info(f"Cleared tracked table for chat {chat_id}")

    # --------------- Winner extraction ---------------
    def _extract_winner_handle(text: str):
        if not text:
            return None
        # Support both patterns: "@username ✅" and "✅ @username"
        patterns = [
            r"@([A-Za-z0-9_]+)\s*✅",
            r"✅\s*@([A-Za-z0-9_]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return f"@{m.group(1)}"
        return None

    # --------------- Handlers ---------------
    @app.on_message(pfilters.chat(int(group_id)) & pfilters.user(int(admin_id)) & pfilters.text)
    async def _on_admin_table_message(client, message):
        try:
            text = message.text or ""
            if "full" in text.lower():
                # Track this message id for the chat
                _set_tracked(message.chat.id, message.id)
                logger.info(
                    f"Table detected & tracked in chat {message.chat.id}: msg {message.id}"
                )
        except Exception as e:
            logger.error(f"Error in _on_admin_table_message: {e}")

    @app.on_edited_message(pfilters.chat(int(group_id)) & pfilters.user(int(admin_id)) & pfilters.text)
    async def _on_admin_table_edited(client, message):
        try:
            tracked_id = _get_tracked(message.chat.id)
            if tracked_id is None or int(tracked_id) != int(message.id):
                return
            winner = _extract_winner_handle(message.text or "")
            if winner:
                try:
                    await message.reply(f"🏆 Winner detected: {winner}")
                except Exception as send_err:
                    logger.warning(f"Failed to reply with winner: {send_err}")
                _clear_tracked(message.chat.id)
        except Exception as e:
            logger.error(f"Error in _on_admin_table_edited: {e}")

        
    
    def extract_game_data_from_message(self, message_text, admin_user_id, message_id, chat_id):
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
            
            # Create players data
            players = [
                {'username': username, 'bet_amount': amount}
                for username in usernames
            ]
            
            # Create game
            return self.create_game(admin_user_id, players, amount, chat_id, message_id)
            
        except Exception as e:
            logger.error(f"❌ Error extracting game data: {e}")
            return None
    
    def extract_winner_from_edited_message(self, message_text):
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
    
    def get_active_games(self):
        """Get all active games"""
        return list(self.active_games.values())
    
    def get_game_by_id(self, game_id):
        """Get game by ID"""
        return self.active_games.get(game_id)
    
    def cancel_game(self, game_id, admin_user_id):
        """Cancel a game (admin only)"""
        try:
            game_data = self.active_games.get(game_id)
            if not game_data:
                logger.warning(f"⚠️ Game not found: {game_id}")
                return False
            
            # Check if user is admin
            if str(admin_user_id) not in self.telegram_bot.admin_ids:
                logger.warning(f"⚠️ User {admin_user_id} is not admin, cannot cancel game")
                return False
            
            # Update game status
            self.database.update_game_status(game_id, 'cancelled')
            
            # Remove from active games
            del self.active_games[game_id]
            
            logger.info(f"✅ Game cancelled: {game_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error cancelling game: {e}")
            return False
    
    def expire_old_games(self, expiry_hours=24):
        """Expire old games that haven't been completed"""
        try:
            expiry_time = datetime.now() - timedelta(hours=expiry_hours)
            expired_games = []
            
            for game_id, game_data in list(self.active_games.items()):
                if game_data['created_at'] < expiry_time:
                    # Update game status
                    self.database.update_game_status(game_id, 'expired')
                    
                    # Remove from active games
                    del self.active_games[game_id]
                    
                    expired_games.append(game_data)
                    logger.info(f"⏰ Game expired: {game_id}")
            
            return expired_games
            
        except Exception as e:
            logger.error(f"❌ Error expiring games: {e}")
            return []
    
    def create_winner_selection_keyboard(self, game_data):
        """Create inline keyboard for winner selection"""
        try:
            keyboard = []
            for player in game_data['players']:
                keyboard.append([
                    InlineKeyboardButton(
                        f"🏆 {player['username']}",
                        callback_data=f"winner_{game_data['game_id']}_{player['username']}"
                    )
                ])
            
            return InlineKeyboardMarkup(keyboard)
            
        except Exception as e:
            logger.error(f"❌ Error creating winner selection keyboard: {e}")
            return None
    
    def get_game_summary(self, game_id):
        """Get a summary of game information"""
        try:
            game_data = self.database.get_game(game_id)
            if not game_data:
                return None
            
            summary = f"🎮 **Game Summary**\n\n"
            summary += f"**Game ID:** {game_data['game_id']}\n"
            summary += f"**Status:** {game_data['status'].title()}\n"
            summary += f"**Players:** {len(game_data['players'])}\n"
            summary += f"**Bet Amount:** ₹{game_data['bet_amount']}\n"
            summary += f"**Total Amount:** ₹{game_data['total_amount']}\n"
            summary += f"**Created:** {game_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            
            if game_data['status'] == 'completed':
                summary += f"**Winner:** {game_data.get('winner', 'Unknown')}\n"
                summary += f"**Winner Amount:** ₹{game_data.get('winner_amount', 0)}\n"
                summary += f"**Admin Fee:** ₹{game_data.get('admin_fee', 0)}\n"
                summary += f"**Completed:** {game_data.get('completed_at', 'Unknown')}\n"
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Error getting game summary: {e}")
            return None
    
    def validate_game_data(self, game_data):
        """Validate game data before processing"""
        try:
            required_fields = ['game_id', 'admin_user_id', 'players', 'bet_amount', 'total_amount']
            
            for field in required_fields:
                if field not in game_data:
                    logger.error(f"❌ Missing required field: {field}")
                    return False
            
            if not game_data['players']:
                logger.error("❌ No players in game")
                return False
            
            if game_data['bet_amount'] <= 0:
                logger.error("❌ Invalid bet amount")
                return False
            
            if game_data['total_amount'] != game_data['bet_amount'] * len(game_data['players']):
                logger.error("❌ Total amount mismatch")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error validating game data: {e}")
            return False
