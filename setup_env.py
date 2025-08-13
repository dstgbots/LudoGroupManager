#!/usr/bin/env python3
"""
Environment setup script for Ludo Group Manager Bot
This script helps you create the .env file with proper configuration
"""

import os

def setup_environment():
    """Interactive setup for environment variables"""
    print("🎮 Ludo Group Manager Bot - Environment Setup")
    print("=" * 50)
    
    env_vars = {}
    
    # Bot Token
    print("\n1. Bot Token Configuration")
    print("   - Go to @BotFather on Telegram")
    print("   - Use /newbot command to create a new bot")
    print("   - Copy the bot token")
    
    bot_token = input("\nEnter your Bot Token: ").strip()
    if not bot_token:
        print("❌ Bot token is required!")
        return False
    env_vars['BOT_TOKEN'] = bot_token
    
    # MongoDB Configuration
    print("\n2. MongoDB Configuration")
    mongo_uri = input("Enter MongoDB URI (press Enter for default 'mongodb://localhost:27017/'): ").strip()
    if not mongo_uri:
        mongo_uri = "mongodb://localhost:27017/"
    env_vars['MONGO_URI'] = mongo_uri
    
    database_name = input("Enter Database Name (press Enter for default 'ludo_bot'): ").strip()
    if not database_name:
        database_name = "ludo_bot"
    env_vars['DATABASE_NAME'] = database_name
    
    # Group ID
    print("\n3. Group Configuration")
    print("   - Add your bot to the Ludo group")
    print("   - Send any message in the group")
    print("   - Visit: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates")
    print("   - Find the chat with negative ID (like -1001234567890)")
    
    group_id = input("\nEnter your Group Chat ID (with negative sign): ").strip()
    if not group_id or not group_id.startswith('-'):
        print("❌ Group ID must be a negative number!")
        return False
    env_vars['GROUP_ID'] = group_id
    
    # Admin IDs
    print("\n4. Admin Configuration")
    print("   - Get admin user IDs from the same getUpdates response")
    print("   - Look for 'from' -> 'id' fields")
    
    admin_ids = input("\nEnter Admin User IDs (comma-separated): ").strip()
    if not admin_ids:
        print("❌ At least one admin ID is required!")
        return False
    env_vars['ADMIN_IDS'] = admin_ids
    
    # Pyrogram Configuration
    print("\n5. Pyrogram Configuration (for admin message editing)")
    print("   - This allows the bot to edit admin messages in the group")
    print("   - You can skip this if you prefer manual editing")
    
    use_pyrogram = input("\nDo you want to use Pyrogram for automatic message editing? (y/N): ").strip().lower()
    
    if use_pyrogram == 'y':
        print("\n   - Go to https://my.telegram.org/apps")
        print("   - Create a new application if you don't have one")
        print("   - Note down the API ID and API Hash")
        
        api_id = input("\nEnter API ID: ").strip()
        if api_id:
            env_vars['API_ID'] = api_id
            
        api_hash = input("Enter API Hash: ").strip()
        if api_hash:
            env_vars['API_HASH'] = api_hash
            
        print("\n   - Now you need to generate a session string")
        print("   - Run: python -c \"from pyrogram import Client; print(Client('test', api_id='YOUR_API_ID', api_hash='YOUR_API_HASH').export_session_string())\"")
        
        session_string = input("\nEnter Pyrogram Session String: ").strip()
        if session_string:
            env_vars['PYROGRAM_SESSION_STRING'] = session_string
        else:
            print("⚠️  Session string not provided - Pyrogram features will be disabled")
    else:
        print("⚠️  Pyrogram disabled - admin messages will need manual editing")
    
    # Create .env file
    env_content = ""
    for key, value in env_vars.items():
        env_content += f"{key}={value}\n"
    
    try:
        with open('.env', 'w') as f:
            f.write(env_content)
        
        print("\n✅ .env file created successfully!")
        print("\nConfiguration Summary:")
        print(f"   Bot Token: {bot_token[:10]}...")
        print(f"   MongoDB URI: {mongo_uri}")
        print(f"   Database: {database_name}")
        print(f"   Group ID: {group_id}")
        print(f"   Admin IDs: {admin_ids}")
        
        if 'API_ID' in env_vars:
            print(f"   API ID: {env_vars.get('API_ID')}")
            print(f"   API Hash: {env_vars.get('API_HASH', '')[:10]}...")
            print(f"   Pyrogram Session: {'✅ Configured' if 'PYROGRAM_SESSION_STRING' in env_vars else '❌ Not provided'}")
        else:
            print("   Pyrogram: ❌ Disabled")
        
        print("\n🚀 You can now run the bot with:")
        print("   python start_bot.py")
        print("   or")
        print("   python bot.py")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating .env file: {e}")
        return False

if __name__ == "__main__":
    if os.path.exists('.env'):
        response = input("⚠️  .env file already exists. Overwrite? (y/N): ").strip().lower()
        if response != 'y':
            print("Setup cancelled.")
            exit(0)
    
    if setup_environment():
        print("\n🎉 Setup completed successfully!")
    else:
        print("\n❌ Setup failed. Please try again.")
