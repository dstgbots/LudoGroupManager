#!/usr/bin/env python3
"""
User management module for Ludo Bot Manager
Handles all user-related operations including balance management, transactions, and user data
"""

import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

class UserManager:
    def __init__(self, database, telegram_bot):
        """Initialize user manager with database and telegram bot dependencies"""
        self.database = database
        self.telegram_bot = telegram_bot
    
    def get_or_create_user(self, user_id, username, first_name, last_name=None):
        """Get existing user or create new one"""
        try:
            # Check if user exists
            user = self.database.get_user(user_id)
            
            if user:
                # Update last seen
                self.database.users_collection.update_one(
                    {'user_id': user_id},
                    {'$set': {'last_updated': datetime.now()}}
                )
                logger.info(f"✅ User found: {username} (ID: {user_id})")
                return user
            else:
                # Create new user
                user_id_created = self.database.create_user(user_id, username, first_name, last_name)
                logger.info(f"✅ New user created: {username} (ID: {user_id})")
                return self.database.get_user(user_id)
                
        except Exception as e:
            logger.error(f"❌ Error getting/creating user: {e}")
            return None
    
    def get_user_balance(self, user_id):
        """Get user's current balance"""
        try:
            user = self.database.get_user(user_id)
            if user:
                return user.get('balance', 0)
            return 0
        except Exception as e:
            logger.error(f"❌ Error getting user balance: {e}")
            return 0
    
    def update_user_balance(self, user_id, new_balance):
        """Update user's balance"""
        try:
            success = self.database.update_user_balance(user_id, new_balance)
            if success:
                logger.info(f"✅ Balance updated for user {user_id}: {new_balance}")
                return True
            else:
                logger.warning(f"⚠️ Failed to update balance for user {user_id}")
                return False
        except Exception as e:
            logger.error(f"❌ Error updating user balance: {e}")
            return False
    
    def add_balance(self, user_id, amount, admin_user_id, reason="Admin addition"):
        """Add balance to user (admin only)"""
        try:
            # Check if user is admin
            if str(admin_user_id) not in self.telegram_bot.admin_ids:
                logger.warning(f"⚠️ User {admin_user_id} is not admin, cannot add balance")
                return False
            
            current_balance = self.get_user_balance(user_id)
            new_balance = current_balance + amount
            
            if self.update_user_balance(user_id, new_balance):
                # Record transaction
                transaction_data = {
                    'user_id': user_id,
                    'type': 'admin_add',
                    'amount': amount,
                    'description': f'{reason} (Admin: {admin_user_id})',
                    'timestamp': datetime.now(),
                    'admin_user_id': admin_user_id
                }
                self.database.create_transaction(transaction_data)
                
                logger.info(f"✅ Balance added for user {user_id}: +{amount}")
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"❌ Error adding balance: {e}")
            return False
    
    def withdraw_balance(self, user_id, amount, reason="Withdrawal"):
        """Withdraw balance from user"""
        try:
            current_balance = self.get_user_balance(user_id)
            
            if current_balance < amount:
                logger.warning(f"⚠️ Insufficient balance for user {user_id}: {current_balance} < {amount}")
                return False
            
            new_balance = current_balance - amount
            
            if self.update_user_balance(user_id, new_balance):
                # Record transaction
                transaction_data = {
                    'user_id': user_id,
                    'type': 'withdraw',
                    'amount': -amount,  # Negative for withdrawal
                    'description': reason,
                    'timestamp': datetime.now()
                }
                self.database.create_transaction(transaction_data)
                
                logger.info(f"✅ Balance withdrawn for user {user_id}: -{amount}")
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"❌ Error withdrawing balance: {e}")
            return False
    
    def get_user_transactions(self, user_id, limit=50):
        """Get user's transaction history"""
        try:
            transactions = self.database.get_user_transactions(user_id, limit)
            return transactions
        except Exception as e:
            logger.error(f"❌ Error getting user transactions: {e}")
            return []
    
    def get_user_stats(self, user_id, days=30):
        """Get user statistics for the last N days"""
        try:
            stats = self.database.get_user_stats(user_id, days)
            return stats
        except Exception as e:
            logger.error(f"❌ Error getting user stats: {e}")
            return []
    
    def get_user_summary(self, user_id):
        """Get a summary of user information"""
        try:
            user = self.database.get_user(user_id)
            if not user:
                return None
            
            # Get recent transactions
            recent_transactions = self.get_user_transactions(user_id, limit=10)
            
            # Get stats
            stats = self.get_user_stats(user_id, days=30)
            
            summary = f"👤 **User Summary**\n\n"
            summary += f"**User ID:** {user['user_id']}\n"
            summary += f"**Username:** @{user['username']}\n"
            summary += f"**Name:** {user['first_name']}"
            if user.get('last_name'):
                summary += f" {user['last_name']}"
            summary += f"\n"
            summary += f"**Balance:** ₹{user['balance']}\n"
            summary += f"**Created:** {user['created_at'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            summary += f"**Last Updated:** {user['last_updated'].strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            # Add recent activity
            if recent_transactions:
                summary += f"**Recent Activity:**\n"
                for tx in recent_transactions[:5]:  # Show last 5 transactions
                    tx_type = tx['type'].title()
                    tx_amount = tx['amount']
                    tx_time = tx['timestamp'].strftime('%m-%d %H:%M')
                    
                    if tx_amount > 0:
                        summary += f"✅ {tx_type}: +₹{tx_amount} ({tx_time})\n"
                    else:
                        summary += f"❌ {tx_type}: ₹{tx_amount} ({tx_time})\n"
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Error getting user summary: {e}")
            return None
    
    def get_all_users_summary(self):
        """Get summary of all users"""
        try:
            users = self.database.get_all_users()
            
            summary = f"👥 **All Users Summary**\n\n"
            summary += f"**Total Users:** {len(users)}\n\n"
            
            # Group users by balance ranges
            balance_ranges = {
                '0-100': 0,
                '101-500': 0,
                '501-1000': 0,
                '1000+': 0
            }
            
            total_balance = 0
            active_users = 0
            
            for user in users:
                balance = user.get('balance', 0)
                total_balance += balance
                
                # Count active users (updated in last 7 days)
                if user.get('last_updated'):
                    days_since_update = (datetime.now() - user['last_updated']).days
                    if days_since_update <= 7:
                        active_users += 1
                
                # Categorize by balance
                if balance <= 100:
                    balance_ranges['0-100'] += 1
                elif balance <= 500:
                    balance_ranges['101-500'] += 1
                elif balance <= 1000:
                    balance_ranges['501-1000'] += 1
                else:
                    balance_ranges['1000+'] += 1
            
            summary += f"**Active Users (7 days):** {active_users}\n"
            summary += f"**Total Balance:** ₹{total_balance}\n\n"
            
            summary += f"**Balance Distribution:**\n"
            for range_name, count in balance_ranges.items():
                summary += f"₹{range_name}: {count} users\n"
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Error getting all users summary: {e}")
            return None
    
    def search_users(self, query):
        """Search users by username or name"""
        try:
            users = self.database.get_all_users()
            results = []
            
            query_lower = query.lower()
            
            for user in users:
                username = user.get('username', '').lower()
                first_name = user.get('first_name', '').lower()
                last_name = user.get('last_name', '').lower()
                
                if (query_lower in username or 
                    query_lower in first_name or 
                    query_lower in last_name):
                    results.append(user)
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Error searching users: {e}")
            return []
    
    def get_top_users(self, limit=10, by_balance=True):
        """Get top users by balance or activity"""
        try:
            users = self.database.get_all_users()
            
            if by_balance:
                # Sort by balance (descending)
                sorted_users = sorted(users, key=lambda x: x.get('balance', 0), reverse=True)
            else:
                # Sort by last activity (most recent first)
                sorted_users = sorted(users, key=lambda x: x.get('last_updated', datetime.min), reverse=True)
            
            return sorted_users[:limit]
            
        except Exception as e:
            logger.error(f"❌ Error getting top users: {e}")
            return []
    
    def cleanup_inactive_users(self, days_inactive=90):
        """Mark users as inactive if they haven't been active for N days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_inactive)
            
            # Find inactive users
            inactive_users = self.database.users_collection.find({
                'last_updated': {'$lt': cutoff_date}
            })
            
            count = 0
            for user in inactive_users:
                # Mark as inactive (you might want to add an 'active' field to your user schema)
                self.database.users_collection.update_one(
                    {'user_id': user['user_id']},
                    {'$set': {'status': 'inactive'}}
                )
                count += 1
            
            logger.info(f"✅ Marked {count} users as inactive")
            return count
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up inactive users: {e}")
            return 0
