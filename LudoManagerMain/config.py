"""
Configuration file for LudoManager
==================================
Contains all configuration constants and environment variable mappings.
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', '5664706056:AAGweTBRqnaS1oQVEWkgxXl1WL9wUO_zuiA')
API_ID = int(os.getenv('API_ID', '18274091'))
API_HASH = os.getenv('API_HASH', '97afe4ab12cb99dab4bed25f768f5bbc')

# Group and Admin Configuration
GROUP_ID = int(os.getenv('GROUP_ID', '-1002849354155'))
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '2109516065').split(',') if x.strip()]

# Database Configuration
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'ludo_bot')

# Feature Flags
ENABLE_BALANCE_TRACKING = os.getenv('ENABLE_BALANCE_TRACKING', 'true').lower() == 'true'
ENABLE_AUTO_BALANCE_SHEET = os.getenv('ENABLE_AUTO_BALANCE_SHEET', 'true').lower() == 'true'
ENABLE_TRANSACTION_LOGGING = os.getenv('ENABLE_TRANSACTION_LOGGING', 'true').lower() == 'true'

# Game Configuration
DEFAULT_GAME_EXPIRY_HOURS = int(os.getenv('DEFAULT_GAME_EXPIRY_HOURS', '24'))
MAX_PLAYERS_PER_GAME = int(os.getenv('MAX_PLAYERS_PER_GAME', '4'))

# Logging Configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
