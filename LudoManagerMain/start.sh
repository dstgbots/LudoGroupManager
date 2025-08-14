#!/usr/bin/env python3
"""
LudoManager Startup Script
=========================
Easy way to start the LudoManager system with proper initialization.
"""

import os
import sys
import asyncio
import logging
from datetime import datetime

def check_dependencies():
    """Check if all required dependencies are installed."""
    # Map package names to their import names
    package_mapping = {
        'pyrogram': 'pyrogram',
        'pymongo': 'pymongo', 
        'python-telegram-bot': 'telegram',
        'python-dotenv': 'dotenv'
    }
    
    missing_packages = []
    
    for package_name, import_name in package_mapping.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package_name)
    
    if missing_packages:
        print("❌ Missing required packages:")
        for package in missing_packages:
            print(f"   - {package}")
        print("\n📦 Install missing packages with:")
        print(f"   pip install {' '.join(missing_packages)}")
        return False
    
    print("✅ All dependencies installed")
    return True

def check_configuration():
    """Check if configuration file exists and has required values."""
    if not os.path.exists('.env'):
        print("❌ .env file not found")
        print("📝 Create .env file from env_template.txt and configure your values")
        return False
    
    # Load and check critical env vars
    from dotenv import load_dotenv
    load_dotenv()
    
    required_vars = ['BOT_TOKEN', 'API_ID', 'API_HASH', 'GROUP_ID', 'ADMIN_IDS']
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print("❌ Missing required environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\n📝 Add these variables to your .env file")
        return False
    
    print("✅ Configuration file validated")
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
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        print("🔧 Make sure MongoDB is running and accessible")
        return False

async def start_full_system():
    """Start both bot.py and test.py systems"""
    print("\n🚀 Starting FULL LudoManager system...")
    print("🤖 Bot system: All commands (/start, /balance, etc.)")
    print("📡 Pyrogram system: Game detection")
    print("=" * 50)
    
    # Import both systems
    import bot
    import test
    
    # Initialize bot manager
    print("🔧 Initializing bot manager...")
    bot_manager = bot.LudoBotManager()
    
    # Start both systems concurrently
    try:
        # Create tasks for both systems
        bot_task = asyncio.create_task(bot_manager.run_async())
        
        # Start pyrogram in a separate task
        def start_pyrogram():
            test.start_with_bot_manager(bot_manager)
        
        pyrogram_task = asyncio.create_task(
            asyncio.to_thread(start_pyrogram)
        )
        
        print("✅ Both systems started!")
        print("🎯 LudoManager is now fully running!")
        print("👂 All features active: commands + game detection")
        print("🛑 Press Ctrl+C to stop")
        print("=" * 50)
        
        # Wait for both tasks
        await asyncio.gather(bot_task, pyrogram_task)
        
    except KeyboardInterrupt:
        print("\n👋 Full system stopped by user")
        bot_task.cancel()
        pyrogram_task.cancel()
    except Exception as e:
        print(f"\n❌ Error in full system: {e}")
        raise

def main():
    """Main startup function."""
    print("🚀 LudoManager System Startup")
    print("=" * 40)
    print(f"⏰ Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 40)
    
    # Check all prerequisites
    if not check_dependencies():
        return False
    
    if not check_configuration():
        return False
    
    if not check_mongodb():
        return False
    
    print("\n✅ All checks passed! Starting LudoManager...")
    print("=" * 40)
    
    # Start the full integrated system
    try:
        asyncio.run(start_full_system())
        return True
        
    except KeyboardInterrupt:
        print("\n👋 LudoManager stopped by user")
        return True
    except Exception as e:
        print(f"\n❌ Error starting LudoManager: {e}")
        return False

if __name__ == "__main__":
    success = main()
    if not success:
        sys.exit(1)
