"""
LudoManager - Telegram Ludo Game Management Bot
===============================================

A comprehensive Telegram bot system for managing Ludo games, user balances, 
and group interactions with MongoDB integration.

Usage:
    python -m LudoManagerMain

Features:
- Game table detection and management
- Winner processing and announcements  
- User balance tracking
- Transaction logging
- MongoDB integration
- Pyrogram + python-telegram-bot integration

Author: LudoManager Team
Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "LudoManager Team"
__description__ = "Telegram Ludo Game Management Bot"

# Import main components for easy access
from . import bot
from . import test
from . import config

# Export main functions
__all__ = [
    "bot",
    "test", 
    "config",
    "__version__",
    "__author__",
    "__description__"
]
