#!/usr/bin/env python3
"""
Quick script to get your group chat ID
"""

import os
import asyncio
from telegram import Bot
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def get_group_info():
    """Get recent updates to find group ID"""
    bot_token = input("Enter your bot token: ").strip()
    
    if not bot_token:
        print("❌ Bot token is required!")
        return
    
    try:
        bot = Bot(token=bot_token)
        
        print("🔍 Getting recent updates...")
        updates = await bot.get_updates(limit=10)
        
        if not updates:
            print("❌ No recent updates found.")
            print("💡 Send a message in your group where the bot is added, then run this script again.")
            return
        
        print("\n📋 Recent Chats:")
        print("=" * 50)
        
        seen_chats = set()
        for update in updates:
            if update.message:
                chat = update.message.chat
                if chat.id not in seen_chats:
                    seen_chats.add(chat.id)
                    chat_type = "🏠 Private" if chat.type == "private" else "👥 Group"
                    print(f"{chat_type} Chat:")
                    print(f"   ID: {chat.id}")
                    print(f"   Title: {chat.title or chat.first_name}")
                    print(f"   Type: {chat.type}")
                    print()
        
        print("💡 Use the GROUP chat ID (negative number) in your .env file")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("💡 Make sure:")
        print("   1. Bot token is correct")
        print("   2. Bot is added to your group")
        print("   3. Recent messages exist in the group")

if __name__ == "__main__":
    asyncio.run(get_group_info())
