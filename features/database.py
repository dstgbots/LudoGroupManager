#!/usr/bin/env python3
"""
Database operations module for Ludo Bot Manager
Handles all MongoDB operations including users, games, transactions, and balance sheets
"""

import logging
from datetime import datetime, timedelta
from pymongo import MongoClient
from collections import defaultdict

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, mongo_uri, database_name="ludo_bot"):
        """Initialize database connection and collections"""
        try:
            self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            self.db = self.client[database_name]
            
            # Initialize collections
            self.users_collection = self.db.users
            self.games_collection = self.db.games
            self.transactions_collection = self.db.transactions
            self.balance_sheet_collection = self.db.balance_sheet
            
            # Test connection
            self.client.admin.command('ping')
            logger.info("✅ MongoDB connection established successfully")
            
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            raise Exception(f"Failed to connect to MongoDB: {e}")
    
    def close_connection(self):
        """Close MongoDB connection"""
        try:
            if self.client:
                self.client.close()
                logger.info("✅ MongoDB connection closed")
        except Exception as e:
            logger.error(f"❌ Error closing MongoDB connection: {e}")
    
    # User Management Methods
    def get_user(self, user_id):
        """Get user by user_id"""
        return self.users_collection.find_one({'user_id': user_id})
    
    def get_user_by_username(self, username):
        """Get user by username"""
        return self.users_collection.find_one({'username': username})
    
    def create_user(self, user_id, username, first_name, last_name=None):
        """Create a new user"""
        user_data = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'balance': 0,
            'created_at': datetime.now(),
            'last_updated': datetime.now()
        }
        result = self.users_collection.insert_one(user_data)
        logger.info(f"✅ Created new user: {username} (ID: {user_id})")
        return result.inserted_id
    
    def update_user_balance(self, user_id, new_balance):
        """Update user balance"""
        result = self.users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'balance': new_balance, 'last_updated': datetime.now()}}
        )
        return result.modified_count > 0
    
    def get_all_users(self):
        """Get all users"""
        return list(self.users_collection.find())
    
    # Game Management Methods
    def create_game(self, game_data):
        """Create a new game"""
        result = self.games_collection.insert_one(game_data)
        logger.info(f"✅ Created new game: {game_data['game_id']}")
        return result.inserted_id
    
    def get_game(self, game_id):
        """Get game by game_id"""
        return self.games_collection.find_one({'game_id': game_id})
    
    def get_game_by_message_id(self, message_id, chat_id):
        """Get game by admin message ID and chat ID"""
        return self.games_collection.find_one({
            'admin_message_id': message_id,
            'chat_id': chat_id
        })
    
    def update_game_status(self, game_id, status, winner=None, winner_amount=None, admin_fee=None):
        """Update game status and winner information"""
        update_data = {
            'status': status,
            'completed_at': datetime.now()
        }
        
        if winner:
            update_data['winner'] = winner
        if winner_amount:
            update_data['winner_amount'] = winner_amount
        if admin_fee:
            update_data['admin_fee'] = admin_fee
        
        result = self.games_collection.update_one(
            {'game_id': game_id},
            {'$set': update_data}
        )
        return result.modified_count > 0
    
    def get_active_games(self):
        """Get all active games"""
        return list(self.games_collection.find({'status': 'active'}))
    
    def get_expired_games(self, expiry_hours=24):
        """Get games that have expired"""
        expiry_time = datetime.now() - timedelta(hours=expiry_hours)
        return list(self.games_collection.find({
            'status': 'active',
            'created_at': {'$lt': expiry_time}
        }))
    
    # Transaction Methods
    def create_transaction(self, transaction_data):
        """Create a new transaction"""
        result = self.transactions_collection.insert_one(transaction_data)
        logger.info(f"✅ Created transaction: {transaction_data['type']} - {transaction_data['amount']}")
        return result.inserted_id
    
    def get_user_transactions(self, user_id, limit=50):
        """Get transactions for a specific user"""
        return list(self.transactions_collection.find(
            {'user_id': user_id}
        ).sort('timestamp', -1).limit(limit))
    
    def get_transactions_by_game(self, game_id):
        """Get all transactions for a specific game"""
        return list(self.transactions_collection.find({'game_id': game_id}))
    
    # Balance Sheet Methods
    def get_balance_sheet(self, date=None):
        """Get balance sheet for a specific date or current date"""
        if not date:
            date = datetime.now().date()
        
        # Get start and end of day
        start_of_day = datetime.combine(date, datetime.min.time())
        end_of_day = datetime.combine(date, datetime.max.time())
        
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
        
        return list(self.transactions_collection.aggregate(pipeline))
    
    def get_monthly_stats(self, year, month):
        """Get monthly statistics"""
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)
        
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
        
        return list(self.transactions_collection.aggregate(pipeline))
    
    def save_pinned_message_id(self, message_id):
        """Save pinned balance sheet message ID"""
        self.balance_sheet_collection.update_one(
            {'type': 'pinned_balance_sheet'},
            {'$set': {'message_id': message_id, 'updated_at': datetime.now()}},
            upsert=True
        )
        logger.info(f"✅ Saved pinned message ID: {message_id}")
    
    def get_pinned_message_id(self):
        """Get pinned balance sheet message ID"""
        data = self.balance_sheet_collection.find_one({'type': 'pinned_balance_sheet'})
        return data.get('message_id') if data else None
    
    # Statistics Methods
    def get_user_stats(self, user_id, days=30):
        """Get user statistics for the last N days"""
        start_date = datetime.now() - timedelta(days=days)
        
        pipeline = [
            {
                '$match': {
                    'user_id': user_id,
                    'timestamp': {'$gte': start_date}
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
        
        return list(self.transactions_collection.aggregate(pipeline))
    
    def get_overall_stats(self, days=30):
        """Get overall bot statistics for the last N days"""
        start_date = datetime.now() - timedelta(days=days)
        
        # User count
        total_users = self.users_collection.count_documents({})
        active_users = self.users_collection.count_documents({
            'last_updated': {'$gte': start_date}
        })
        
        # Game count
        total_games = self.games_collection.count_documents({})
        active_games = self.games_collection.count_documents({'status': 'active'})
        completed_games = self.games_collection.count_documents({'status': 'completed'})
        
        # Transaction stats
        pipeline = [
            {
                '$match': {
                    'timestamp': {'$gte': start_date}
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
        
        transaction_stats = list(self.transactions_collection.aggregate(pipeline))
        
        return {
            'total_users': total_users,
            'active_users': active_users,
            'total_games': total_games,
            'active_games': active_games,
            'completed_games': completed_games,
            'transaction_stats': transaction_stats
        }
