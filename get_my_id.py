#!/usr/bin/env python3
"""
Get your Telegram user ID from recent bot interactions
"""

import os
import asyncio
from telegram import Bot

async def get_user_id():
    """Get user ID from recent updates"""
    
    bot_token = "5664706056:AAGweTBRqnaS1oQVEWkgxXl1WL9wUO_zuiA"
    
    try:
        bot = Bot(token=bot_token)
        updates = await bot.get_updates(limit=50)
        
        print("👤 Recent Users Who Interacted with Bot:")
        print("=" * 45)
        
        seen_users = {}
        for update in updates:
            if update.message and update.message.from_user:
                user = update.message.from_user
                user_id = user.id
                
                if user_id not in seen_users:
                    seen_users[user_id] = user
                    
                    print(f"User: {user.first_name} {user.last_name or ''}")
                    print(f"Username: @{user.username or 'No username'}")
                    print(f"User ID: {user_id}")
                    print(f"Recent message: \"{update.message.text[:30] if update.message.text else 'No text'}...\"")
                    
                    if update.message.chat.type in ['group', 'supergroup']:
                        print(f"In group: {update.message.chat.title} (ID: {update.message.chat.id})")
                    print("-" * 30)
        
        if not seen_users:
            print("❌ No recent user interactions found.")
            print("💡 Send /start to the bot privately or use any command, then run this script again.")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(get_user_id())
