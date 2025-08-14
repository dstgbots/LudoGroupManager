#!/usr/bin/env python3
"""
LudoManager Unified Launcher
===========================
Starts both test.py (Pyrogram listener) and bot.py (business logic) in one command.
"""

import os
import sys
import subprocess
import signal
import threading
import time
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class LudoManagerLauncher:
    def __init__(self):
        self.processes = []
        self.running = True
        
    def check_dependencies(self):
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
            print(f"\n📦 Install with: pip install {' '.join(missing_packages)}")
            return False
        
        print("✅ All dependencies installed")
        return True

    def check_configuration(self):
        """Check if configuration is properly set up."""
        if not os.path.exists('.env'):
            print("❌ .env file not found")
            print("📝 Create .env file from env_template.txt")
            return False
        
        # Basic validation
        from dotenv import load_dotenv
        load_dotenv()
        
        required_vars = ['BOT_TOKEN', 'API_ID', 'API_HASH', 'GROUP_ID', 'ADMIN_IDS']
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            print("❌ Missing environment variables:")
            for var in missing_vars:
                print(f"   - {var}")
            return False
        
        print("✅ Configuration validated")
        return True

    def start_pyrogram_listener(self):
        """Start the Pyrogram listener (test.py)"""
        try:
            print("🚀 Starting Pyrogram listener (test.py)...")
            
            # Import and initialize bot manager first
            import bot
            bot.initialize_bot_manager()
            print("✅ Bot manager initialized")
            
            # Now start the Pyrogram listener
            import test
            print("✅ Pyrogram listener started")
            
        except KeyboardInterrupt:
            print("👋 Pyrogram listener stopped by user")
        except Exception as e:
            logger.error(f"❌ Error in Pyrogram listener: {e}")
            raise

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print(f"\n🛑 Received signal {signum}, shutting down...")
        self.running = False
        
        # Cleanup processes
        for process in self.processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            except Exception as e:
                logger.error(f"Error terminating process: {e}")
        
        sys.exit(0)

    def run(self):
        """Main launcher function"""
        print("🚀 LudoManager Unified Launcher")
        print("=" * 50)
        print(f"⏰ Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 50)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Pre-flight checks
        if not self.check_dependencies():
            return False
        
        if not self.check_configuration():
            return False
        
        try:
            print("\n🎯 Starting integrated LudoManager system...")
            print("📡 Pyrogram listener will handle message detection")
            print("🧠 Bot manager will handle all business logic")
            print("🔗 Both components integrated in single process")
            print("=" * 50)
            
            # Start the integrated system
            self.start_pyrogram_listener()
            
        except KeyboardInterrupt:
            print("\n👋 LudoManager stopped by user")
            return True
        except Exception as e:
            print(f"\n❌ Error starting LudoManager: {e}")
            logger.error(f"Startup error: {e}")
            return False

def main():
    """Entry point"""
    launcher = LudoManagerLauncher()
    success = launcher.run()
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
