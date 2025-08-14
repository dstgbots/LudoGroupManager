"""
LudoManager Main Entry Point
===========================

This file enables running LudoManager as a Python module:
    python -m LudoManagerMain

It handles the startup sequence and provides a unified entry point for the system.
"""

import os
import sys
import logging
from datetime import datetime

def check_dependencies():
    """Check if all required dependencies are installed."""
    required_packages = ['pyrogram', 'pymongo', 'python-telegram-bot', 'python-dotenv']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ Missing required packages:")
        for package in missing_packages:
            print(f"   - {package}")
        print(f"\n📦 Install with: pip install {' '.join(missing_packages)}")
        return False
    
    print("✅ All dependencies installed")
    return True

def check_configuration():
    """Check if configuration is properly set up."""
    if not os.path.exists('.env'):
        print("❌ .env file not found")
        print("📝 Create .env file from env_template.txt")
        print("💡 Example: copy env_template.txt to .env and configure your values")
        return False
    
    # Basic validation
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        required_vars = ['BOT_TOKEN', 'API_ID', 'API_HASH', 'GROUP_ID', 'ADMIN_IDS']
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            print("❌ Missing environment variables in .env file:")
            for var in missing_vars:
                print(f"   - {var}")
            print("\n📝 Add these variables to your .env file")
            return False
        
        print("✅ Configuration validated")
        return True
        
    except ImportError:
        print("⚠️ python-dotenv not available - using environment variables directly")
        return True

def check_mongodb():
    """Check if MongoDB is accessible."""
    try:
        from pymongo import MongoClient
        from dotenv import load_dotenv
        
        load_dotenv()
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
        client.server_info()  # Test connection
        client.close()
        print("✅ MongoDB connection successful")
        return True
        
    except ImportError:
        print("⚠️ pymongo not available - database features may be limited")
        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        print("🔧 Make sure MongoDB is running and accessible")
        print("💡 You can still run the bot with limited functionality")
        return True  # Don't fail completely, just warn

def show_startup_banner():
    """Display the startup banner."""
    print("=" * 60)
    print("🎮 LudoManager - Telegram Ludo Game Management Bot")
    print("=" * 60)
    print(f"⏰ Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("📡 Mode: Pyrogram Listener + Bot Manager Integration")
    print("🎯 Features: Game Detection, Winner Processing, Balance Management")
    print("=" * 60)

def main():
    """Main entry point for the LudoManager system."""
    show_startup_banner()
    
    print("\n🔍 Pre-flight checks...")
    print("-" * 30)
    
    # Check all prerequisites
    if not check_dependencies():
        print("\n❌ Dependency check failed!")
        return False
    
    if not check_configuration():
        print("\n❌ Configuration check failed!")
        return False
    
    check_mongodb()  # This can warn but not fail
    
    print("\n✅ All checks passed!")
    print("-" * 30)
    
    try:
        print("\n🚀 Starting LudoManager system...")
        print("📡 Initializing Pyrogram listener...")
        print("🧠 Loading bot manager...")
        print("🔗 Setting up integration...")
        
        # Import and initialize bot manager
        from . import bot
        bot.initialize_bot_manager()
        print("✅ Bot manager initialized with all features")
        
        # Start the Pyrogram listener
        print("📻 Starting Pyrogram listener for message detection...")
        from . import test
        
        print("\n" + "=" * 60)
        print("🎉 LudoManager is now running!")
        print("👂 Listening for game tables and winner declarations...")
        print("🛑 Press Ctrl+C to stop")
        print("=" * 60)
        
        # This will run indefinitely until interrupted
        # The test module handles the Pyrogram client execution
        
    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("👋 LudoManager stopped by user")
        print("🧹 Cleaning up...")
        print("✅ Goodbye!")
        print("=" * 60)
        return True
        
    except ImportError as e:
        print(f"\n❌ Import error: {e}")
        print("💡 Make sure you're running from the correct directory")
        print("💡 Try: cd to parent directory and run 'python -m LudoManagerMain'")
        return False
        
    except Exception as e:
        print(f"\n❌ Error starting LudoManager: {e}")
        logging.error(f"Startup error: {e}")
        return False

if __name__ == "__main__":
    # Configure basic logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    success = main()
    if not success:
        sys.exit(1)
