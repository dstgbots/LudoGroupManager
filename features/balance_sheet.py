#!/usr/bin/env python3
"""
Balance sheet module for Ludo Bot Manager
Handles all balance sheet operations, statistics, and reporting
"""

import logging
from datetime import datetime, timedelta
import calendar
from collections import defaultdict

logger = logging.getLogger(__name__)

class BalanceSheetManager:
    def __init__(self, database, telegram_bot):
        """Initialize balance sheet manager with database and telegram bot dependencies"""
        self.database = database
        self.telegram_bot = telegram_bot
        self.pinned_balance_msg_id = None
        
        # Load pinned message ID
        self._load_pinned_message_id()
    
    def _load_pinned_message_id(self):
        """Load the pinned balance sheet message ID from database"""
        try:
            self.pinned_balance_msg_id = self.database.get_pinned_message_id()
            if self.pinned_balance_msg_id:
                logger.info(f"📌 Loaded pinned balance sheet message ID: {self.pinned_balance_msg_id}")
        except Exception as e:
            logger.error(f"Error loading pinned message ID: {e}")
    
    def save_pinned_message_id(self, message_id):
        """Save pinned balance sheet message ID"""
        try:
            self.database.save_pinned_message_id(message_id)
            self.pinned_balance_msg_id = message_id
            logger.info(f"✅ Saved pinned message ID: {message_id}")
        except Exception as e:
            logger.error(f"❌ Error saving pinned message ID: {e}")
    
    def get_daily_balance_sheet(self, date=None):
        """Get daily balance sheet for a specific date or current date"""
        try:
            if not date:
                date = datetime.now().date()
            
            # Get start and end of day
            start_of_day = datetime.combine(date, datetime.min.time())
            end_of_day = datetime.combine(date, datetime.max.time())
            
            # Get transactions for the day
            pipeline = [
                {
                    '$match': {
                        'timestamp': {'$gte': start_of_day, '$lte': end_of_day}
                    }
                },
                {
                    '$group': {
                        '_id': '$type',
                        'total_amount': {'$sum': '$amount'},
                        'count': {'$sum': 1}
                    }
                }
            ]
            
            daily_stats = list(self.database.transactions_collection.aggregate(pipeline))
            
            # Create balance sheet text
            balance_sheet = f"📊 **Daily Balance Sheet**\n"
            balance_sheet += f"📅 **Date:** {date.strftime('%Y-%m-%d')}\n\n"
            
            total_income = 0
            total_expense = 0
            
            for stat in daily_stats:
                tx_type = stat['_id']
                amount = stat['total_amount']
                count = stat['count']
                
                if amount > 0:
                    total_income += amount
                    balance_sheet += f"✅ **{tx_type.title()}:** +₹{amount} ({count} transactions)\n"
                else:
                    total_expense += abs(amount)
                    balance_sheet += f"❌ **{tx_type.title()}:** ₹{amount} ({count} transactions)\n"
            
            balance_sheet += f"\n💰 **Summary:**\n"
            balance_sheet += f"**Total Income:** ₹{total_income}\n"
            balance_sheet += f"**Total Expense:** ₹{total_expense}\n"
            balance_sheet += f"**Net:** ₹{total_income - total_expense}\n"
            
            return balance_sheet
            
        except Exception as e:
            logger.error(f"❌ Error getting daily balance sheet: {e}")
            return "❌ Error generating balance sheet"
    
    def get_monthly_balance_sheet(self, year=None, month=None):
        """Get monthly balance sheet for a specific month or current month"""
        try:
            if not year:
                year = datetime.now().year
            if not month:
                month = datetime.now().month
            
            # Get start and end of month
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
            
            # Get transactions for the month
            pipeline = [
                {
                    '$match': {
                        'timestamp': {'$gte': start_date, '$lt': end_date}
                    }
                },
                {
                    '$group': {
                        '_id': '$type',
                        'total_amount': {'$sum': '$amount'},
                        'count': {'$sum': 1}
                    }
                }
            ]
            
            monthly_stats = list(self.database.transactions_collection.aggregate(pipeline))
            
            # Create balance sheet text
            month_name = calendar.month_name[month]
            balance_sheet = f"📊 **Monthly Balance Sheet**\n"
            balance_sheet += f"📅 **Period:** {month_name} {year}\n\n"
            
            total_income = 0
            total_expense = 0
            
            for stat in monthly_stats:
                tx_type = stat['_id']
                amount = stat['total_amount']
                count = stat['count']
                
                if amount > 0:
                    total_income += amount
                    balance_sheet += f"✅ **{tx_type.title()}:** +₹{amount} ({count} transactions)\n"
                else:
                    total_expense += abs(amount)
                    balance_sheet += f"❌ **{tx_type.title()}:** ₹{amount} ({count} transactions)\n"
            
            balance_sheet += f"\n💰 **Summary:**\n"
            balance_sheet += f"**Total Income:** ₹{total_income}\n"
            balance_sheet += f"**Total Expense:** ₹{total_expense}\n"
            balance_sheet += f"**Net:** ₹{total_income - total_expense}\n"
            
            return balance_sheet
            
        except Exception as e:
            logger.error(f"❌ Error getting monthly balance sheet: {e}")
            return "❌ Error generating monthly balance sheet"
    
    def get_overall_statistics(self, days=30):
        """Get overall bot statistics for the last N days"""
        try:
            stats = self.database.get_overall_stats(days)
            
            # Create statistics text
            stats_text = f"📈 **Bot Statistics (Last {days} days)**\n\n"
            
            # User statistics
            stats_text += f"👥 **Users:**\n"
            stats_text += f"**Total Users:** {stats['total_users']}\n"
            stats_text += f"**Active Users:** {stats['active_users']}\n\n"
            
            # Game statistics
            stats_text += f"🎮 **Games:**\n"
            stats_text += f"**Total Games:** {stats['total_games']}\n"
            stats_text += f"**Active Games:** {stats['active_games']}\n"
            stats_text += f"**Completed Games:** {stats['completed_games']}\n\n"
            
            # Transaction statistics
            stats_text += f"💰 **Transactions:**\n"
            
            total_income = 0
            total_expense = 0
            
            for stat in stats['transaction_stats']:
                tx_type = stat['_id']
                amount = stat['total_amount']
                count = stat['count']
                
                if amount > 0:
                    total_income += amount
                    stats_text += f"✅ **{tx_type.title()}:** +₹{amount} ({count} tx)\n"
                else:
                    total_expense += abs(amount)
                    stats_text += f"❌ **{tx_type.title()}:** ₹{amount} ({count} tx)\n"
            
            stats_text += f"\n💰 **Financial Summary:**\n"
            stats_text += f"**Total Income:** ₹{total_income}\n"
            stats_text += f"**Total Expense:** ₹{total_expense}\n"
            stats_text += f"**Net:** ₹{total_income - total_expense}\n"
            
            return stats_text
            
        except Exception as e:
            logger.error(f"❌ Error getting overall statistics: {e}")
            return "❌ Error generating statistics"
    
    def get_user_balance_summary(self):
        """Get summary of all user balances"""
        try:
            users = self.database.get_all_users()
            
            if not users:
                return "❌ No users found"
            
            # Calculate balance statistics
            total_balance = sum(user.get('balance', 0) for user in users)
            avg_balance = total_balance / len(users) if users else 0
            
            # Find users with highest and lowest balances
            sorted_users = sorted(users, key=lambda x: x.get('balance', 0), reverse=True)
            top_users = sorted_users[:5]
            bottom_users = sorted_users[-5:] if len(sorted_users) >= 5 else sorted_users
            
            summary = f"💰 **User Balance Summary**\n\n"
            summary += f"**Total Users:** {len(users)}\n"
            summary += f"**Total Balance:** ₹{total_balance}\n"
            summary += f"**Average Balance:** ₹{avg_balance:.2f}\n\n"
            
            # Top users
            summary += f"🏆 **Top 5 Users:**\n"
            for i, user in enumerate(top_users, 1):
                username = user.get('username', 'Unknown')
                balance = user.get('balance', 0)
                summary += f"{i}. @{username}: ₹{balance}\n"
            
            summary += f"\n📉 **Bottom 5 Users:**\n"
            for i, user in enumerate(bottom_users, 1):
                username = user.get('username', 'Unknown')
                balance = user.get('balance', 0)
                summary += f"{i}. @{username}: ₹{balance}\n"
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Error getting user balance summary: {e}")
            return "❌ Error generating user balance summary"
    
    def get_game_statistics(self, days=30):
        """Get game statistics for the last N days"""
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            # Get games created in the last N days
            pipeline = [
                {
                    '$match': {
                        'created_at': {'$gte': start_date}
                    }
                },
                {
                    '$group': {
                        '_id': '$status',
                        'count': {'$sum': 1},
                        'total_amount': {'$sum': '$total_amount'}
                    }
                }
            ]
            
            game_stats = list(self.database.games_collection.aggregate(pipeline))
            
            # Get daily game creation trend
            daily_pipeline = [
                {
                    '$match': {
                        'created_at': {'$gte': start_date}
                    }
                },
                {
                    '$group': {
                        '_id': {
                            'year': {'$year': '$created_at'},
                            'month': {'$month': '$created_at'},
                            'day': {'$dayOfMonth': '$created_at'}
                        },
                        'count': {'$sum': 1}
                    }
                },
                {
                    '$sort': {'_id.year': 1, '_id.month': 1, '_id.day': 1}
                }
            ]
            
            daily_stats = list(self.database.games_collection.aggregate(daily_pipeline))
            
            # Create statistics text
            stats_text = f"🎮 **Game Statistics (Last {days} days)**\n\n"
            
            # Game status summary
            total_games = 0
            total_amount = 0
            
            for stat in game_stats:
                status = stat['_id']
                count = stat['count']
                amount = stat['total_amount']
                
                total_games += count
                total_amount += amount
                
                stats_text += f"**{status.title()} Games:** {count} (₹{amount})\n"
            
            stats_text += f"\n💰 **Summary:**\n"
            stats_text += f"**Total Games:** {total_games}\n"
            stats_text += f"**Total Amount:** ₹{total_amount}\n"
            stats_text += f"**Average Game Amount:** ₹{total_amount/total_games:.2f}\n" if total_games > 0 else "**Average Game Amount:** ₹0\n"
            
            # Daily trend
            if daily_stats:
                stats_text += f"\n📈 **Daily Trend:**\n"
                for stat in daily_stats[-7:]:  # Show last 7 days
                    date_info = stat['_id']
                    count = stat['count']
                    date_str = f"{date_info['year']}-{date_info['month']:02d}-{date_info['day']:02d}"
                    stats_text += f"{date_str}: {count} games\n"
            
            return stats_text
            
        except Exception as e:
            logger.error(f"❌ Error getting game statistics: {e}")
            return "❌ Error generating game statistics"
    
    def update_pinned_balance_sheet(self, chat_id):
        """Update the pinned balance sheet message"""
        try:
            if not self.pinned_balance_msg_id:
                logger.warning("⚠️ No pinned message ID found")
                return False
            
            # Get current balance sheet
            balance_sheet = self.get_daily_balance_sheet()
            
            # Update the pinned message
            self.telegram_bot.bot.edit_message_text(
                chat_id=chat_id,
                message_id=self.pinned_balance_msg_id,
                text=balance_sheet,
                parse_mode='Markdown'
            )
            
            logger.info("✅ Pinned balance sheet updated successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error updating pinned balance sheet: {e}")
            return False
    
    def create_balance_sheet_keyboard(self):
        """Create inline keyboard for balance sheet options"""
        try:
            keyboard = [
                [
                    InlineKeyboardButton("📊 Today", callback_data="balance_today"),
                    InlineKeyboardButton("📅 This Month", callback_data="balance_month")
                ],
                [
                    InlineKeyboardButton("📈 Statistics", callback_data="balance_stats"),
                    InlineKeyboardButton("👥 Users", callback_data="balance_users")
                ],
                [
                    InlineKeyboardButton("🎮 Games", callback_data="balance_games"),
                    InlineKeyboardButton("💰 Summary", callback_data="balance_summary")
                ]
            ]
            
            return InlineKeyboardMarkup(keyboard)
            
        except Exception as e:
            logger.error(f"❌ Error creating balance sheet keyboard: {e}")
            return None
    
    def handle_balance_sheet_callback(self, callback_data):
        """Handle balance sheet callback queries"""
        try:
            if callback_data == "balance_today":
                return self.get_daily_balance_sheet()
            elif callback_data == "balance_month":
                return self.get_monthly_balance_sheet()
            elif callback_data == "balance_stats":
                return self.get_overall_statistics()
            elif callback_data == "balance_users":
                return self.get_user_balance_summary()
            elif callback_data == "balance_games":
                return self.get_game_statistics()
            elif callback_data == "balance_summary":
                return self.get_overall_statistics(days=7)
            else:
                return "❌ Unknown balance sheet option"
                
        except Exception as e:
            logger.error(f"❌ Error handling balance sheet callback: {e}")
            return "❌ Error processing request"
