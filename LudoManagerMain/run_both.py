#!/usr/bin/env python3
"""
Simple Bot Runner - Threading Approach
=====================================
This runs both systems using simple threading to avoid async conflicts.
"""

import threading
import time
import signal
import sys
import os
from datetime import datetime

# Make sure we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Global variables to track threads
bot_thread = None
pyrogram_thread = None
running = True

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    global running
    print(f"\n🛑 Received shutdown signal, stopping both systems...")
    running = False
    sys.exit(0)

def run_bot_system():
    """Run the bot.py system - handles all Telegram Bot API commands"""
    try:
        print("🤖 [BOT THREAD] Starting Telegram Bot API system...")
        
        # Import bot module
        import bot
        
        # Create bot manager instance
        print("🤖 [BOT THREAD] Creating bot manager...")
        bot_manager = bot.LudoBotManager()
        
        # Run the bot (this will block this thread)
        print("🤖 [BOT THREAD] Starting bot polling...")
        bot_manager.run()  # This is the synchronous version
        
    except Exception as e:
        print(f"❌ [BOT THREAD] Error: {e}")
        import traceback
        traceback.print_exc()

def run_pyrogram_system():
    """Run the test.py system - handles Pyrogram message detection"""
    try:
        # Wait for bot system to initialize
        print("📡 [PYROGRAM THREAD] Waiting for bot system to start...")
        time.sleep(5)
        
        print("📡 [PYROGRAM THREAD] Starting Pyrogram listener...")
        
        # Import test module  
        import test
        
        # Run standalone Pyrogram (it will create its own bot manager)
        print("📡 [PYROGRAM THREAD] Running Pyrogram standalone...")
        test.start_standalone()
        
    except Exception as e:
        print(f"❌ [PYROGRAM THREAD] Error: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Main function to start both systems"""
    global bot_thread, pyrogram_thread, running
    
    print("🚀 LudoManager Dual System Launcher")
    print("=" * 60)
    print(f"⏰ Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🔧 Method: Simple Threading (No Async Conflicts)")
    print("=" * 60)
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("\n🎯 Starting both systems...")
    print("🤖 System 1: Telegram Bot API (/start, /balance, /help)")
    print("📡 System 2: Pyrogram (game detection)")
    print("-" * 40)
    
    try:
        # Start bot system in separate thread
        print("🚀 Starting bot thread...")
        bot_thread = threading.Thread(
            target=run_bot_system,
            name="BotSystem",
            daemon=False  # Don't make it daemon so program waits
        )
        bot_thread.start()
        print("✅ Bot thread started")
        
        # Start pyrogram system in separate thread
        print("🚀 Starting Pyrogram thread...")
        pyrogram_thread = threading.Thread(
            target=run_pyrogram_system,
            name="PyrogramSystem", 
            daemon=False  # Don't make it daemon so program waits
        )
        pyrogram_thread.start()
        print("✅ Pyrogram thread started")
        
        print("\n" + "=" * 60)
        print("🎉 BOTH SYSTEMS ARE RUNNING!")
        print("🤖 Bot commands: /start, /balance, /help are active")
        print("📡 Game detection: Table & winner detection active")
        print("🛑 Press Ctrl+C to stop both systems")
        print("=" * 60)
        
        # Monitor both threads
        while running:
            time.sleep(2)
            
            # Check if bot thread is alive
            if not bot_thread.is_alive():
                print("\n⚠️ Bot thread stopped!")
                print("🔍 Checking if it was intentional...")
                break
                
            # Check if pyrogram thread is alive  
            if not pyrogram_thread.is_alive():
                print("\n⚠️ Pyrogram thread stopped!")
                print("🔍 Checking if it was intentional...")
                break
                
            # Show status every 30 seconds
            if int(time.time()) % 30 == 0:
                print(f"🔄 [{datetime.now().strftime('%H:%M:%S')}] Both systems running...")
        
        print("\n👋 One or both systems stopped")
        
    except KeyboardInterrupt:
        print("\n👋 Stopped by user (Ctrl+C)")
        running = False
        
    except Exception as e:
        print(f"\n❌ Error in main loop: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        print("\n🧹 Cleaning up...")
        running = False
        
        # Wait for threads to finish
        if bot_thread and bot_thread.is_alive():
            print("⏳ Waiting for bot thread to stop...")
            bot_thread.join(timeout=5)
            
        if pyrogram_thread and pyrogram_thread.is_alive():
            print("⏳ Waiting for Pyrogram thread to stop...")
            pyrogram_thread.join(timeout=5)
            
        print("✅ Cleanup complete")

if __name__ == "__main__":
    main()
