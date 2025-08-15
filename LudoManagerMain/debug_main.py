#!/usr/bin/env python3
"""
Debug version of __main__.py
==========================
This version adds extensive debugging to see exactly what's happening.
"""

import sys
import os
import logging
from datetime import datetime

# Configure detailed logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

def show_startup_banner():
    """Display startup information"""
    print("🚀 LudoManager System [DEBUG MODE]")
    print("=" * 60)
    print(f"⏰ Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🐛 Mode: Debug - Extensive Logging")
    print("=" * 60)

async def main():
    """Main entry point with debug output"""
    show_startup_banner()
    
    print("\n🔍 Starting debug analysis...")
    print("-" * 30)
    
    try:
        print("📥 Importing bot module...")
        import bot
        print("✅ Bot module imported successfully")
        
        print("📥 Importing test module...")
        import test
        print("✅ Test module imported successfully")
        
        print("🧠 Creating bot manager...")
        bot_manager = bot.LudoBotManager()
        print("✅ Bot manager created")
        
        print("🔄 Starting bot run_async()...")
        import asyncio
        
        # Create bot task
        print("📝 Creating bot task...")
        bot_task = asyncio.create_task(bot_manager.run_async())
        print(f"✅ Bot task created: {bot_task}")
        
        # Give it a moment
        print("⏳ Waiting 2 seconds...")
        await asyncio.sleep(2)
        
        print(f"🔍 Bot task status: {bot_task.done()}")
        if bot_task.done():
            print("⚠️ Bot task completed immediately!")
            if bot_task.exception():
                print(f"❌ Bot task exception: {bot_task.exception()}")
            else:
                print(f"✅ Bot task result: {bot_task.result()}")
        else:
            print("✅ Bot task is running")
        
        # Start pyrogram in a separate task
        def start_pyrogram():
            print("📡 [PYROGRAM] Starting...")
            test.start_with_bot_manager(bot_manager)
            print("📡 [PYROGRAM] Completed")
        
        print("📝 Creating Pyrogram task...")
        pyrogram_task = asyncio.create_task(
            asyncio.to_thread(start_pyrogram)
        )
        print(f"✅ Pyrogram task created: {pyrogram_task}")
        
        # Wait a bit more
        print("⏳ Waiting 3 more seconds...")
        await asyncio.sleep(3)
        
        print(f"🔍 Bot task status: {bot_task.done()}")
        print(f"🔍 Pyrogram task status: {pyrogram_task.done()}")
        
        if bot_task.done():
            print("⚠️ Bot task finished early!")
        if pyrogram_task.done():
            print("⚠️ Pyrogram task finished early!")
        
        # Try to wait for both
        print("⏳ Waiting for both tasks...")
        done, pending = await asyncio.wait(
            [bot_task, pyrogram_task], 
            timeout=10,
            return_when=asyncio.FIRST_COMPLETED
        )
        
        print(f"🔍 Done tasks: {len(done)}")
        print(f"🔍 Pending tasks: {len(pending)}")
        
        for task in done:
            if task.exception():
                print(f"❌ Task failed: {task.exception()}")
            else:
                print(f"✅ Task completed: {task.result()}")
        
        # Cancel pending tasks
        for task in pending:
            print(f"🛑 Cancelling pending task: {task}")
            task.cancel()
        
        print("🔍 Debug analysis complete")
        
    except Exception as e:
        print(f"\n❌ Error in debug main: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    import asyncio
    success = asyncio.run(main())
    if not success:
        sys.exit(1)
