#!/usr/bin/env python3
"""
Startup script for Ludo Group Manager Bot
"""

import sys
import os
from config import validate_config
from bot import LudoBotManager

def main():
    """Main startup function"""
    print("🎮 Ludo Group Manager Bot")
    print("=" * 30)
    
    # Validate configuration
    if not validate_config():
        sys.exit(1)
    
    print("✅ Configuration validated successfully")
    
    try:
        # Initialize and start the bot
        bot_manager = LudoBotManager()
        bot_manager.run()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
