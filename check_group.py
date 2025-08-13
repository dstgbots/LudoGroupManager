#!/usr/bin/env python3
"""
Simple script to check which group you're in
"""

import os
import asyncio
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()

async def check_current_group():
    """Check recent messages to see group IDs"""
    
    bot_token = os.getenv('BOT_TOKEN')
    configured_group = os.getenv('GROUP_ID')
    
    print(f"🔍 Configured Group ID: {configured_group}")
    print(f"🔍 Configured Group ID (as int): {int(configured_group) if configured_group else 'None'}")
    print("\n📋 Recent Group Messages:")
    print("=" * 40)
    
    try:
        if not bot_token:
            print("❌ BOT_TOKEN not found in environment variables!")
            return
            
        if not configured_group:
            print("❌ GROUP_ID not found in environment variables!")
            return
            
        bot = Bot(token=bot_token)
        updates = await bot.get_updates(limit=20)
        print(f"📬 Retrieved {len(updates)} recent updates")
        
        group_messages = []
        for update in updates:
            if update.message and update.message.chat.type in ['group', 'supergroup']:
                group_messages.append({
                    'group_id': update.message.chat.id,
                    'group_title': update.message.chat.title,
                    'message_text': update.message.text[:50] if update.message.text else "No text",
                    'from_user': update.message.from_user.first_name if update.message.from_user else "Unknown"
                })
        
        seen_groups = {}
        for msg in group_messages:
            group_id = msg['group_id']
            if group_id not in seen_groups:
                seen_groups[group_id] = msg
                
                status = "✅ MATCH" if str(group_id) == str(configured_group) else "❌ DIFFERENT"
                print(f"{status} Group: {msg['group_title']}")
                print(f"   ID: {group_id}")
                print(f"   Recent message: \"{msg['message_text']}\" by {msg['from_user']}")
                print()
        
        if not seen_groups:
            print("❌ No recent group messages found.")
            print("💡 Send a message in your group and run this script again.")
        
        print("💡 Make sure you're using the group that shows '✅ MATCH'")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_current_group())
